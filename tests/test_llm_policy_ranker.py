from __future__ import annotations

import unittest

from candidate_test_support import ranker_controller_state
from controller.controller_state import ControllerState
from controller.llm_policy_ranker import LLMPolicyRanker
from controller.policy_validator import PolicyValidator
from llm.candidate_ranker_mock_client import (
    CandidateRankerMockMode,
    MockCandidateRankerLLMClient,
)
from test_support import make_state


class LLMPolicyRankerTests(unittest.TestCase):
    def build(
        self,
        mode: CandidateRankerMockMode,
    ) -> tuple[LLMPolicyRanker, MockCandidateRankerLLMClient]:
        client = MockCandidateRankerLLMClient(mode)
        return LLMPolicyRanker(client, PolicyValidator()), client

    def test_valid_and_alternative_rankings_select_candidate_policy(self) -> None:
        for mode in (
            CandidateRankerMockMode.VALID_TOP_DETERMINISTIC,
            CandidateRankerMockMode.VALID_ALTERNATIVE_HIGH_CONFIDENCE,
            CandidateRankerMockMode.VALID_MEDIUM_CONFIDENCE_TOP_TWO,
        ):
            with self.subTest(mode=mode):
                ranker, client = self.build(mode)
                result = ranker.recommend(
                    make_state(
                        zone_temperature=32.0,
                        power_kw=125.0,
                        hvac_power_kw=23.0,
                    ),
                    ranker_controller_state(),
                    {},
                )
                self.assertEqual(client.request_count, 1)
                self.assertFalse(result.fallback_used)
                self.assertIn(
                    result.selected_candidate,
                    result.candidate_set.candidates,
                )
                self.assertFalse(result.validation.corrected)

    def test_every_failure_uses_current_deterministic_recommendation(self) -> None:
        for mode in (
            CandidateRankerMockMode.LOW_CONFIDENCE,
            CandidateRankerMockMode.UNKNOWN_CANDIDATE,
            CandidateRankerMockMode.DUPLICATE_RANKING,
            CandidateRankerMockMode.INCOMPLETE_RANKING,
            CandidateRankerMockMode.SELECTED_NOT_FIRST,
            CandidateRankerMockMode.EXTRA_ACTUATOR_FIELD,
            CandidateRankerMockMode.EXTRA_POLICY_VALUES,
            CandidateRankerMockMode.MALFORMED_JSON,
            CandidateRankerMockMode.TIMEOUT,
            CandidateRankerMockMode.EXCEPTION,
        ):
            with self.subTest(mode=mode):
                ranker, _ = self.build(mode)
                result = ranker.recommend(
                    make_state(
                        zone_temperature=32.0,
                        power_kw=125.0,
                        hvac_power_kw=23.0,
                    ),
                    ranker_controller_state(),
                    {},
                )
                self.assertTrue(result.fallback_used)
                self.assertEqual(
                    result.selected_candidate.candidate_id,
                    result.candidate_set.deterministic_recommendation_id,
                )
                self.assertIn(
                    result.selected_candidate,
                    result.candidate_set.candidates,
                )

    def test_forced_single_candidate_skips_llm(self) -> None:
        ranker, client = self.build(
            CandidateRankerMockMode.VALID_TOP_DETERMINISTIC
        )
        state = ControllerState()
        state.append_building_state(
            make_state(
                zone_temperature=30.0,
                timestep_duration_hours=1.0,
            )
        )
        state.append_building_state(
            make_state(
                zone_temperature=31.0,
                timestep_duration_hours=1.0,
            )
        )
        result = ranker.recommend(
            make_state(zone_temperature=35.0),
            state,
            {},
        )
        self.assertTrue(result.forced_single_candidate)
        self.assertFalse(result.llm_called)
        self.assertEqual(client.request_count, 0)
        self.assertEqual(result.selected_candidate.candidate_id, "P1")

    def test_ranker_has_no_physical_action_authority(self) -> None:
        ranker, _ = self.build(CandidateRankerMockMode.LOW_CONFIDENCE)
        result = ranker.recommend(
            make_state(zone_temperature=32.0, power_kw=125.0),
            ranker_controller_state(),
            {},
        )
        self.assertFalse(hasattr(result, "action"))
        self.assertFalse(
            hasattr(result.policy, "supply_air_temperature_setpoint")
        )


if __name__ == "__main__":
    unittest.main()
