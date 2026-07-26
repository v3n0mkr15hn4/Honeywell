from __future__ import annotations

import unittest

from controller.pipeline import ControlPipeline
from controller.policy_aware_rule_controller import PolicyAwareRuleController
from controller.policy_validator import PolicyValidator
from controller.safety import SafetyValidator
from controller.supervisory_llm_controller import SupervisoryLLMController
from llm.supervisor_mock_client import (
    MockSupervisorLLMClient,
    SupervisorMockMode,
)
from test_pipeline import FakeActuatorWriter, FakeLogger, FakeSensorReader
from test_support import make_state


class HybridPipelineTests(unittest.TestCase):
    def build(
        self,
        mode: SupervisorMockMode,
        count: int,
        timestep_hours: float = 1.0,
    ):
        client = MockSupervisorLLMClient(mode)
        logger = FakeLogger()
        pipeline = ControlPipeline(
            sensor_reader=FakeSensorReader(
                [
                    make_state(
                        timestep=index + 1,
                        timestep_duration_hours=timestep_hours,
                    )
                    for index in range(count)
                ]
            ),
            actuator_writer=FakeActuatorWriter(),
            controller=PolicyAwareRuleController(),
            safety_validator=SafetyValidator(),
            logger=logger,
            supervisor=SupervisoryLLMController(
                client,
                PolicyValidator(),
            ),
            supervisor_interval_hours=4.0,
        )
        return pipeline, client, logger

    def test_rule_runs_every_interval_and_supervisor_runs_every_four_hours(
        self,
    ) -> None:
        pipeline, client, logger = self.build(
            SupervisorMockMode.VALID_THERMAL_PRIORITY,
            count=8,
        )
        for _ in range(8):
            pipeline.end_zone_timestep(object())

        self.assertEqual(client.request_count, 2)
        self.assertEqual(len(logger.rows), 8)
        self.assertEqual(
            sum(bool(row["supervisor_called"]) for row in logger.rows),
            2,
        )
        self.assertTrue(
            all(row["decision_source"] == "policy_rule" for row in logger.rows)
        )
        self.assertTrue(
            all(row["action_reused"] is False for row in logger.rows)
        )
        self.assertEqual(len(pipeline.state.history), 8)

    def test_warmup_suppression_prevents_supervisor_call(self) -> None:
        client = MockSupervisorLLMClient()
        pipeline = ControlPipeline(
            sensor_reader=FakeSensorReader([None]),
            actuator_writer=FakeActuatorWriter(),
            controller=PolicyAwareRuleController(),
            safety_validator=SafetyValidator(),
            logger=FakeLogger(),
            supervisor=SupervisoryLLMController(client, PolicyValidator()),
            supervisor_interval_hours=4.0,
        )
        pipeline.end_zone_timestep(object())
        self.assertEqual(client.request_count, 0)

    def test_failures_enter_cooldown_while_physical_control_continues(
        self,
    ) -> None:
        pipeline, client, logger = self.build(
            SupervisorMockMode.MALFORMED_JSON,
            count=6,
            timestep_hours=4.0,
        )
        for _ in range(6):
            pipeline.end_zone_timestep(object())

        self.assertEqual(client.request_count, 3)
        self.assertEqual(len(logger.rows), 6)
        self.assertTrue(
            all(row["validated_action"] is not None for row in logger.rows)
        )
        self.assertEqual(pipeline.state.supervisor_cooldown_activations, 1)
        self.assertTrue(
            all(row["supervisor_fallback_used"] for row in logger.rows)
        )


if __name__ == "__main__":
    unittest.main()
