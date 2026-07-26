from __future__ import annotations

import json
import unittest

from controller.supervisor_output_parser import (
    SupervisorOutputParserError,
    parse_supervisor_response,
)
from controller.supervisor_policy import Priority


def valid_payload() -> dict[str, object]:
    return {
        "thermal_priority": "high",
        "energy_priority": "medium",
        "controller_aggressiveness": "normal",
        "target_zone_temperature_c": 32.0,
        "minimum_action_hold_intervals": 2,
        "policy_duration_hours": 6,
        "strategy": "balanced",
        "reason": "Zone trend supports the current policy.",
    }


class SupervisorOutputParserTests(unittest.TestCase):
    def test_valid_json_returns_policy(self) -> None:
        policy = parse_supervisor_response(json.dumps(valid_payload()))
        self.assertEqual(policy.thermal_priority, Priority.HIGH)
        self.assertEqual(policy.target_zone_temperature_c, 32.0)

    def test_missing_wrong_extra_and_direct_fields_are_rejected(self) -> None:
        variants = []
        missing = valid_payload()
        missing.pop("reason")
        variants.append(missing)
        wrong = valid_payload()
        wrong["minimum_action_hold_intervals"] = 2.0
        variants.append(wrong)
        extra = valid_payload()
        extra["unknown"] = True
        variants.append(extra)
        direct = valid_payload()
        direct["supply_air_temperature_setpoint"] = 22.0
        variants.append(direct)
        for payload in variants:
            with self.subTest(payload=payload):
                with self.assertRaises(SupervisorOutputParserError):
                    parse_supervisor_response(json.dumps(payload))

    def test_invalid_enum_nan_infinity_and_empty_text_are_rejected(self) -> None:
        invalid_enum = valid_payload()
        invalid_enum["thermal_priority"] = "urgent"
        empty = valid_payload()
        empty["strategy"] = " "
        for text in (
            json.dumps(invalid_enum),
            json.dumps(empty),
            json.dumps(valid_payload()).replace("32.0", "NaN"),
            json.dumps(valid_payload()).replace("32.0", "Infinity"),
        ):
            with self.subTest(text=text):
                with self.assertRaises(SupervisorOutputParserError):
                    parse_supervisor_response(text)

    def test_markdown_and_prose_are_rejected(self) -> None:
        text = json.dumps(valid_payload())
        for response in (f"```json\n{text}\n```", f"Policy:\n{text}"):
            with self.assertRaises(SupervisorOutputParserError):
                parse_supervisor_response(response)


if __name__ == "__main__":
    unittest.main()
