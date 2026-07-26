from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]
CREATE_PAGE = ROOT / "dashboard" / "pages" / "2_Create_Simulation.py"
ACTIVITY_PAGE = ROOT / "dashboard" / "pages" / "3_Agent_Activity.py"
RESULTS_PAGE = ROOT / "dashboard" / "pages" / "4_Simulation_Results.py"
HISTORY_PAGE = ROOT / "dashboard" / "pages" / "5_Run_History.py"


class MCPDashboardPageTests(unittest.TestCase):
    def test_create_page_renders_incompatible_service_state(self) -> None:
        inventory = {
            "compatible": False,
            "health": {"healthy": False},
            "tools": [],
            "missing_required_tools": ["validate_idf"],
        }
        with patch.dict(
            os.environ,
            {
                "ENERGYPLUS_MCP_ENABLED": "false",
                "ENERGYPLUS_MCP_WORKSPACE_ROOT": str(
                    ROOT / "simulation_workspace"
                ),
            },
            clear=False,
        ), patch(
            "src.simulation_upload.service.inspect_inventory",
            return_value=inventory,
        ):
            app = AppTest.from_file(str(CREATE_PAGE)).run(timeout=20)
        self.assertFalse(app.exception)
        self.assertTrue(any(item.value == "Create Simulation" for item in app.title))
        combined = " ".join(item.value for item in app.error)
        self.assertIn("disabled", combined)

    def test_activity_and_results_pages_render_without_selected_run(self) -> None:
        for page in (ACTIVITY_PAGE, RESULTS_PAGE):
            with self.subTest(page=page.name):
                app = AppTest.from_file(str(page)).run(timeout=20)
                self.assertFalse(app.exception)
                self.assertTrue(
                    any("Select or create" in item.value for item in app.info)
                )

    def test_history_page_renders(self) -> None:
        app = AppTest.from_file(str(HISTORY_PAGE)).run(timeout=20)
        self.assertFalse(app.exception)
        self.assertTrue(any(item.value == "Run History" for item in app.title))

    def test_pages_do_not_contain_secret_rendering(self) -> None:
        combined = "\n".join(
            page.read_text(encoding="utf-8")
            for page in (CREATE_PAGE, ACTIVITY_PAGE, RESULTS_PAGE, HISTORY_PAGE)
        )
        self.assertNotIn("ENERGYPLUS_MCP_TOKEN", combined)
        self.assertNotIn("NVIDIA_NIM_API_KEY", combined)


if __name__ == "__main__":
    unittest.main()
