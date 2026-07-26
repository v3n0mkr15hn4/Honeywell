from __future__ import annotations

import asyncio
import tempfile
import unittest

from src.agent.energyplus_agent import EnergyPlusAgent
from src.mcp.energyplus_mcp_client import MCPToolResult
from src.simulation_upload.workspace import RunWorkspaceManager


SCHEMAS = {
    name: {
        "name": name,
        "description": name,
        "input_schema": {
            "type": "object",
            "properties": {
                "idf_path": {"type": "string"},
                **(
                    {
                        "weather_file": {"type": "string"},
                        "output_directory": {"type": "string"},
                    }
                    if name == "run_energyplus_simulation"
                    else {}
                ),
            },
            "required": ["idf_path"],
        },
    }
    for name in ("validate_idf", "run_energyplus_simulation")
}
SCHEMAS["modify_run_period"] = {
    "name": "modify_run_period",
    "description": "modify",
    "input_schema": {
        "type": "object",
        "properties": {
            "idf_path": {"type": "string"},
            "field_updates": {"type": "object"},
        },
        "required": ["idf_path", "field_updates"],
    },
}


class FakeClient:
    def __init__(self) -> None:
        self.tool_schemas = SCHEMAS
        self.calls: list[str] = []

    async def initialize(self) -> None:
        return None

    async def call_tool(self, name, arguments):
        self.calls.append(name)
        return MCPToolResult(
            tool_name=name,
            structured_content={"success": True},
            text_content='{"success": true}',
            is_error=False,
            elapsed_seconds=0.01,
        )


class SequenceModel:
    def __init__(self, responses: list[str]) -> None:
        self.responses = iter(responses)
        self.last_latency_seconds = 0.01

    def complete(self, messages, tools=None):
        return next(self.responses)


class AgentTests(unittest.TestCase):
    def workspace(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        workspace = RunWorkspaceManager(temp.name).create()
        (workspace.input_dir / "model.idf").write_text(
            "Version,26.1;", encoding="utf-8"
        )
        (workspace.input_dir / "weather.epw").write_text(
            "LOCATION,a,b,c,d,e,f,g,h", encoding="utf-8"
        )
        return workspace

    def test_validation_precedes_one_approved_simulation(self) -> None:
        workspace = self.workspace()
        model = SequenceModel(
            [
                '{"action":"call_tool","tool_name":"validate_idf",'
                f'"arguments":{{"idf_path":"{(workspace.input_dir / "model.idf").as_posix()}"}},'
                '"reason":"Validate first."}',
                '{"action":"call_tool","tool_name":"run_energyplus_simulation",'
                f'"arguments":{{"idf_path":"{(workspace.input_dir / "model.idf").as_posix()}",'
                f'"weather_file":"{(workspace.input_dir / "weather.epw").as_posix()}",'
                f'"output_directory":"{workspace.output_dir.as_posix()}"}},'
                '"reason":"Run approved simulation."}',
                '{"action":"final","status":"completed","summary":"Done.",'
                '"next_steps":[]}',
            ]
        )
        client = FakeClient()
        result = asyncio.run(
            EnergyPlusAgent(client, model, workspace).run(
                "run", simulation_approved=True
            )
        )
        self.assertEqual(client.calls, ["validate_idf", "run_energyplus_simulation"])
        self.assertTrue(result.simulation_completed)

    def test_simulation_without_approval_is_rejected(self) -> None:
        workspace = self.workspace()
        model = SequenceModel(
            [
                '{"action":"call_tool","tool_name":"run_energyplus_simulation",'
                f'"arguments":{{"idf_path":"{(workspace.input_dir / "model.idf").as_posix()}"}},'
                '"reason":"Try to run."}',
                '{"action":"final","status":"failed","summary":"Not approved.",'
                '"next_steps":[]}',
            ]
        )
        client = FakeClient()
        result = asyncio.run(
            EnergyPlusAgent(client, model, workspace).run(
                "run", simulation_approved=False
            )
        )
        self.assertEqual(client.calls, [])
        self.assertEqual(
            result.activities[0].rejection_category, "human_approval_required"
        )

    def test_unknown_tool_and_malformed_json_fail_closed(self) -> None:
        workspace = self.workspace()
        unknown = SequenceModel(
            [
                '{"action":"call_tool","tool_name":"execute_shell",'
                '"arguments":{},"reason":"No."}',
                '{"action":"final","status":"failed","summary":"Rejected.",'
                '"next_steps":[]}',
            ]
        )
        client = FakeClient()
        result = asyncio.run(EnergyPlusAgent(client, unknown, workspace).run("x"))
        self.assertFalse(result.activities[0].accepted)
        malformed = asyncio.run(
            EnergyPlusAgent(
                FakeClient(), SequenceModel(["not json"]), workspace
            ).run("x")
        )
        self.assertTrue(malformed.fallback_used)
        self.assertEqual(malformed.status, "failed")

    def test_maximum_steps_stops_repeated_rejections(self) -> None:
        workspace = self.workspace()
        model = SequenceModel(
            [
                '{"action":"call_tool","tool_name":"execute_shell",'
                '"arguments":{},"reason":"No."}'
            ]
            * 3
        )
        result = asyncio.run(
            EnergyPlusAgent(
                FakeClient(), model, workspace, maximum_steps=3
            ).run("x")
        )
        self.assertTrue(result.fallback_used)
        self.assertEqual(len(result.activities), 3)

    def test_modification_is_disabled_without_human_approval(self) -> None:
        workspace = self.workspace()
        model = SequenceModel(
            [
                '{"action":"call_tool","tool_name":"modify_run_period",'
                f'"arguments":{{"idf_path":"{(workspace.input_dir / "model.idf").as_posix()}",'
                '"field_updates":{"Begin_Month":2}},"reason":"Modify."}',
                '{"action":"final","status":"failed","summary":"Disabled.",'
                '"next_steps":[]}',
            ]
        )
        client = FakeClient()
        result = asyncio.run(EnergyPlusAgent(client, model, workspace).run("x"))
        self.assertEqual(client.calls, [])
        self.assertEqual(
            result.activities[0].rejection_category,
            "modifications_disabled",
        )

    def test_second_simulation_request_is_rejected(self) -> None:
        workspace = self.workspace()
        idf = (workspace.input_dir / "model.idf").as_posix()
        epw = (workspace.input_dir / "weather.epw").as_posix()
        output = workspace.output_dir.as_posix()
        model = SequenceModel(
            [
                '{"action":"call_tool","tool_name":"validate_idf",'
                f'"arguments":{{"idf_path":"{idf}"}},"reason":"Validate."}}',
                '{"action":"call_tool","tool_name":"run_energyplus_simulation",'
                f'"arguments":{{"idf_path":"{idf}","weather_file":"{epw}",'
                f'"output_directory":"{output}"}},"reason":"Run."}}',
                '{"action":"call_tool","tool_name":"run_energyplus_simulation",'
                f'"arguments":{{"idf_path":"{idf}","weather_file":"{epw}",'
                f'"output_directory":"{output}"}},"reason":"Run again."}}',
                '{"action":"final","status":"completed","summary":"One run.",'
                '"next_steps":[]}',
            ]
        )
        client = FakeClient()
        result = asyncio.run(
            EnergyPlusAgent(client, model, workspace).run(
                "x", simulation_approved=True
            )
        )
        self.assertEqual(
            client.calls, ["validate_idf", "run_energyplus_simulation"]
        )
        self.assertEqual(
            result.activities[2].rejection_category, "simulation_limit"
        )


if __name__ == "__main__":
    unittest.main()
