"""Bounded LLM ranker that can select, but never create, policy."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from controller.candidate_policy_generator import CandidatePolicyGenerator
from controller.candidate_policy_prompt_builder import (
    build_candidate_policy_prompt,
)
from controller.candidate_ranking_parser import (
    CandidateRankingParserError,
    ParsedCandidateRanking,
    parse_candidate_ranking,
)
from controller.candidate_selection_validator import (
    CandidateSelectionResult,
    CandidateSelectionValidator,
)
from controller.controller_state import ControllerState
from controller.deterministic_feature_extractor import (
    DeterministicFeatureExtractor,
)
from controller.policy_candidate import CandidatePolicySet, PolicyCandidate
from controller.policy_validator import PolicyValidationResult, PolicyValidator
from controller.state import BuildingState
from controller.state_summary import StateSummary
from controller.supervisor_policy import SupervisorPolicy
from llm.client import LLMClient, LLMTimeoutError


@dataclass(frozen=True)
class CandidateRankerDecisionResult:
    policy: SupervisorPolicy
    validation: PolicyValidationResult
    fallback_used: bool
    used_default_policy: bool
    failure_reason: str
    response_time_s: float
    parser_failure: bool
    timeout: bool
    policy_changed: bool
    state_summary: StateSummary
    candidate_set: CandidatePolicySet
    selected_candidate: PolicyCandidate
    parsed_ranking: ParsedCandidateRanking | None
    selection: CandidateSelectionResult | None
    llm_called: bool
    forced_single_candidate: bool
    selected_policy_source: str
    raw_response: str
    llm_request_started: bool
    llm_request_completed: bool
    llm_retry_count: int
    llm_http_status_category: str
    llm_failure_category: str


class LLMPolicyRanker:
    """Rank deterministic safe candidates at the supervisory cadence."""

    uses_candidate_ranking = True

    def __init__(
        self,
        client: LLMClient,
        validator: PolicyValidator,
        feature_extractor: DeterministicFeatureExtractor | None = None,
        candidate_generator: CandidatePolicyGenerator | None = None,
        selection_validator: CandidateSelectionValidator | None = None,
        provider: str = "mock",
        model: str = "deterministic-mock",
        policy_grace_period_hours: float = 2.0,
    ) -> None:
        self.client = client
        self.validator = validator
        self.feature_extractor = (
            feature_extractor or DeterministicFeatureExtractor()
        )
        self.candidate_generator = (
            candidate_generator or CandidatePolicyGenerator(validator)
        )
        self.selection_validator = (
            selection_validator or CandidateSelectionValidator()
        )
        self.provider = provider
        self.model = model
        self.policy_grace_period_hours = policy_grace_period_hours
        self.request_in_flight = False

    def recommend(
        self,
        state: BuildingState,
        controller_state: ControllerState,
        metrics_snapshot: dict[str, object],
    ) -> CandidateRankerDecisionResult:
        del metrics_snapshot
        current = controller_state.current_supervisor_policy
        summary = self.feature_extractor.extract(
            state,
            tuple(controller_state.history),
            current,
            controller_state.supervisor_policy_age_hours,
        )
        candidate_set = self.candidate_generator.generate(summary, current)
        if len(candidate_set.candidates) == 1:
            selected = candidate_set.candidates[0]
            return self._result(
                current,
                summary,
                candidate_set,
                selected,
                None,
                None,
                False,
                True,
                "forced_single_candidate",
                "",
                0.0,
            )
        if self.request_in_flight:
            return self._failure(
                RuntimeError("candidate ranking request already in flight"),
                current,
                summary,
                candidate_set,
                0.0,
                "",
            )
        prompt = build_candidate_policy_prompt(summary, candidate_set)
        start = time.perf_counter()
        self.request_in_flight = True
        raw = ""
        try:
            raw = self.client.query(prompt)
            parsed = parse_candidate_ranking(raw)
            selection = self.selection_validator.validate(
                parsed,
                candidate_set,
            )
            source = (
                "llm_selected"
                if selection.accepted_llm_selection
                else "deterministic_fallback"
            )
            return self._result(
                current,
                summary,
                candidate_set,
                selection.selected_candidate,
                parsed,
                selection,
                True,
                False,
                source,
                raw,
                time.perf_counter() - start,
            )
        except Exception as exc:
            return self._failure(
                exc,
                current,
                summary,
                candidate_set,
                time.perf_counter() - start,
                raw,
            )
        finally:
            self.request_in_flight = False

    def _failure(
        self,
        exc: Exception,
        current: SupervisorPolicy,
        summary: StateSummary,
        candidate_set: CandidatePolicySet,
        elapsed: float,
        raw: str,
    ) -> CandidateRankerDecisionResult:
        selected = candidate_set.candidate(
            candidate_set.deterministic_recommendation_id
        )
        if selected is None:
            raise RuntimeError("Deterministic fallback candidate is missing")
        return self._result(
            current,
            summary,
            candidate_set,
            selected,
            None,
            None,
            True,
            False,
            "deterministic_fallback",
            raw,
            elapsed,
            failure_reason=f"{type(exc).__name__}: {exc}",
            parser_failure=isinstance(exc, CandidateRankingParserError),
            timeout=isinstance(exc, (LLMTimeoutError, TimeoutError)),
        )

    def _result(
        self,
        current: SupervisorPolicy,
        summary: StateSummary,
        candidate_set: CandidatePolicySet,
        selected: PolicyCandidate,
        parsed: ParsedCandidateRanking | None,
        selection: CandidateSelectionResult | None,
        llm_called: bool,
        forced: bool,
        source: str,
        raw: str,
        elapsed: float,
        failure_reason: str = "",
        parser_failure: bool = False,
        timeout: bool = False,
    ) -> CandidateRankerDecisionResult:
        validation = self.validator.validate(
            selected.to_policy(),
            previous_policy=current,
        )
        fallback = bool(failure_reason) or bool(
            selection and selection.fallback_used
        )
        reason = failure_reason or (
            selection.validation_status
            if selection and selection.fallback_used
            else ""
        )
        failure_category = ""
        if failure_reason:
            failure_category = str(
                getattr(self.client, "last_failure_category", "")
                or ("parser_error" if parser_failure else "transport_error")
            )
        elif selection and selection.fallback_used:
            failure_category = (
                "low_confidence"
                if selection.low_confidence_fallback
                else "invalid_ranking"
            )
        return CandidateRankerDecisionResult(
            policy=validation.validated_policy,
            validation=validation,
            fallback_used=fallback,
            used_default_policy=False,
            failure_reason=reason,
            response_time_s=elapsed,
            parser_failure=parser_failure,
            timeout=timeout,
            policy_changed=validation.validated_policy != current,
            state_summary=summary,
            candidate_set=candidate_set,
            selected_candidate=selected,
            parsed_ranking=parsed,
            selection=selection,
            llm_called=llm_called,
            forced_single_candidate=forced,
            selected_policy_source=source,
            raw_response=raw,
            llm_request_started=(
                bool(getattr(self.client, "last_request_started", True))
                if llm_called
                else False
            ),
            llm_request_completed=(
                bool(getattr(self.client, "last_request_completed", True))
                if llm_called
                else False
            ),
            llm_retry_count=(
                int(getattr(self.client, "last_retry_count", 0))
                if llm_called
                else 0
            ),
            llm_http_status_category=(
                str(getattr(self.client, "last_http_status_category", ""))
                if llm_called
                else ""
            ),
            llm_failure_category=failure_category,
        )
