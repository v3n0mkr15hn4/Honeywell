from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from nvidia_nim_one_day_smoke_test import (
    analyze_telemetry,
    build_one_day_idf_text,
    parse_energyplus_error_counts,
)


class NvidiaNIMOneDaySmokeSupportTests(unittest.TestCase):
    def test_one_day_idf_keeps_one_run_period(self) -> None:
        source = """
SimulationControl,
    No, !- Do Zone Sizing Calculation
    No, !- Do System Sizing Calculation
    No, !- Do Plant Sizing Calculation
    Yes, !- Run Simulation for Sizing Periods
    Yes; !- Run Simulation for Weather File Run Periods

RunPeriod,
    Jan, !- Name
    1, !- Begin Month
    1, !- Begin Day of Month
    , !- Begin Year
    1, !- End Month
    31; !- End Day of Month

RunPeriod,
    Jul, !- Name
    7, !- Begin Month
    1, !- Begin Day of Month
    , !- Begin Year
    7, !- End Month
    31; !- End Day of Month
"""
        result = build_one_day_idf_text(source)
        self.assertEqual(result.casefold().count("runperiod,"), 1)
        self.assertIn("NVIDIA NIM One Day, !- Name", result)
        self.assertIn("1; !- End Day of Month", result)
        self.assertNotIn("Jul", result)
        self.assertIn("No, !- Run Simulation for Sizing Periods", result)

    def test_error_counts_use_completion_summary(self) -> None:
        text = (
            "** Warning ** detail\n"
            "EnergyPlus Completed Successfully-- 3 Warning; "
            "0 Severe Errors; Elapsed Time=00hr 00min 01.00sec"
        )
        self.assertEqual(parse_energyplus_error_counts(text), (3, 0))

    def test_telemetry_checks_bounds_rate_and_candidate_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "control.csv"
            fields = [
                "simulation_time",
                "validated_supply_air_setpoint_c",
                "applied_supply_air_setpoint_c",
                "safety_corrected",
                "candidate_ids",
                "final_selected_policy_id",
                "forced_single_candidate",
                "llm_ranker_called",
                "llm_raw_ranking",
                "llm_selected_policy_id",
                "llm_confidence",
                "llm_reason",
                "llm_request_completed",
                "llm_retry_count",
                "llm_failure_category",
                "deterministic_fallback_used",
            ]
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow(
                    {
                        "simulation_time": "1.00 h",
                        "validated_supply_air_setpoint_c": "24.0",
                        "applied_supply_air_setpoint_c": "24.0",
                        "safety_corrected": "False",
                        "candidate_ids": '["P3","P4"]',
                        "final_selected_policy_id": "P4",
                        "forced_single_candidate": "False",
                        "llm_ranker_called": "True",
                        "llm_raw_ranking": '["P4","P3"]',
                        "llm_selected_policy_id": "P4",
                        "llm_confidence": "0.8",
                        "llm_reason": "Stable and high power.",
                        "llm_request_completed": "True",
                        "llm_retry_count": "0",
                        "llm_failure_category": "",
                        "deterministic_fallback_used": "False",
                    }
                )
                writer.writerow(
                    {
                        "simulation_time": "1.17 h",
                        "validated_supply_air_setpoint_c": "23.0",
                        "applied_supply_air_setpoint_c": "24.0",
                        "safety_corrected": "False",
                        "candidate_ids": "[]",
                        "final_selected_policy_id": "",
                        "forced_single_candidate": "False",
                        "llm_ranker_called": "False",
                        "llm_raw_ranking": "[]",
                        "llm_selected_policy_id": "",
                        "llm_confidence": "",
                        "llm_reason": "",
                        "llm_request_completed": "False",
                        "llm_retry_count": "0",
                        "llm_failure_category": "",
                        "deterministic_fallback_used": "False",
                    }
                )

            result = analyze_telemetry(path)
            self.assertTrue(result["setpoints_within_limits"])
            self.assertTrue(result["maximum_change_within_limit"])
            self.assertTrue(result["all_final_policies_from_candidate_set"])
            self.assertEqual(result["llm_calls"], 1)


if __name__ == "__main__":
    unittest.main()
