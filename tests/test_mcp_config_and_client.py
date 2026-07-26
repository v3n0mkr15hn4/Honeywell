from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.mcp.config import EnergyPlusMCPConfig, MCPConfigurationError
from src.mcp.energyplus_mcp_client import EnergyPlusMCPClient


class MCPConfigurationTests(unittest.TestCase):
    def test_enabled_configuration_requires_long_token(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(MCPConfigurationError):
                EnergyPlusMCPConfig(
                    enabled=True,
                    url="http://127.0.0.1:8000/mcp",
                    token="short",
                    workspace_root=root,
                )

    def test_repr_redacts_token(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            token = "a" * 40
            config = EnergyPlusMCPConfig(
                enabled=True,
                url="http://127.0.0.1:8000/mcp",
                token=token,
                workspace_root=root,
            )
        self.assertNotIn(token, repr(config))
        self.assertIn("<redacted>", repr(config))


class MCPClientTests(unittest.TestCase):
    def make_client(self) -> EnergyPlusMCPClient:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        return EnergyPlusMCPClient(
            EnergyPlusMCPConfig(
                enabled=True,
                url="http://127.0.0.1:8000/mcp",
                token="secret-token-" + "x" * 32,
                workspace_root=self.temp.name,
            )
        )

    def test_valid_tool_call_is_normalized(self) -> None:
        client = self.make_client()
        client._tools = {"validate_idf": {"name": "validate_idf"}}
        client._session = AsyncMock()
        client._session.call_tool.return_value = SimpleNamespace(
            content=[SimpleNamespace(type="text", text='{"valid": true}')],
            structuredContent=None,
            isError=False,
        )
        result = asyncio.run(
            client.call_tool("validate_idf", {"idf_path": "model.idf"})
        )
        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content, {"valid": True})

    def test_unknown_tool_is_rejected_without_transport(self) -> None:
        client = self.make_client()
        client._session = AsyncMock()
        result = asyncio.run(client.call_tool("execute_shell", {}))
        self.assertTrue(result.is_error)
        self.assertEqual(result.error_category, "unknown_tool")
        client._session.call_tool.assert_not_called()

    def test_secret_is_redacted_from_failure(self) -> None:
        client = self.make_client()
        client._tools = {"validate_idf": {"name": "validate_idf"}}
        client._session = AsyncMock()
        client._session.call_tool.side_effect = RuntimeError(
            f"Authorization: Bearer {client.config.token}"
        )
        result = asyncio.run(client.call_tool("validate_idf", {}))
        self.assertNotIn(client.config.token, result.text_content)
        self.assertIn("<redacted>", result.text_content)

    def test_timeout_is_categorized(self) -> None:
        client = self.make_client()
        client._tools = {"validate_idf": {"name": "validate_idf"}}
        client._session = AsyncMock()
        client._session.call_tool.side_effect = TimeoutError()
        result = asyncio.run(client.call_tool("validate_idf", {}))
        self.assertEqual(result.error_category, "timeout")


if __name__ == "__main__":
    unittest.main()
