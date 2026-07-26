from __future__ import annotations

import unittest

from controller.action import ControlAction
from controller.safety import SafetyValidator


def action(value: float) -> ControlAction:
    return ControlAction(value, "test", "test")


class SafetyValidatorTests(unittest.TestCase):
    def test_value_inside_limits_passes_unchanged(self) -> None:
        result = SafetyValidator().validate(action(23.0))

        self.assertEqual(result.action.supply_air_temperature_setpoint, 23.0)
        self.assertEqual(result.status, "valid")
        self.assertFalse(result.corrected)

    def test_21_clamps_to_22(self) -> None:
        result = SafetyValidator().validate(action(21.0))

        self.assertEqual(result.action.supply_air_temperature_setpoint, 22.0)
        self.assertTrue(result.corrected)
        self.assertIn("clamped from 21.0 C to 22.0 C", result.status)

    def test_26_clamps_to_25(self) -> None:
        result = SafetyValidator().validate(action(26.0))

        self.assertEqual(result.action.supply_air_temperature_setpoint, 25.0)
        self.assertIn("clamped from 26.0 C to 25.0 C", result.status)

    def test_large_change_is_rate_limited_to_one_degree(self) -> None:
        result = SafetyValidator().validate(
            action(22.0),
            previous_action=action(25.0),
        )

        self.assertEqual(result.action.supply_air_temperature_setpoint, 24.0)
        self.assertIn("1.0 C per decision", result.status)
        self.assertIn("from 25.0 C to 24.0 C", result.status)

    def test_unsafe_numeric_value_never_throws(self) -> None:
        result = SafetyValidator().validate(action(-1000.0))
        self.assertEqual(result.action.supply_air_temperature_setpoint, 22.0)


if __name__ == "__main__":
    unittest.main()
