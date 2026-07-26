"""Validate model rankings against the current deterministic candidate set."""

from __future__ import annotations

import re
from dataclasses import dataclass

from controller.candidate_ranking_parser import ParsedCandidateRanking
from controller.policy_candidate import CandidatePolicySet, PolicyCandidate


@dataclass(frozen=True)
class CandidateSelectionResult:
    selected_candidate: PolicyCandidate
    accepted_llm_selection: bool
    fallback_used: bool
    validation_status: str
    confidence_gate_status: str
    low_confidence_fallback: bool = False
    invalid_ranking_fallback: bool = False


class CandidateSelectionValidator:
    """Apply membership, completeness, factual-reason, and confidence gates."""

    def validate(
        self,
        parsed: ParsedCandidateRanking,
        candidate_set: CandidatePolicySet,
    ) -> CandidateSelectionResult:
        candidate_ids = tuple(
            candidate.candidate_id for candidate in candidate_set.candidates
        )
        ranked = parsed.ranking
        invalid_reason = ""
        if len(ranked) != len(candidate_ids):
            invalid_reason = "incomplete ranking"
        elif len(set(ranked)) != len(ranked):
            invalid_reason = "duplicate candidate ID"
        elif set(ranked) != set(candidate_ids):
            invalid_reason = "unknown or missing candidate ID"
        elif parsed.selected_policy_id != ranked[0]:
            invalid_reason = "selected_policy_id is not ranking[0]"
        elif candidate_set.candidate(parsed.selected_policy_id) is None:
            invalid_reason = "selected policy does not exist"
        elif self._unsupported_unavailable_claim(parsed.reason):
            invalid_reason = "unsupported occupancy or PMV claim"
        if invalid_reason:
            return self._fallback(
                candidate_set,
                invalid_reason,
                gate="invalid_ranking",
                invalid=True,
            )

        if parsed.confidence < 0.50:
            return self._fallback(
                candidate_set,
                "confidence below 0.50",
                gate="low_confidence_rejected",
                low=True,
            )
        if parsed.confidence < 0.75:
            allowed = set(candidate_set.deterministic_ranking[:2])
            if parsed.selected_policy_id not in allowed:
                return self._fallback(
                    candidate_set,
                    "medium-confidence choice is outside deterministic top two",
                    gate="medium_confidence_rejected",
                    low=True,
                )
            gate = "medium_confidence_top_two_accepted"
        else:
            gate = "high_confidence_accepted"
        selected = candidate_set.candidate(parsed.selected_policy_id)
        if selected is None:
            raise RuntimeError("Validated selected candidate disappeared")
        return CandidateSelectionResult(
            selected_candidate=selected,
            accepted_llm_selection=True,
            fallback_used=False,
            validation_status="valid candidate ranking",
            confidence_gate_status=gate,
        )

    def _fallback(
        self,
        candidate_set: CandidatePolicySet,
        reason: str,
        gate: str,
        low: bool = False,
        invalid: bool = False,
    ) -> CandidateSelectionResult:
        selected = candidate_set.candidate(
            candidate_set.deterministic_recommendation_id
        )
        if selected is None:
            raise RuntimeError("Deterministic recommendation is missing")
        return CandidateSelectionResult(
            selected_candidate=selected,
            accepted_llm_selection=False,
            fallback_used=True,
            validation_status=f"{reason}; deterministic recommendation used",
            confidence_gate_status=gate,
            low_confidence_fallback=low,
            invalid_ranking_fallback=invalid,
        )

    @staticmethod
    def _unsupported_unavailable_claim(reason: str) -> bool:
        text = reason.lower()
        mentions = re.search(
            r"\b(occupancy|occupied|unoccupied|occupants?|pmv)\b",
            text,
        )
        qualified = re.search(
            r"\b(unavailable|unknown|not available|not provided|false)\b",
            text,
        )
        return bool(mentions and not qualified)
