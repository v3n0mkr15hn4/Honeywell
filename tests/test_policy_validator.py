from __future__ import annotations

import math
import unittest

from controller.policy_validator import PolicyValidator
from controller.supervisor_policy import (
    ControllerAggressiveness,
    Priority,
    SupervisorPolicy,
    default_supervisor_policy,
)


def policy(**overrides: object) -> SupervisorPolicy:
    values: dict[str, object] = {
        "thermal_priority": Priority.HIGH,
        "energy_priority": Priority.MEDIUM,
        "controller_aggressiveness": ControllerAggressiveness.NORMAL,
        "target_zone_temperature_c": 32.0,
        "minimum_action_hold_intervals": 2,
        "policy_duration_hours": 6,
        "strategy": "test",
        "reason": "Deterministic test policy.",
    }
    values.update(overrides)
    return SupervisorPolicy(**values)  # type: ignore[arg-type]


class PolicyValidatorTests(unittest.TestCase):
    def test_numeric_fields_are_clamped(self) -> None:
        result = PolicyValidator().validate(
            policy(
                target_zone_temperature_c=100.0,
                minimum_action_hold_intervals=99,
                policy_duration_hours=99,
            )
        )
        self.assertTrue(result.corrected)
        self.assertEqual(result.validated_policy.target_zone_temperature_c, 34.0)
        self.assertEqual(result.validated_policy.minimum_action_hold_intervals, 6)
        self.assertEqual(result.validated_policy.policy_duration_hours, 12)

    def test_invalid_enum_and_nonfinite_use_safe_baseline(self) -> None:
        previous = default_supervisor_policy()
        result = PolicyValidator().validate(
            policy(
                thermal_priority="urgent",
                target_zone_temperature_c=math.inf,
            ),
            previous_policy=previous,
        )
        self.assertEqual(result.validated_policy.thermal_priority, Priority.HIGH)
        self.assertEqual(result.validated_policy.target_zone_temperature_c, 32.0)
        self.assertIn("thermal_priority", result.rejected_fields)
        self.assertIn("target_zone_temperature_c", result.rejected_fields)

    def test_policy_to_policy_changes_are_bounded(self) -> None:
        previous = policy(
            target_zone_temperature_c=30.0,
            minimum_action_hold_intervals=1,
            policy_duration_hours=4,
        )
        result = PolicyValidator().validate(
            policy(
                target_zone_temperature_c=34.0,
                minimum_action_hold_intervals=6,
                policy_duration_hours=12,
            ),
            previous_policy=previous,
        )
        self.assertEqual(result.validated_policy.target_zone_temperature_c, 31.0)
        self.assertEqual(result.validated_policy.minimum_action_hold_intervals, 3)
        self.assertEqual(result.validated_policy.policy_duration_hours, 8)


if __name__ == "__main__":
    unittest.main()
