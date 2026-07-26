from __future__ import annotations

import unittest

from controller.action import ControlAction
from controller.controller_state import ControllerState
from controller.policy_aware_rule_controller import PolicyAwareRuleController
from controller.safety import SafetyValidator
from controller.supervisor_policy import (
    ControllerAggressiveness,
    Priority,
    SupervisorPolicy,
)
from test_support import make_state


def policy(
    thermal: Priority,
    energy: Priority,
    aggressiveness: ControllerAggressiveness,
    target: float = 32.0,
    hold: int = 1,
) -> SupervisorPolicy:
    return SupervisorPolicy(
        thermal_priority=thermal,
        energy_priority=energy,
        controller_aggressiveness=aggressiveness,
        target_zone_temperature_c=target,
        minimum_action_hold_intervals=hold,
        policy_duration_hours=6,
        strategy="test_policy",
        reason="Test policy.",
    )


class PolicyAwareRuleControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = PolicyAwareRuleController()

    def test_thermal_and_energy_priorities_change_rule_output(self) -> None:
        state = make_state(zone_temperature=29.0)
        thermal = self.controller.decide(
            state,
            ControllerState(),
            policy(
                Priority.HIGH,
                Priority.LOW,
                ControllerAggressiveness.AGGRESSIVE,
            ),
        )
        energy = self.controller.decide(
            state,
            ControllerState(),
            policy(
                Priority.MEDIUM,
                Priority.HIGH,
                ControllerAggressiveness.CONSERVATIVE,
            ),
        )
        self.assertEqual(thermal.supply_air_temperature_setpoint, 22.0)
        self.assertGreater(
            energy.supply_air_temperature_setpoint,
            thermal.supply_air_temperature_setpoint,
        )

    def test_target_changes_deterministic_threshold(self) -> None:
        state = make_state(zone_temperature=30.0)
        lower_target = self.controller.decide(
            state,
            ControllerState(),
            policy(
                Priority.HIGH,
                Priority.MEDIUM,
                ControllerAggressiveness.NORMAL,
                target=30.0,
            ),
        )
        higher_target = self.controller.decide(
            state,
            ControllerState(),
            policy(
                Priority.HIGH,
                Priority.MEDIUM,
                ControllerAggressiveness.NORMAL,
                target=34.0,
            ),
        )
        self.assertLess(
            lower_target.supply_air_temperature_setpoint,
            higher_target.supply_air_temperature_setpoint,
        )

    def test_minimum_hold_is_enforced_and_final_safety_remains_authoritative(
        self,
    ) -> None:
        state = ControllerState(
            previous_action=ControlAction(25.0, "previous", "Previous."),
            physical_action_hold_intervals_elapsed=0,
        )
        action = self.controller.decide(
            make_state(zone_temperature=29.0),
            state,
            policy(
                Priority.HIGH,
                Priority.LOW,
                ControllerAggressiveness.AGGRESSIVE,
                hold=2,
            ),
        )
        self.assertEqual(action.supply_air_temperature_setpoint, 25.0)
        validated = SafetyValidator().validate(action, state.previous_action)
        self.assertGreaterEqual(
            validated.action.supply_air_temperature_setpoint,
            22.0,
        )
        self.assertLessEqual(
            validated.action.supply_air_temperature_setpoint,
            25.0,
        )


if __name__ == "__main__":
    unittest.main()
