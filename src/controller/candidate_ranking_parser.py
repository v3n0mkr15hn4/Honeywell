"""Strict structural parser for candidate-ranking responses."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any


class CandidateRankingParserError(ValueError):
    """Raised when ranking JSON violates the exact structural contract."""


@dataclass(frozen=True)
class ParsedCandidateRanking:
    ranking: tuple[str, ...]
    selected_policy_id: str
    confidence: float
    reason: str


CANDIDATE_RANKING_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "ranking": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [f"P{index}" for index in range(1, 7)],
            },
            "minItems": 1,
            "maxItems": 6,
            "uniqueItems": True,
        },
        "selected_policy_id": {
            "type": "string",
            "enum": [f"P{index}" for index in range(1, 7)],
        },
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "reason": {"type": "string", "minLength": 1},
    },
    "required": [
        "ranking",
        "selected_policy_id",
        "confidence",
        "reason",
    ],
    "additionalProperties": False,
}
REQUIRED_KEYS = frozenset(CANDIDATE_RANKING_RESPONSE_SCHEMA["required"])


def parse_candidate_ranking(text: str) -> ParsedCandidateRanking:
    try:
        data = json.loads(
            text,
            parse_constant=lambda value: _raise_nonfinite(value),
        )
    except (json.JSONDecodeError, CandidateRankingParserError) as exc:
        raise CandidateRankingParserError(
            f"Candidate ranking is not strict JSON: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise CandidateRankingParserError("Ranking JSON must be an object.")
    missing = REQUIRED_KEYS - data.keys()
    extra = data.keys() - REQUIRED_KEYS
    if missing:
        raise CandidateRankingParserError(
            "Ranking response missing required keys: "
            + ", ".join(sorted(missing))
        )
    if extra:
        raise CandidateRankingParserError(
            "Ranking response has unexpected keys: "
            + ", ".join(sorted(extra))
        )
    ranking = data["ranking"]
    if (
        not isinstance(ranking, list)
        or not ranking
        or any(not isinstance(item, str) or not item.strip() for item in ranking)
    ):
        raise CandidateRankingParserError(
            "ranking must be a non-empty array of non-empty strings."
        )
    normalized = tuple(item.strip() for item in ranking)
    if len(set(normalized)) != len(normalized):
        raise CandidateRankingParserError(
            "ranking must not contain duplicate candidate IDs."
        )
    selected = data["selected_policy_id"]
    if not isinstance(selected, str) or not selected.strip():
        raise CandidateRankingParserError(
            "selected_policy_id must be a non-empty string."
        )
    confidence = data["confidence"]
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise CandidateRankingParserError("confidence must be numeric.")
    confidence_value = float(confidence)
    if not math.isfinite(confidence_value) or not 0.0 <= confidence_value <= 1.0:
        raise CandidateRankingParserError(
            "confidence must be finite and between 0 and 1."
        )
    reason = data["reason"]
    if not isinstance(reason, str) or not reason.strip():
        raise CandidateRankingParserError("reason must be non-empty.")
    return ParsedCandidateRanking(
        ranking=normalized,
        selected_policy_id=selected.strip(),
        confidence=confidence_value,
        reason=reason.strip(),
    )


def _raise_nonfinite(value: str) -> None:
    raise CandidateRankingParserError(f"Non-finite JSON number: {value}")
