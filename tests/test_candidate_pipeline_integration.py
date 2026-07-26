from __future__ import annotations

import unittest

from candidate_test_support import energy_policy
from controller.llm_policy_ranker import LLMPolicyRanker
from controller.pipeline import ControlPipeline
from controller.policy_aware_rule_controller import PolicyAwareRuleController
from controller.policy_validator import PolicyValidator
from controller.safety import SafetyValidator
from llm.candidate_ranker_mock_client import (
    CandidateRankerMockMode,
    MockCandidateRankerLLMClient,
)
from test_pipeline import FakeActuatorWriter, FakeLogger, FakeSensorReader
from test_support import make_state


class CandidatePipelineIntegrationTests(unittest.TestCase):
    def build(
        self,
        mode: CandidateRankerMockMode,
        temperatures: tuple[float, float, float],
        powers: tuple[float, float, float] = (80.0, 85.0, 90.0),
    ):
        client = MockCandidateRankerLLMClient(mode)
        logger = FakeLogger()
        pipeline = ControlPipeline(
            sensor_reader=FakeSensorReader(
                [
                    make_state(
                        timestep=index + 1,
                        zone_temperature=temperature,
                        power_kw=powers[index],
                        timestep_duration_hours=1.0,
                    )
                    for index, temperature in enumerate(temperatures)
                ]
            ),
            actuator_writer=FakeActuatorWriter(),
            controller=PolicyAwareRuleController(),
            safety_validator=SafetyValidator(),
            logger=logger,
            supervisor=LLMPolicyRanker(client, PolicyValidator()),
            supervisor_interval_hours=3.0,
        )
        return pipeline, client, logger

    def test_forced_candidate_skips_llm_and_rule_retains_authority(self) -> None:
        pipeline, client, logger = self.build(
            CandidateRankerMockMode.VALID_TOP_DETERMINISTIC,
            (30.0, 31.0, 35.0),
        )
        for _ in range(3):
            pipeline.end_zone_timestep(object())

        self.assertEqual(client.request_count, 0)
        row = logger.rows[-1]
        metadata = row["candidate_metadata"]
        self.assertTrue(metadata["forced_single_candidate"])
        self.assertFalse(row["supervisor_called"])
        self.assertEqual(metadata["final_selected_policy_id"], "P1")
        self.assertEqual(
            row["controller_type"],
            "PolicyAwareRuleController",
        )
        self.assertLessEqual(
            row["validated_action"].supply_air_temperature_setpoint,
            25.0,
        )

    def test_stale_energy_policy_cannot_survive_invalid_ranking(self) -> None:
        pipeline, client, logger = self.build(
            CandidateRankerMockMode.MALFORMED_JSON,
            (31.0, 32.0, 34.0),
            (100.0, 110.0, 120.0),
        )
        pipeline.state.current_supervisor_policy = energy_policy()
        for _ in range(3):
            pipeline.end_zone_timestep(object())

        self.assertEqual(client.request_count, 1)
        self.assertTrue(logger.rows[-1]["supervisor_fallback_used"])
        metadata = logger.rows[-1]["candidate_metadata"]
        self.assertEqual(metadata["candidate_ids"], ["P1", "P2"])
        self.assertEqual(metadata["final_selected_policy_id"], "P1")
        self.assertNotEqual(
            pipeline.state.current_supervisor_policy.strategy,
            "energy_saving",
        )
        self.assertEqual(
            pipeline.state.current_supervisor_policy.strategy,
            "thermal_recovery_aggressive",
        )


if __name__ == "__main__":
    unittest.main()
