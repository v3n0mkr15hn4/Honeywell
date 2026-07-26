from __future__ import annotations

import unittest

from ollama_model_benchmark import (
    benchmark_cases,
    build_fixture,
    summarize,
)
from controller.prompt_builder import build_prompt


class OllamaBenchmarkTests(unittest.TestCase):
    def test_fixture_corpus_is_fixed_and_complete(self) -> None:
        cases = benchmark_cases()

        self.assertEqual(len(cases), 20)
        self.assertEqual(len({case.case_id for case in cases}), 20)
        self.assertTrue(
            all(
                set(case.expected_directions)
                <= {"lower", "higher", "hold"}
                for case in cases
            )
        )

    def test_every_fixture_builds_the_shared_prompt(self) -> None:
        for case in benchmark_cases():
            with self.subTest(case=case.case_id):
                state, controller_state = build_fixture(case)
                prompt = build_prompt(state, controller_state)
                self.assertIn(
                    "MAIN COOLING COIL 1 OUTLET NODE",
                    prompt,
                )
                self.assertIn(
                    "supply_air_temperature_setpoint",
                    prompt,
                )

    def test_summary_rejects_directionally_wrong_model(self) -> None:
        requests = [
            {
                "strict_json_parse_success": True,
                "response_latency_s": 1.0,
                "parsed_requested_setpoint_c": 25.0,
                "previous_setpoint_c": 24.0,
                "timeout": False,
                "transport_failure": False,
                "fallback_used": False,
                "fallback_success": False,
                "safety_corrected": False,
                "direction_correct": False,
                "actual_physical_direction": "higher",
                "expected_physical_directions": ["lower"],
                "reason": "same",
                "final_inside_safe_range": True,
                "final_change_limited": True,
            }
            for _ in range(20)
        ]

        result = summarize("bad-model", requests, 15.0)

        self.assertEqual(result["physical_direction_accuracy"], 0.0)
        self.assertFalse(result["eligible_for_energyplus_smoke_test"])


if __name__ == "__main__":
    unittest.main()
