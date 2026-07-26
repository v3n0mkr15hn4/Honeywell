"""Deterministic candidate-ranking responses for boundary validation."""

from __future__ import annotations

import json
import re
import time
from enum import Enum

from llm.client import LLMClient, LLMTimeoutError


class CandidateRankerMockMode(str, Enum):
    VALID_TOP_DETERMINISTIC = "valid_top_deterministic"
    VALID_ALTERNATIVE_HIGH_CONFIDENCE = "valid_alternative_high_confidence"
    VALID_MEDIUM_CONFIDENCE_TOP_TWO = "valid_medium_confidence_top_two"
    LOW_CONFIDENCE = "low_confidence"
    UNKNOWN_CANDIDATE = "unknown_candidate"
    DUPLICATE_RANKING = "duplicate_ranking"
    INCOMPLETE_RANKING = "incomplete_ranking"
    SELECTED_NOT_FIRST = "selected_not_first"
    EXTRA_ACTUATOR_FIELD = "extra_actuator_field"
    EXTRA_POLICY_VALUES = "extra_policy_values"
    MALFORMED_JSON = "malformed_json"
    TIMEOUT = "timeout"
    EXCEPTION = "exception"


class MockCandidateRankerLLMClient(LLMClient):
    def __init__(
        self,
        mode: CandidateRankerMockMode = (
            CandidateRankerMockMode.VALID_TOP_DETERMINISTIC
        ),
    ) -> None:
        self.mode = mode
        self.request_count = 0
        self.last_prompt: str | None = None
        self.last_response_duration_seconds: float | None = None

    def query(self, prompt: str) -> str:
        self.request_count += 1
        self.last_prompt = prompt
        start = time.perf_counter()
        try:
            return self._response(prompt)
        finally:
            self.last_response_duration_seconds = time.perf_counter() - start

    def _response(self, prompt: str) -> str:
        ids = self._ids(prompt)
        recommendation = self._recommendation(prompt)
        ordered = [recommendation] + [
            candidate_id for candidate_id in ids if candidate_id != recommendation
        ]
        if self.mode == CandidateRankerMockMode.EXCEPTION:
            raise RuntimeError("Mock candidate ranker unavailable")
        if self.mode == CandidateRankerMockMode.TIMEOUT:
            raise LLMTimeoutError("Mock candidate ranker timed out")
        if self.mode == CandidateRankerMockMode.MALFORMED_JSON:
            return "rank the deterministic option first"
        if self.mode == CandidateRankerMockMode.UNKNOWN_CANDIDATE:
            ordered[-1] = "P99"
        elif self.mode == CandidateRankerMockMode.DUPLICATE_RANKING:
            ordered[-1] = ordered[0]
        elif self.mode == CandidateRankerMockMode.INCOMPLETE_RANKING:
            ordered = ordered[:-1]
        elif (
            self.mode
            == CandidateRankerMockMode.VALID_ALTERNATIVE_HIGH_CONFIDENCE
        ):
            ordered = ordered[1:] + ordered[:1]
        elif (
            self.mode
            == CandidateRankerMockMode.VALID_MEDIUM_CONFIDENCE_TOP_TWO
            and len(ordered) > 1
        ):
            ordered[0], ordered[1] = ordered[1], ordered[0]
        confidence = (
            0.30
            if self.mode == CandidateRankerMockMode.LOW_CONFIDENCE
            else 0.65
            if self.mode
            == CandidateRankerMockMode.VALID_MEDIUM_CONFIDENCE_TOP_TWO
            else 0.90
        )
        selected = ordered[0]
        if self.mode == CandidateRankerMockMode.SELECTED_NOT_FIRST:
            selected = ordered[-1]
        payload: dict[str, object] = {
            "ranking": ordered,
            "selected_policy_id": selected,
            "confidence": confidence,
            "reason": (
                "Thermal state and power trend support this supplied candidate."
            ),
        }
        if self.mode == CandidateRankerMockMode.EXTRA_ACTUATOR_FIELD:
            payload["supply_air_temperature_setpoint"] = 22.0
        if self.mode == CandidateRankerMockMode.EXTRA_POLICY_VALUES:
            payload["target_zone_temperature_c"] = 31.0
        return json.dumps(payload, separators=(",", ":"))

    @staticmethod
    def _ids(prompt: str) -> list[str]:
        match = re.search(r"^Candidate IDs: (.+)$", prompt, re.MULTILINE)
        if not match:
            raise RuntimeError("Candidate IDs missing from mock prompt")
        return [item.strip() for item in match.group(1).split(",")]

    @staticmethod
    def _recommendation(prompt: str) -> str:
        match = re.search(
            r"^Deterministic recommendation ID: (P\d+)$",
            prompt,
            re.MULTILINE,
        )
        if not match:
            raise RuntimeError("Recommendation missing from mock prompt")
        return match.group(1)
