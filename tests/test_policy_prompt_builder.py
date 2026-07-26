from __future__ import annotations

import unittest

from controller.controller_state import ControllerState
from controller.policy_prompt_builder import build_policy_prompt
from controller.supervisor_policy import default_supervisor_policy
from test_support import make_state


class PolicyPromptBuilderTests(unittest.TestCase):
    def test_prompt_enforces_policy_only_role_without_answer_leakage(self) -> None:
        state = ControllerState()
        for index in range(12):
            state.append_building_state(
                make_state(
                    timestep=index + 1,
                    zone_temperature=30.0 + index * 0.1,
                    power_kw=80.0 + index,
                )
            )
        prompt = build_policy_prompt(
            make_state(timestep=13, zone_temperature=32.0, power_kw=95.0),
            state,
            {
                "physical_actuator_changes": 3,
                "physical_safety_corrections": 1,
                "supervisory_fallbacks": 2,
            },
            default_supervisor_policy(),
        )

        self.assertIn("do not control an actuator", prompt)
        self.assertIn("A lower node setpoint means stronger cooling", prompt)
        self.assertIn("Recent zone minimum", prompt)
        self.assertIn("Facility power trend", prompt)
        self.assertIn("Physical actuator changes: 3", prompt)
        self.assertIn("Current Validated Policy", prompt)
        self.assertIn("Occupancy: Unavailable", prompt)
        self.assertIn("PMV: Unavailable", prompt)
        self.assertIn("Never return supply_air_temperature_setpoint", prompt)
        self.assertNotIn('{"thermal_priority"', prompt)


if __name__ == "__main__":
    unittest.main()
