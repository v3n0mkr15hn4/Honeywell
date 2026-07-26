from __future__ import annotations

import json
import unittest

from controller.candidate_ranking_parser import (
    CandidateRankingParserError,
    parse_candidate_ranking,
)


def response(**overrides: object) -> str:
    values: dict[str, object] = {
        "ranking": ["P2", "P1", "P3"],
        "selected_policy_id": "P2",
        "confidence": 0.82,
        "reason": "Rising thermal state favors balanced recovery.",
    }
    values.update(overrides)
    return json.dumps(values)


class CandidateRankingParserTests(unittest.TestCase):
    def test_valid_response(self) -> None:
        parsed = parse_candidate_ranking(response())
        self.assertEqual(parsed.ranking, ("P2", "P1", "P3"))
        self.assertEqual(parsed.selected_policy_id, "P2")

    def test_malformed_markdown_missing_and_extra_are_rejected(self) -> None:
        invalid = [
            "not json",
            "```json\n" + response() + "\n```",
            json.dumps(
                {
                    "ranking": ["P1"],
                    "selected_policy_id": "P1",
                    "confidence": 0.8,
                }
            ),
            response(extra="field"),
            response(supply_air_temperature_setpoint=22.0),
            response(target_zone_temperature_c=31.0),
        ]
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(CandidateRankingParserError):
                    parse_candidate_ranking(value)

    def test_invalid_ranking_duplicates_confidence_and_reason_rejected(
        self,
    ) -> None:
        invalid = [
            response(ranking="P1"),
            response(ranking=["P1", "P1"], selected_policy_id="P1"),
            response(confidence="high"),
            response(confidence=-0.1),
            response(confidence=1.1),
            response(reason=""),
            response(selected_policy_id=""),
        ]
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(CandidateRankingParserError):
                    parse_candidate_ranking(value)

    def test_nan_and_infinity_are_rejected(self) -> None:
        for constant in ("NaN", "Infinity", "-Infinity"):
            text = response().replace("0.82", constant)
            with self.subTest(constant=constant):
                with self.assertRaises(CandidateRankingParserError):
                    parse_candidate_ranking(text)


if __name__ == "__main__":
    unittest.main()
