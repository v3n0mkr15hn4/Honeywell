from __future__ import annotations

import unittest

from controller.policy_prompt_builder import build_policy_prompt
from ollama_supervisory_policy_benchmark import (
    benchmark_cases,
    build_fixture,
    run_fallback_self_test,
)
from qwen3_1_7b_supervisor_precheck import PRECHECK_CASE_IDS, audit_prompt


class OllamaSupervisoryPolicyBenchmarkTests(unittest.TestCase):
    def test_fixture_corpus_is_fixed_and_complete(self) -> None:
        cases = benchmark_cases()

        self.assertEqual(len(cases), 10)
        self.assertEqual(len({case.case_id for case in cases}), 10)
        self.assertTrue(set(PRECHECK_CASE_IDS) <= {case.case_id for case in cases})

    def test_every_fixture_builds_policy_only_prompt(self) -> None:
        for case in benchmark_cases():
            with self.subTest(case=case.case_id):
                state, controller_state, metrics = build_fixture(case)
                prompt = build_policy_prompt(
                    state,
                    controller_state,
                    metrics,
                    case.current_policy,
                )
                self.assertIn("bounded high-level policy only", prompt)
                self.assertIn("Return JSON only", prompt)
                self.assertNotIn('{"thermal_priority"', prompt)

    def test_prompt_audit_rejects_completed_answer_leakage(self) -> None:
        audit = audit_prompt()

        self.assertTrue(audit["passed"])
        self.assertFalse(audit["completed_policy_example_present"])

    def test_previous_and_default_fallbacks_are_exercised(self) -> None:
        result = run_fallback_self_test()

        self.assertTrue(result["previous_policy_fallback_success"])
        self.assertTrue(result["default_policy_fallback_success"])


if __name__ == "__main__":
    unittest.main()
