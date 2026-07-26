"""Typed, secret-safe client for the official EnergyPlus MCP HTTP service."""

from __future__ import annotations

import json
import re
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from .config import EnergyPlusMCPConfig


@dataclass(frozen=True)
class MCPHealthResult:
    healthy: bool
    elapsed_seconds: float
    error_category: str | None = None
    message: str = ""


@dataclass(frozen=True)
class MCPServerInfo:
    name: str
    version: str
    protocol_version: str


@dataclass(frozen=True)
class MCPToolResult:
    tool_name: str
    structured_content: dict[str, Any] | list[Any] | None
    text_content: str
    is_error: bool
    elapsed_seconds: float
    error_category: str | None = None


class EnergyPlusMCPClient:
    """Safely reusable MCP session.

    Use one instance inside one async context. Dashboard actions create a fresh
    instance per worker, avoiding event-loop leakage across Streamlit reruns.
    """

    def __init__(self, config: EnergyPlusMCPConfig) -> None:
        self.config = config
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._tools: dict[str, dict[str, Any]] = {}
        self.server_info: MCPServerInfo | None = None

    async def __aenter__(self) -> "EnergyPlusMCPClient":
        await self.initialize()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    @property
    def tool_schemas(self) -> dict[str, dict[str, Any]]:
        return dict(self._tools)

    def _health_url(self) -> str:
        parts = urlsplit(self.config.url)
        return urlunsplit((parts.scheme, parts.netloc, "/health", "", ""))

    def _redact(self, value: object) -> str:
        text = str(value)
        if self.config.token:
            text = text.replace(self.config.token, "<redacted>")
        text = re.sub(
            r"(?i)(authorization\s*[:=]\s*bearer\s+)\S+",
            r"\1<redacted>",
            text,
        )
        return text

    @staticmethod
    def _categorize(exc: BaseException) -> str:
        text = str(exc).lower()
        if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
            return "timeout"
        if (
            "401" in text
            or "403" in text
            or "unauthor" in text
            or "authentication" in text
            or "forbidden" in text
        ):
            return "authentication"
        if isinstance(exc, (httpx.ConnectError, httpx.NetworkError)):
            return "server_unavailable"
        if "json" in text or "malformed" in text or "decode" in text:
            return "malformed_response"
        if "session" in text or "disconnect" in text or "closed" in text:
            return "disconnected"
        return "mcp_error"

    async def health_check(self) -> MCPHealthResult:
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                timeout=min(self.config.timeout_seconds, 10.0)
            ) as client:
                response = await client.get(self._health_url())
                response.raise_for_status()
                payload = response.json()
            healthy = isinstance(payload, dict) and payload.get("status") == "ok"
            return MCPHealthResult(
                healthy=healthy,
                elapsed_seconds=time.perf_counter() - started,
                error_category=None if healthy else "malformed_response",
                message="ok" if healthy else "Health response did not report status=ok",
            )
        except Exception as exc:
            return MCPHealthResult(
                healthy=False,
                elapsed_seconds=time.perf_counter() - started,
                error_category=self._categorize(exc),
                message=self._redact(exc),
            )

    async def initialize(self) -> MCPServerInfo:
        if self._session is not None and self.server_info is not None:
            return self.server_info
        if not self.config.enabled:
            raise RuntimeError("EnergyPlus MCP integration is disabled")

        stack = AsyncExitStack()
        try:
            http_client = await stack.enter_async_context(
                httpx.AsyncClient(
                    headers={
                        "Authorization": f"Bearer {self.config.token}",
                        "Accept": "application/json, text/event-stream",
                    },
                    timeout=self.config.timeout_seconds,
                )
            )
            streams = await stack.enter_async_context(
                streamable_http_client(
                    self.config.url,
                    http_client=http_client,
                    terminate_on_close=True,
                )
            )
            session = await stack.enter_async_context(
                ClientSession(
                    streams[0],
                    streams[1],
                    read_timeout_seconds=timedelta(
                        seconds=self.config.timeout_seconds
                    ),
                )
            )
            result = await session.initialize()
            self._stack = stack
            self._session = session
            self.server_info = MCPServerInfo(
                name=result.serverInfo.name,
                version=result.serverInfo.version,
                protocol_version=result.protocolVersion,
            )
            await self.list_tools()
            return self.server_info
        except Exception as exc:
            await stack.aclose()
            raise RuntimeError(
                f"MCP initialization failed ({self._categorize(exc)}): "
                f"{self._redact(exc)}"
            ) from None

    async def list_tools(self) -> list[dict[str, Any]]:
        if self._session is None:
            await self.initialize()
        assert self._session is not None
        try:
            response = await self._session.list_tools()
            tools = [
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "input_schema": tool.inputSchema,
                }
                for tool in response.tools
            ]
            self._tools = {tool["name"]: tool for tool in tools}
            return tools
        except Exception as exc:
            raise RuntimeError(
                f"MCP list_tools failed ({self._categorize(exc)}): "
                f"{self._redact(exc)}"
            ) from None

    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> MCPToolResult:
        started = time.perf_counter()
        if self._session is None:
            try:
                await self.initialize()
            except Exception as exc:
                return MCPToolResult(
                    tool_name=tool_name,
                    structured_content=None,
                    text_content=self._redact(exc),
                    is_error=True,
                    elapsed_seconds=time.perf_counter() - started,
                    error_category=self._categorize(exc),
                )

        if tool_name not in self._tools:
            return MCPToolResult(
                tool_name=tool_name,
                structured_content=None,
                text_content=f"Unknown MCP tool: {tool_name}",
                is_error=True,
                elapsed_seconds=time.perf_counter() - started,
                error_category="unknown_tool",
            )

        assert self._session is not None
        try:
            result = await self._session.call_tool(
                tool_name,
                arguments,
                read_timeout_seconds=timedelta(
                    seconds=(
                        self.config.simulation_timeout_seconds
                        if tool_name == "run_energyplus_simulation"
                        else self.config.timeout_seconds
                    )
                ),
            )
            text_parts = [
                str(getattr(item, "text"))
                for item in result.content
                if getattr(item, "type", None) == "text"
            ]
            joined_text = "\n".join(text_parts)
            structured = result.structuredContent
            if (
                isinstance(structured, dict)
                and set(structured) == {"result"}
                and isinstance(structured["result"], str)
            ):
                wrapped = structured["result"]
                start = min(
                    (
                        index
                        for index in (wrapped.find("{"), wrapped.find("["))
                        if index >= 0
                    ),
                    default=-1,
                )
                if start >= 0:
                    closing = "}" if wrapped[start] == "{" else "]"
                    end = wrapped.rfind(closing)
                    try:
                        structured = json.loads(wrapped[start : end + 1])
                    except json.JSONDecodeError:
                        pass
            if not structured and text_parts:
                candidate = joined_text.strip()
                starts = [
                    index
                    for index in (candidate.find("{"), candidate.find("["))
                    if index >= 0
                ]
                if starts:
                    start = min(starts)
                    closing = "}" if candidate[start] == "{" else "]"
                    end = candidate.rfind(closing)
                    try:
                        parsed = json.loads(candidate[start : end + 1])
                        if isinstance(parsed, (dict, list)):
                            structured = parsed
                    except json.JSONDecodeError:
                        pass
            semantic_error = joined_text.lstrip().lower().startswith(
                (
                    "error ",
                    "error:",
                    "file not found",
                    "files not found",
                    "invalid input",
                )
            )
            if isinstance(structured, dict) and structured.get("success") is False:
                semantic_error = True
            is_error = bool(result.isError) or semantic_error
            return MCPToolResult(
                tool_name=tool_name,
                structured_content=structured,
                text_content=self._redact(joined_text),
                is_error=is_error,
                elapsed_seconds=time.perf_counter() - started,
                error_category="tool_execution" if is_error else None,
            )
        except Exception as exc:
            return MCPToolResult(
                tool_name=tool_name,
                structured_content=None,
                text_content=self._redact(exc),
                is_error=True,
                elapsed_seconds=time.perf_counter() - started,
                error_category=self._categorize(exc),
            )

    async def close(self) -> None:
        stack, self._stack = self._stack, None
        self._session = None
        self._tools = {}
        self.server_info = None
        if stack is not None:
            await stack.aclose()
