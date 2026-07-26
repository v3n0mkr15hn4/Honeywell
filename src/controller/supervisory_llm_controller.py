"""Low-frequency LLM boundary that can return policy but never ControlAction."""

from __future__ import annotations

import time
from dataclasses import dataclass

from controller.controller_state import ControllerState
from controller.policy_prompt_builder import build_policy_prompt
from controller.policy_validator import (
    PolicyValidationResult,
    PolicyValidator,
)
from controller.state import BuildingState
from controller.supervisor_output_parser import (
    SupervisorOutputParserError,
    parse_supervisor_response,
)
from controller.supervisor_policy import (
    SupervisorPolicy,
    default_supervisor_policy,
)
from llm.client import LLMClient, LLMTimeoutError


@dataclass(frozen=True)
class SupervisoryDecisionResult:
    policy: SupervisorPolicy
    validation: PolicyValidationResult
    fallback_used: bool
    used_default_policy: bool
    failure_reason: str
    response_time_s: float
    parser_failure: bool
    timeout: bool
    policy_changed: bool


class SupervisoryLLMController:
    """Generate validated high-level policy with deterministic fallback."""

    def __init__(
        self,
        client: LLMClient,
        validator: PolicyValidator,
        provider: str = "mock",
        model: str = "deterministic-mock",
        policy_grace_period_hours: float = 2.0,
    ) -> None:
        self.client = client
        self.validator = validator
        self.provider = provider
        self.model = model
        self.policy_grace_period_hours = policy_grace_period_hours
        self.request_in_flight = False

    def recommend(
        self,
        state: BuildingState,
        controller_state: ControllerState,
        metrics_snapshot: dict[str, object],
    ) -> SupervisoryDecisionResult:
        """Return validated policy and never propagate an inference failure."""

        if self.request_in_flight:
            return self._failure_result(
                RuntimeError("supervisory request already in flight"),
                controller_state,
                0.0,
            )
        current = controller_state.current_supervisor_policy
        prompt = build_policy_prompt(
            state,
            controller_state,
            metrics_snapshot,
            current,
        )
        start = time.perf_counter()
        self.request_in_flight = True
        try:
            response = self.client.query(prompt)
            proposed = parse_supervisor_response(response)
            validation = self.validator.validate(
                proposed,
                previous_policy=current,
            )
            elapsed = time.perf_counter() - start
            return SupervisoryDecisionResult(
                policy=validation.validated_policy,
                validation=validation,
                fallback_used=False,
                used_default_policy=False,
                failure_reason="",
                response_time_s=elapsed,
                parser_failure=False,
                timeout=False,
                policy_changed=validation.validated_policy != current,
            )
        except Exception as exc:
            return self._failure_result(
                exc,
                controller_state,
                time.perf_counter() - start,
            )
        finally:
            self.request_in_flight = False

    def _failure_result(
        self,
        exc: Exception,
        controller_state: ControllerState,
        elapsed: float,
    ) -> SupervisoryDecisionResult:
        current = controller_state.current_supervisor_policy
        policy, used_default = self._fallback_policy(controller_state)
        validation = PolicyValidationResult(
            validated_policy=policy,
            corrected=False,
            validation_status=(
                "supervisor failure; "
                + ("default policy" if used_default else "previous policy")
                + " retained"
            ),
            rejected_fields=(),
        )
        print(
            "[Supervisor] Policy generation failed; deterministic policy "
            f"retained: {exc}"
        )
        return SupervisoryDecisionResult(
            policy=policy,
            validation=validation,
            fallback_used=True,
            used_default_policy=used_default,
            failure_reason=f"{type(exc).__name__}: {exc}",
            response_time_s=elapsed,
            parser_failure=isinstance(exc, SupervisorOutputParserError),
            timeout=isinstance(exc, (LLMTimeoutError, TimeoutError)),
            policy_changed=policy != current,
        )

    def _fallback_policy(
        self,
        controller_state: ControllerState,
    ) -> tuple[SupervisorPolicy, bool]:
        current = controller_state.current_supervisor_policy
        usable_until = (
            current.policy_duration_hours + self.policy_grace_period_hours
        )
        if controller_state.supervisor_policy_age_hours <= usable_until:
            return current, False
        return default_supervisor_policy(), True
