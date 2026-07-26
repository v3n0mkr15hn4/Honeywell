from __future__ import annotations

import unittest

from controller.output_parser import OutputParserError, parse_response


class OutputParserTests(unittest.TestCase):
    def test_new_field_parses_into_single_source_of_truth(self) -> None:
        action = parse_response(
            '{"supply_air_temperature_setpoint": 23, '
            '"strategy": "moderate", "reason": "Zone is stable."}'
        )

        self.assertEqual(action.supply_air_temperature_setpoint, 23)
        self.assertEqual(action.cooling_setpoint, 23)
        self.assertEqual(action.strategy, "moderate")

    def test_old_cooling_setpoint_only_response_is_rejected(self) -> None:
        with self.assertRaises(OutputParserError):
            parse_response(
                '{"cooling_setpoint": 23, "strategy": "legacy", '
                '"reason": "Wrong field."}'
            )

    def test_missing_new_field_is_rejected(self) -> None:
        with self.assertRaises(OutputParserError):
            parse_response('{"strategy": "missing", "reason": "bad"}')

    def test_wrong_type_is_rejected(self) -> None:
        with self.assertRaises(OutputParserError):
            parse_response(
                '{"supply_air_temperature_setpoint": "cold", '
                '"strategy": "wrong", "reason": "bad"}'
            )

    def test_empty_strategy_and_reason_are_rejected(self) -> None:
        with self.assertRaises(OutputParserError):
            parse_response(
                '{"supply_air_temperature_setpoint": 23, '
                '"strategy": "", "reason": "bad"}'
            )
        with self.assertRaises(OutputParserError):
            parse_response(
                '{"supply_air_temperature_setpoint": 23, '
                '"strategy": "ok", "reason": " "}'
            )

    def test_prose_and_malformed_json_are_rejected(self) -> None:
        with self.assertRaises(OutputParserError):
            parse_response("supply air should be 23")
        with self.assertRaises(OutputParserError):
            parse_response(
                'Here is JSON: {"supply_air_temperature_setpoint": 23, '
                '"strategy": "x", "reason": "y"}'
            )

    def test_nan_and_infinity_are_rejected(self) -> None:
        for value in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(value=value):
                with self.assertRaises(OutputParserError):
                    parse_response(
                        '{"supply_air_temperature_setpoint": '
                        f"{value}, "
                        '"strategy": "invalid", "reason": "non-finite"}'
                    )


if __name__ == "__main__":
    unittest.main()
