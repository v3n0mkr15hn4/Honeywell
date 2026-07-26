from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from dashboard.telemetry_loader import load_telemetry


class DashboardTelemetryLoaderTests(unittest.TestCase):
    def test_missing_and_empty_files_return_empty_frame(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing.csv"
            self.assertTrue(load_telemetry(missing).empty)
            empty = Path(temp_dir) / "empty.csv"
            empty.write_text("", encoding="utf-8")
            self.assertTrue(load_telemetry(empty).empty)

    def test_incomplete_final_row_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "telemetry.csv"
            path.write_text(
                "timestep,indoor_temp_c,policy_strategy\n"
                "1,31.5,balanced\n"
                "2,32.0",
                encoding="utf-8",
            )
            frame = load_telemetry(path)
            self.assertEqual(len(frame), 1)
            self.assertEqual(frame.iloc[0]["timestep"], 1)

    def test_numeric_conversion_tolerates_malformed_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "telemetry.csv"
            path.write_text(
                "timestep,indoor_temp_c\n"
                "2,not-a-number\n"
                "bad,31.0\n"
                "1,30.0\n",
                encoding="utf-8",
            )
            frame = load_telemetry(path)
            self.assertEqual(frame.iloc[0]["timestep"], 1)
            self.assertEqual(frame.iloc[1]["timestep"], 2)
            self.assertTrue(pd.isna(frame.iloc[1]["indoor_temp_c"]))
            self.assertTrue(pd.isna(frame.iloc[2]["timestep"]))

    def test_valid_csv_is_sorted_and_simulated_hour_is_extracted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "telemetry.csv"
            path.write_text(
                "simulation_time,timestep,indoor_temp_c\n"
                "1999-01-01 2.00 h,2,32.0\n"
                "1999-01-01 1.00 h,1,31.0\n",
                encoding="utf-8",
            )
            frame = load_telemetry(path)
            self.assertEqual(frame["timestep"].tolist(), [1, 2])
            self.assertEqual(frame["simulated_hour"].tolist(), [1.0, 2.0])


if __name__ == "__main__":
    unittest.main()
