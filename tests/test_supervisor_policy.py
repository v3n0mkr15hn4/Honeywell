from __future__ import annotations

import dataclasses
import unittest

from controller.supervisor_policy import (
    ControllerAggressiveness,
    Priority,
    default_supervisor_policy,
)


class SupervisorPolicyTests(unittest.TestCase):
    def test_default_policy_is_valid_immutable_and_actuator_free(self) -> None:
        policy = default_supervisor_policy()

        self.assertEqual(policy.thermal_priority, Priority.HIGH)
        self.assertEqual(
            policy.controller_aggressiveness,
            ControllerAggressiveness.NORMAL,
        )
        self.assertFalse(
            {
                "supply_air_temperature_setpoint",
                "cooling_setpoint",
                "heating_setpoint",
                "actuator_key",
            }
            & {field.name for field in dataclasses.fields(policy)}
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            policy.target_zone_temperature_c = 30.0  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
