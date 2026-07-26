from __future__ import annotations

import unittest

from candidate_test_support import make_summary
from controller.candidate_policy_generator import CandidatePolicyGenerator
from controller.candidate_ranking_parser import ParsedCandidateRanking
from controller.candidate_selection_validator import (
    CandidateSelectionValidator,
)


class CandidateSelectionValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        summary = make_summary(high_power=True)
        self.candidate_set = CandidatePolicyGenerator().generate(
            summary,
            summary.current_policy,
        )
        self.validator = CandidateSelectionValidator()
        self.ids = tuple(
            item.candidate_id for item in self.candidate_set.candidates
        )

    def parsed(
        self,
        ranking: tuple[str, ...] | None = None,
        selected: str | None = None,
        confidence: float = 0.90,
        reason: str = "Stable thermal state permits an energy trade-off.",
    ) -> ParsedCandidateRanking:
        ranking = ranking or self.candidate_set.deterministic_ranking
        return ParsedCandidateRanking(
            ranking=ranking,
            selected_policy_id=selected or ranking[0],
            confidence=confidence,
            reason=reason,
        )

    def test_valid_high_and_medium_confidence_selection(self) -> None:
        alternative = (self.ids[-1],) + self.ids[:-1]
        high = self.validator.validate(
            self.parsed(alternative, confidence=0.90),
            self.candidate_set,
        )
        self.assertTrue(high.accepted_llm_selection)

        top_two = self.candidate_set.deterministic_ranking
        medium_ranking = (top_two[1], top_two[0]) + top_two[2:]
        medium = self.validator.validate(
            self.parsed(medium_ranking, confidence=0.60),
            self.candidate_set,
        )
        self.assertTrue(medium.accepted_llm_selection)

    def test_medium_lower_rank_and_low_confidence_fall_back(self) -> None:
        deterministic = self.candidate_set.deterministic_recommendation_id
        lower = (
            self.candidate_set.deterministic_ranking[-1],
        ) + self.candidate_set.deterministic_ranking[:-1]
        medium = self.validator.validate(
            self.parsed(lower, confidence=0.60),
            self.candidate_set,
        )
        low = self.validator.validate(
            self.parsed(confidence=0.20),
            self.candidate_set,
        )
        self.assertEqual(medium.selected_candidate.candidate_id, deterministic)
        self.assertTrue(medium.fallback_used)
        self.assertTrue(low.low_confidence_fallback)

    def test_invalid_rankings_and_unavailable_claim_fall_back(self) -> None:
        invalid = [
            self.parsed(self.ids[:-1]),
            self.parsed(self.ids[:-1] + ("P99",)),
            self.parsed((self.ids[0], self.ids[0]) + self.ids[2:]),
            self.parsed(self.ids, selected=self.ids[-1]),
            self.parsed(reason="Occupied users have acceptable PMV."),
        ]
        for parsed in invalid:
            with self.subTest(parsed=parsed):
                result = self.validator.validate(parsed, self.candidate_set)
                self.assertTrue(result.fallback_used)
                self.assertIn(
                    result.selected_candidate.candidate_id,
                    self.ids,
                )


if __name__ == "__main__":
    unittest.main()
