from __future__ import annotations

import unittest

from controller.action import ControlAction
from controller.controller_state import ControllerState
from controller.prompt_builder import build_prompt
from test_support import make_state


class PromptBuilderTests(unittest.TestCase):
    def test_prompt_has_exact_physical_semantics_schema_and_trends(self) -> None:
        controller_state = ControllerState(
            previous_action=ControlAction(24.0, "previous", "Previous reason."),
            timestep=6,
            last_strategy="previous",
            previous_validation_status="valid",
        )
        for index in range(6):
            controller_state.append_building_state(
                make_state(
                    timestep=index + 1,
                    zone_temperature=28.0 + index * 0.2,
                    power_kw=70.0 + index,
                )
            )

        prompt = build_prompt(
            make_state(timestep=7, zone_temperature=30.0, power_kw=80.0),
            controller_state,
        )

        self.assertIn("MAIN COOLING COIL 1 OUTLET NODE", prompt)
        self.assertIn("Allowed range: 22.0 C to 25.0 C", prompt)
        self.assertIn("Lower values generally provide colder supply air", prompt)
        self.assertIn("not directly setting the zone temperature", prompt)
        self.assertIn("EnergyPlus calculates", prompt)
        self.assertIn(
            "- supply_air_temperature_setpoint: a finite number",
            prompt,
        )
        self.assertIn("Do not copy a fixed default response", prompt)
        self.assertIn(
            "Hold the previous setpoint when no meaningful change is justified.",
            prompt,
        )
        self.assertIn(
            "If the setpoint is lower than the previous setpoint",
            prompt,
        )
        self.assertIn(
            "If the setpoint is higher than the previous setpoint",
            prompt,
        )
        self.assertIn(
            "If the setpoint is unchanged, justify holding it.",
            prompt,
        )
        self.assertIn(
            "Occupancy and PMV may be unavailable; do not invent them.",
            prompt,
        )
        self.assertNotIn(
            '{"supply_air_temperature_setpoint": 23.0',
            prompt,
        )
        self.assertNotIn('"strategy": "moderate_cooling"', prompt)
        self.assertNotIn('"reason": "Short physical explanation."', prompt)
        self.assertIn("Occupancy: Unavailable", prompt)
        self.assertIn("PMV: Unavailable", prompt)
        self.assertNotIn('"cooling_setpoint":', prompt)
        self.assertIn("Previous supply-air temperature setpoint: 24.0 C", prompt)
        self.assertIn("Previous reason: Previous reason.", prompt)
        self.assertIn("Zone temperature change over approximately one hour:", prompt)
        self.assertIn("Facility power change over approximately one hour:", prompt)

    def test_prompt_marks_unavailable_trends(self) -> None:
        prompt = build_prompt(make_state(), ControllerState())
        self.assertIn("Previous zone temperature: Unavailable", prompt)
        self.assertIn(
            "Zone temperature change over approximately one hour: Unavailable",
            prompt,
        )


if __name__ == "__main__":
    unittest.main()
