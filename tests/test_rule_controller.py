from __future__ import annotations

import unittest

from controller.controller_state import ControllerState
from controller.rule_controller import RuleController
from controller.safety import SafetyValidator
from test_support import make_state


class RuleControllerTests(unittest.TestCase):
    def test_high_temperature_lowers_node_target(self) -> None:
        action = RuleController().decide(make_state(zone_temperature=31.0))
        self.assertEqual(action.supply_air_temperature_setpoint, 22.0)
        self.assertIn("cooling-coil outlet", action.reason)

    def test_rising_temperature_lowers_node_target(self) -> None:
        state = ControllerState()
        state.append_building_state(make_state(zone_temperature=26.0))
        action = RuleController().decide(
            make_state(zone_temperature=26.3),
            state,
        )
        self.assertEqual(action.supply_air_temperature_setpoint, 22.0)

    def test_low_thermal_demand_raises_node_target(self) -> None:
        action = RuleController().decide(make_state(zone_temperature=25.0))
        self.assertEqual(action.supply_air_temperature_setpoint, 25.0)

    def test_every_rule_output_is_safe_after_validation(self) -> None:
        validator = SafetyValidator()
        for temperature in (20.0, 27.5, 35.0):
            validated = validator.validate(
                RuleController().decide(
                    make_state(zone_temperature=temperature)
                )
            ).action
            self.assertGreaterEqual(
                validated.supply_air_temperature_setpoint,
                22.0,
            )
            self.assertLessEqual(
                validated.supply_air_temperature_setpoint,
                25.0,
            )


if __name__ == "__main__":
    unittest.main()
