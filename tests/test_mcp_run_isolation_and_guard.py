from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.mcp.tool_guard import MCPToolGuard
from src.simulation_upload.package_validator import (
    SimulationPackageValidator,
    UploadedFile,
)
from src.simulation_upload.workspace import RunWorkspaceManager


SCHEMAS = {
    "validate_idf": {
        "name": "validate_idf",
        "input_schema": {
            "type": "object",
            "properties": {"idf_path": {"type": "string"}},
            "required": ["idf_path"],
        },
    },
    "run_energyplus_simulation": {
        "name": "run_energyplus_simulation",
        "input_schema": {
            "type": "object",
            "properties": {
                "idf_path": {"type": "string"},
                "weather_file": {"type": "string"},
                "output_directory": {"type": "string"},
            },
            "required": ["idf_path"],
        },
    },
}


class IsolationAndGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.manager = RunWorkspaceManager(self.temp.name)
        self.one = self.manager.create()
        self.two = self.manager.create()
        (self.one.input_dir / "model.idf").write_text(
            "Version,26.1;", encoding="utf-8"
        )

    def test_run_directories_are_unique(self) -> None:
        self.assertNotEqual(self.one.run_id, self.two.run_id)
        self.assertNotEqual(self.one.root, self.two.root)

    def test_workspace_rejects_escape(self) -> None:
        with self.assertRaises(ValueError):
            self.one.resolve_inside(self.two.input_dir / "other.idf")
        with self.assertRaises(ValueError):
            self.one.resolve_inside("../escape.idf")

    def test_guard_accepts_current_run_and_normalizes_path(self) -> None:
        guard = MCPToolGuard(self.one.root, SCHEMAS)
        result = guard.authorize(
            "validate_idf", {"idf_path": "input/model.idf"}
        )
        self.assertTrue(result.accepted)
        self.assertTrue(Path(result.arguments["idf_path"]).is_absolute())

    def test_guard_rejects_cross_run_url_shell_and_unknown_argument(self) -> None:
        guard = MCPToolGuard(self.one.root, SCHEMAS)
        cases = [
            {"idf_path": str(self.two.input_dir / "other.idf")},
            {"idf_path": "https://example.com/model.idf"},
            {"idf_path": "input/model.idf; whoami"},
            {"idf_path": "input/model.idf", "command": "whoami"},
        ]
        for arguments in cases:
            with self.subTest(arguments=arguments):
                self.assertFalse(
                    guard.authorize("validate_idf", arguments).accepted
                )

    def test_guard_refuses_non_allowlisted_tool(self) -> None:
        guard = MCPToolGuard(self.one.root, SCHEMAS)
        result = guard.authorize("execute_shell", {})
        self.assertFalse(result.accepted)
        self.assertEqual(result.rejection_category, "tool_not_allowlisted")

    def test_guard_maps_only_current_run_to_container_workspace(self) -> None:
        server_root = f"/workspace/simulation_workspace/runs/{self.one.run_id}"
        guard = MCPToolGuard(
            self.one.root, SCHEMAS, server_run_root=server_root
        )
        accepted = guard.authorize(
            "validate_idf",
            {"idf_path": f"{server_root}/input/model.idf"},
        )
        rejected = guard.authorize(
            "validate_idf",
            {
                "idf_path": (
                    "/workspace/simulation_workspace/runs/"
                    f"{self.two.run_id}/input/other.idf"
                )
            },
        )
        self.assertTrue(accepted.accepted)
        self.assertEqual(
            accepted.arguments["idf_path"],
            f"{server_root}/input/model.idf",
        )
        self.assertFalse(rejected.accepted)


if __name__ == "__main__":
    unittest.main()
