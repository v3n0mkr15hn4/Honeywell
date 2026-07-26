from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "dashboard" / "app.py"


class DashboardAppTests(unittest.TestCase):
    def test_empty_telemetry_state_renders(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DASHBOARD_DEMO_MODE": "false",
                "ENERGYPLUS_TELEMETRY_CSV": str(
                    ROOT / "does-not-exist.csv"
                ),
            },
            clear=False,
        ):
            app = AppTest.from_file(str(APP)).run(timeout=20)
        self.assertFalse(app.exception)
        self.assertTrue(
            any("Waiting for telemetry" in item.value for item in app.info)
        )

    def test_valid_demo_telemetry_state_renders(self) -> None:
        with patch.dict(
            os.environ,
            {"DASHBOARD_DEMO_MODE": "true"},
            clear=False,
        ):
            app = AppTest.from_file(str(APP)).run(timeout=20)
        self.assertFalse(app.exception)
        self.assertTrue(
            any(
                item.value == "EnergyPlus Supervisory Control"
                for item in app.title
            )
        )
        self.assertGreater(len(app.metric), 10)
        self.assertGreater(len(app.dataframe), 1)


if __name__ == "__main__":
    unittest.main()
