from __future__ import annotations

import unittest

import pandas as pd

from dashboard.metrics_helpers import (
    cumulative_metrics,
    operational_target_violation_rate,
    parse_candidate_summaries,
    safe_json_list,
    watts_to_kilowatts,
)


class DashboardMetricsTests(unittest.TestCase):
    def test_active_target_violation_rate_uses_each_row_target(self) -> None:
        frame = pd.DataFrame(
            {
                "indoor_temp_c": [31.0, 33.0, 32.0],
                "target_zone_temperature_c": [32.0, 32.5, 32.0],
            }
        )
        self.assertAlmostEqual(
            operational_target_violation_rate(frame) or 0.0,
            1.0 / 3.0,
        )

    def test_watts_to_kilowatts(self) -> None:
        result = watts_to_kilowatts(pd.Series([1000, "2500", "bad"]))
        self.assertEqual(result.iloc[0], 1.0)
        self.assertEqual(result.iloc[1], 2.5)
        self.assertTrue(pd.isna(result.iloc[2]))

    def test_fallback_safety_and_success_counts(self) -> None:
        frame = pd.DataFrame(
            {
                "llm_ranker_called": ["True", "True", "False"],
                "llm_request_completed": ["True", "False", "False"],
                "ranking_validation_status": [
                    "valid candidate ranking",
                    "",
                    "",
                ],
                "deterministic_fallback_used": ["False", "True", "False"],
                "safety_corrected": ["True", "False", "True"],
                "invalid_ranking_fallback": ["False", "True", "False"],
            }
        )
        result = cumulative_metrics(frame)
        self.assertEqual(result["nvidia_calls"], 2)
        self.assertEqual(result["successful_nvidia_calls"], 1)
        self.assertEqual(result["strict_ranking_successes"], 1)
        self.assertEqual(result["deterministic_fallbacks"], 1)
        self.assertEqual(result["physical_safety_corrections"], 2)

    def test_candidate_parsing_valid_malformed_and_missing(self) -> None:
        valid = (
            '[{"candidate_id":"P3","mode":"balanced"},'
            '{"candidate_id":"P4","mode":"energy_conservative"}]'
        )
        self.assertEqual(len(parse_candidate_summaries(valid)), 2)
        self.assertEqual(parse_candidate_summaries("{bad json"), [])
        self.assertEqual(parse_candidate_summaries(None), [])
        self.assertEqual(safe_json_list('["P3","P4"]'), ["P3", "P4"])


if __name__ == "__main__":
    unittest.main()
