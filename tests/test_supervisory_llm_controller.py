from __future__ import annotations

import unittest

from controller.controller_state import ControllerState
from controller.policy_validator import PolicyValidator
from controller.supervisory_llm_controller import SupervisoryLLMController
from controller.supervisor_policy import (
    ControllerAggressiveness,
    Priority,
    SupervisorPolicy,
    default_supervisor_policy,
)
from llm.supervisor_mock_client import (
    MockSupervisorLLMClient,
    SupervisorMockMode,
)
from test_support import make_state


def custom_policy() -> SupervisorPolicy:
    return SupervisorPolicy(
        thermal_priority=Priority.MEDIUM,
        energy_priority=Priority.HIGH,
        controller_aggressiveness=ControllerAggressiveness.CONSERVATIVE,
        target_zone_temperature_c=33.0,
        minimum_action_hold_intervals=4,
        policy_duration_hours=4,
        strategy="previous_valid",
        reason="Previously validated policy.",
    )


class SupervisoryLLMControllerTests(unittest.TestCase):
    def build(
        self,
        mode: SupervisorMockMode,
    ) -> tuple[SupervisoryLLMController, MockSupervisorLLMClient]:
        client = MockSupervisorLLMClient(mode)
        return (
            SupervisoryLLMController(
                client,
                PolicyValidator(),
                policy_grace_period_hours=2,
            ),
            client,
        )

    def test_valid_and_unsafe_responses_are_validated(self) -> None:
        controller, _ = self.build(SupervisorMockMode.VALID_THERMAL_PRIORITY)
        valid = controller.recommend(make_state(), ControllerState(), {})
        self.assertFalse(valid.fallback_used)
        self.assertEqual(valid.policy.strategy, "thermal_recovery")

        controller, _ = self.build(SupervisorMockMode.UNSAFE_NUMERIC_VALUES)
        unsafe = controller.recommend(make_state(), ControllerState(), {})
        self.assertFalse(unsafe.fallback_used)
        self.assertTrue(unsafe.validation.corrected)
        self.assertLessEqual(unsafe.policy.target_zone_temperature_c, 34.0)

    def test_parser_failure_and_timeout_reuse_previous_policy(self) -> None:
        for mode in (
            SupervisorMockMode.MALFORMED_JSON,
            SupervisorMockMode.TIMEOUT,
            SupervisorMockMode.DIRECT_ACTUATOR_FIELD_ATTEMPT,
        ):
            with self.subTest(mode=mode):
                controller, _ = self.build(mode)
                state = ControllerState(
                    current_supervisor_policy=custom_policy(),
                    supervisor_policy_age_hours=5.0,
                )
                result = controller.recommend(make_state(), state, {})
                self.assertTrue(result.fallback_used)
                self.assertEqual(result.policy, custom_policy())
                self.assertFalse(result.used_default_policy)
                self.assertEqual(result.timeout, mode == SupervisorMockMode.TIMEOUT)

    def test_expired_policy_beyond_grace_uses_default(self) -> None:
        controller, _ = self.build(SupervisorMockMode.EXCEPTION)
        state = ControllerState(
            current_supervisor_policy=custom_policy(),
            supervisor_policy_age_hours=7.0,
        )
        result = controller.recommend(make_state(), state, {})
        self.assertTrue(result.fallback_used)
        self.assertTrue(result.used_default_policy)
        self.assertEqual(result.policy, default_supervisor_policy())

    def test_in_flight_request_uses_policy_fallback_without_second_call(
        self,
    ) -> None:
        controller, client = self.build(SupervisorMockMode.VALID_BALANCED)
        controller.request_in_flight = True
        result = controller.recommend(make_state(), ControllerState(), {})
        self.assertTrue(result.fallback_used)
        self.assertEqual(client.request_count, 0)


if __name__ == "__main__":
    unittest.main()
