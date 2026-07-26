"""Bounded NVIDIA NIM agent for schema-validated EnergyPlus MCP tool use."""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from dotenv import load_dotenv
from openai import OpenAI

from src.mcp.energyplus_mcp_client import EnergyPlusMCPClient, MCPToolResult
from src.mcp.tool_guard import (
    DEFAULT_AGENT_TOOLS,
    MCPToolGuard,
    MODIFICATION_TOOLS,
)
from src.simulation_upload.workspace import RunWorkspace


SYSTEM_PROMPT = """/no_think
You are an EnergyPlus simulation agent.
Use EnergyPlus MCP tools whenever an answer depends on the uploaded model.
You may inspect, validate, and simulate only files inside the assigned run.
Never invent model contents, zones, schedules, outputs, loops, or results.
Never request or expose secrets. Never execute shell commands or source code.
Use only the supplied tools. Validate before simulation. Do not modify the
original IDF. Do not run more than one simulation.
Respond with exactly one supplied function call at a time. Do not emit normal
assistant text, markdown, JSON examples, or hidden reasoning. Use finish_task
only after every tool explicitly required by the task has completed.
"""


class AgentModel(Protocol):
    last_latency_seconds: float | None

    def complete(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
    ) -> str:
        ...


class NvidiaNIMEnergyPlusModel:
    """OpenAI-compatible NVIDIA transport dedicated to the MCP agent."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 45.0,
        max_tokens: int = 700,
        client: Any | None = None,
    ) -> None:
        load_dotenv(".env", override=False)
        secret = api_key or os.getenv("NVIDIA_NIM_API_KEY", "")
        if not secret:
            raise ValueError("NVIDIA_NIM_API_KEY is not configured")
        self.model = model or os.getenv(
            "NVIDIA_NIM_MODEL",
            "nvidia/llama-3.3-nemotron-super-49b-v1.5",
        )
        self.client = client or OpenAI(
            base_url=base_url
            or os.getenv(
                "NVIDIA_NIM_BASE_URL", "https://integrate.api.nvidia.com/v1"
            ),
            api_key=secret,
            timeout=timeout_seconds,
            max_retries=1,
        )
        self.max_tokens = max_tokens
        self.last_latency_seconds: float | None = None

    def complete(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
    ) -> str:
        started = time.perf_counter()
        try:
            request: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "temperature": 0,
                "top_p": 1,
                "max_tokens": self.max_tokens,
                "stream": False,
            }
            if tools:
                native_tools = [
                    {
                        "type": "function",
                        "function": {
                            "name": tool["name"],
                            "description": tool.get("description", "")[:1024],
                            "parameters": tool.get(
                                "input_schema", {"type": "object"}
                            ),
                        },
                    }
                    for tool in tools
                ]
                native_tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": "finish_task",
                            "description": (
                                "Return the final user-facing result only after "
                                "all required MCP inspections are complete."
                            ),
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "status": {
                                        "type": "string",
                                        "enum": ["ready", "failed", "completed"],
                                    },
                                    "summary": {"type": "string"},
                                    "next_steps": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                },
                                "required": [
                                    "status",
                                    "summary",
                                    "next_steps",
                                ],
                                "additionalProperties": False,
                            },
                        },
                    }
                )
                request["tools"] = native_tools
                request["tool_choice"] = "required"
                request["parallel_tool_calls"] = False
            else:
                request["response_format"] = {"type": "json_object"}

            response = self.client.chat.completions.create(**request)
            choices = getattr(response, "choices", None)
            if not choices:
                raise RuntimeError("NVIDIA NIM returned no choices")
            message = choices[0].message
            tool_calls = getattr(message, "tool_calls", None)
            if tool_calls:
                if len(tool_calls) != 1:
                    raise RuntimeError(
                        "NVIDIA NIM returned multiple native tool calls"
                    )
                function = tool_calls[0].function
                try:
                    arguments = json.loads(function.arguments)
                except json.JSONDecodeError:
                    raise RuntimeError(
                        "NVIDIA NIM returned malformed native tool arguments"
                    ) from None
                if not isinstance(arguments, dict):
                    raise RuntimeError(
                        "NVIDIA NIM native tool arguments must be an object"
                    )
                if function.name == "finish_task":
                    return json.dumps({"action": "final", **arguments})
                return json.dumps(
                    {
                        "action": "call_tool",
                        "tool_name": function.name,
                        "arguments": arguments,
                        "reason": f"NVIDIA selected {function.name}.",
                    }
                )

            content = getattr(message, "content", None)
            if tools:
                raise RuntimeError(
                    "NVIDIA NIM did not return the required native tool call"
                )
            if not isinstance(content, str) or not content.strip():
                raise RuntimeError("NVIDIA NIM returned empty content")
            return content.strip()
        finally:
            self.last_latency_seconds = time.perf_counter() - started


@dataclass
class AgentActivity:
    step: int
    tool_requested: str | None
    accepted: bool
    rejection_category: str | None
    reason: str
    arguments_summary: dict[str, Any]
    tool_duration_seconds: float | None
    tool_success: bool | None
    result_summary: str
    nvidia_latency_seconds: float | None


@dataclass
class EnergyPlusAgentResult:
    status: str
    summary: str
    next_steps: list[str]
    activities: list[AgentActivity] = field(default_factory=list)
    simulation_launched: bool = False
    simulation_completed: bool = False
    fallback_used: bool = False
    tool_results: dict[str, list[str]] = field(default_factory=dict)


class EnergyPlusAgent:
    def __init__(
        self,
        mcp_client: EnergyPlusMCPClient,
        model: AgentModel,
        workspace: RunWorkspace,
        *,
        maximum_steps: int = 10,
        allow_modifications: bool = False,
    ) -> None:
        if not 1 <= maximum_steps <= 12:
            raise ValueError("maximum_steps must be between 1 and 12")
        self.mcp_client = mcp_client
        self.model = model
        self.workspace = workspace
        self.maximum_steps = maximum_steps
        self.allow_modifications = allow_modifications

    @staticmethod
    def _parse_action(raw: str) -> dict[str, Any]:
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Model response is not strict JSON: {exc}") from None
        if not isinstance(value, dict):
            raise ValueError("Model response must be one JSON object")
        action = value.get("action")
        if action == "call_tool":
            allowed = {"action", "tool_name", "arguments", "reason"}
            if set(value) - allowed:
                raise ValueError("Tool request contains unknown fields")
            if (
                not isinstance(value.get("tool_name"), str)
                or not isinstance(value.get("arguments"), dict)
                or not isinstance(value.get("reason"), str)
            ):
                raise ValueError("Tool request fields have invalid types")
            return value
        if action == "final":
            allowed = {"action", "status", "summary", "next_steps"}
            if set(value) - allowed:
                raise ValueError("Final response contains unknown fields")
            if value.get("status") not in {"ready", "failed", "completed"}:
                raise ValueError("Final status is invalid")
            if not isinstance(value.get("summary"), str) or not isinstance(
                value.get("next_steps"), list
            ):
                raise ValueError("Final response fields have invalid types")
            if not all(isinstance(item, str) for item in value["next_steps"]):
                raise ValueError("Every next_steps item must be text")
            return value
        raise ValueError("Model action must be call_tool or final")

    def _safe_summary(self, text: object, limit: int = 1200) -> str:
        text = str(text)
        replacements = {
            str(self.workspace.root),
            self.workspace.root.as_posix(),
        }
        client_config = getattr(self.mcp_client, "config", None)
        if client_config is not None:
            replacements.add(
                client_config.server_run_root(self.workspace.run_id)
            )
        for path in sorted(replacements, key=len, reverse=True):
            text = text.replace(path, "<run>")
            text = text.replace(path.replace("\\", "\\\\"), "<run>")
        text = re.sub(r"[A-Za-z]:\\[^\s\"']+", "<run-path>", text)
        text = re.sub(r"/(?:[^/\s]+/)+[^/\s]+", "<run-path>", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:limit]

    def _write_activity(self, result: EnergyPlusAgentResult) -> None:
        path = self.workspace.metadata_dir / "agent_activity.json"
        path.write_text(
            json.dumps(
                {
                    "run_id": self.workspace.run_id,
                    "status": result.status,
                    "simulation_launched": result.simulation_launched,
                    "simulation_completed": result.simulation_completed,
                    "fallback_used": result.fallback_used,
                    "activities": [
                        asdict(activity) for activity in result.activities
                    ],
                    "final_summary": result.summary,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    async def run(
        self,
        user_task: str,
        *,
        simulation_approved: bool = False,
    ) -> EnergyPlusAgentResult:
        await self.mcp_client.initialize()
        schemas = self.mcp_client.tool_schemas
        client_config = getattr(self.mcp_client, "config", None)
        server_run_root = (
            client_config.server_run_root(self.workspace.run_id)
            if client_config is not None
            else str(self.workspace.root)
        )
        guard = MCPToolGuard(
            self.workspace.root,
            schemas,
            allow_modifications=self.allow_modifications,
            server_run_root=server_run_root,
        )
        visible_tools = [
            {
                "name": name,
                "description": schema.get("description", "")[:500],
                "input_schema": schema.get("input_schema", {}),
            }
            for name, schema in schemas.items()
            if name in DEFAULT_AGENT_TOOLS
            or (self.allow_modifications and name in MODIFICATION_TOOLS)
        ]
        context = {
            "task": user_task,
            "run_id": self.workspace.run_id,
            "idf_path": guard.server_path(
                next(self.workspace.input_dir.rglob("*.idf"))
            ),
            "epw_path": guard.server_path(
                next(self.workspace.input_dir.rglob("*.epw"))
            ),
            "output_directory": guard.server_path(self.workspace.output_dir),
            "simulation_approved": simulation_approved,
            "modifications_allowed": self.allow_modifications,
            "available_tools": [tool["name"] for tool in visible_tools],
        }
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(context)},
        ]
        activities: list[AgentActivity] = []
        results: dict[str, list[str]] = {}
        successful_tools: set[str] = set()
        simulation_calls = 0

        for step in range(1, self.maximum_steps + 1):
            try:
                raw = await asyncio.to_thread(
                    self.model.complete, messages, visible_tools
                )
                action = self._parse_action(raw)
            except Exception as exc:
                outcome = EnergyPlusAgentResult(
                    status="failed",
                    summary=f"Agent stopped safely: {self._safe_summary(exc)}",
                    next_steps=["Retry the bounded inspection or inspect MCP health."],
                    activities=activities,
                    fallback_used=True,
                    tool_results=results,
                )
                self._write_activity(outcome)
                return outcome

            if action["action"] == "final":
                outcome = EnergyPlusAgentResult(
                    status=action["status"],
                    summary=action["summary"][:2000],
                    next_steps=action["next_steps"][:8],
                    activities=activities,
                    simulation_launched=simulation_calls > 0,
                    simulation_completed=(
                        "run_energyplus_simulation" in successful_tools
                    ),
                    tool_results=results,
                )
                self._write_activity(outcome)
                return outcome

            tool_name = action["tool_name"]
            arguments = action["arguments"]
            reason = action["reason"][:240]
            rejection: str | None = None
            if tool_name == "run_energyplus_simulation":
                if not simulation_approved:
                    rejection = "human_approval_required"
                elif "validate_idf" not in successful_tools:
                    rejection = "validation_required"
                elif simulation_calls >= 1:
                    rejection = "simulation_limit"
            if tool_name in MODIFICATION_TOOLS and not self.allow_modifications:
                rejection = "modifications_disabled"

            authorization = guard.authorize(tool_name, arguments)
            if rejection or not authorization.accepted:
                category = rejection or authorization.rejection_category
                message = (
                    "Tool request rejected: "
                    + (rejection or authorization.message)
                )
                activities.append(
                    AgentActivity(
                        step=step,
                        tool_requested=tool_name,
                        accepted=False,
                        rejection_category=category,
                        reason=reason,
                        arguments_summary={
                            key: Path(value).name
                            if key.endswith(("path", "directory"))
                            and isinstance(value, str)
                            else value
                            for key, value in arguments.items()
                        },
                        tool_duration_seconds=None,
                        tool_success=False,
                        result_summary=message,
                        nvidia_latency_seconds=self.model.last_latency_seconds,
                    )
                )
                messages.extend(
                    [
                        {"role": "assistant", "content": raw},
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "tool_status": "rejected",
                                    "category": category,
                                    "message": message,
                                }
                            ),
                        },
                    ]
                )
                continue

            if tool_name == "run_energyplus_simulation":
                simulation_calls += 1
            tool_result: MCPToolResult = await self.mcp_client.call_tool(
                tool_name, authorization.arguments
            )
            summary = self._safe_summary(tool_result.text_content)
            activities.append(
                AgentActivity(
                    step=step,
                    tool_requested=tool_name,
                    accepted=True,
                    rejection_category=tool_result.error_category,
                    reason=reason,
                    arguments_summary={
                        key: Path(value).name
                        if key.endswith(("path", "directory"))
                        and isinstance(value, str)
                        else value
                        for key, value in authorization.arguments.items()
                    },
                    tool_duration_seconds=tool_result.elapsed_seconds,
                    tool_success=not tool_result.is_error,
                    result_summary=summary,
                    nvidia_latency_seconds=self.model.last_latency_seconds,
                )
            )
            results.setdefault(tool_name, []).append(tool_result.text_content)
            if not tool_result.is_error:
                successful_tools.add(tool_name)
            messages.extend(
                [
                    {"role": "assistant", "content": raw},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "tool_name": tool_name,
                                "success": not tool_result.is_error,
                                "error_category": tool_result.error_category,
                                "result": summary,
                            }
                        ),
                    },
                ]
            )

        outcome = EnergyPlusAgentResult(
            status="failed",
            summary=f"Agent stopped at the {self.maximum_steps}-step safety limit.",
            next_steps=["Narrow the requested inspection and retry."],
            activities=activities,
            simulation_launched=simulation_calls > 0,
            simulation_completed="run_energyplus_simulation" in successful_tools,
            fallback_used=True,
            tool_results=results,
        )
        self._write_activity(outcome)
        return outcome
