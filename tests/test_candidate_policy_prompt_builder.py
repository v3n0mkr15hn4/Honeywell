from __future__ import annotations

import unittest

from candidate_test_support import make_summary
from controller.candidate_policy_generator import CandidatePolicyGenerator
from controller.candidate_policy_prompt_builder import (
    build_candidate_policy_prompt,
)


class CandidatePolicyPromptBuilderTests(unittest.TestCase):
    def test_prompt_contains_processed_facts_and_every_candidate(self) -> None:
        summary = make_summary(high_power=True)
        candidate_set = CandidatePolicyGenerator().generate(
            summary,
            summary.current_policy,
        )
        prompt = build_candidate_policy_prompt(summary, candidate_set)

        for fact in (
            "thermal_state: near_target",
            "zone_trend: stable",
            "power_trend: stable",
            "outdoor_trend: stable",
            "occupancy_available: false",
            "pmv_available: false",
        ):
            self.assertIn(fact, prompt)
        for candidate in candidate_set.candidates:
            self.assertIn(f"- {candidate.candidate_id}:", prompt)
        self.assertIn(
            candidate_set.deterministic_recommendation_id,
            prompt,
        )
        self.assertNotIn('{"ranking"', prompt)
        self.assertNotIn("30.0, 31.0, 32.0", prompt)
        self.assertIn("Do not return physical actuator values", prompt)


if __name__ == "__main__":
    unittest.main()
