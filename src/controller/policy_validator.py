"""Safety validation for bounded supervisory policy."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from controller.supervisor_policy import (
    ControllerAggressiveness,
    Priority,
    SupervisorPolicy,
    default_supervisor_policy,
)


@dataclass(frozen=True)
class PolicyLimits:
    minimum_target_zone_temperature_c: float = 30.0
    maximum_target_zone_temperature_c: float = 34.0
    minimum_action_hold_intervals: int = 1
    maximum_action_hold_intervals: int = 6
    minimum_policy_duration_hours: int = 4
    maximum_policy_duration_hours: int = 12
    maximum_target_change_c: float = 1.0
    maximum_hold_interval_change: int = 2
    maximum_duration_change_hours: int = 4


@dataclass(frozen=True)
class PolicyValidationResult:
    validated_policy: SupervisorPolicy
    corrected: bool
    validation_status: str
    rejected_fields: tuple[str, ...]


class PolicyValidator:
    """Correct unsafe policy values without weakening physical safety."""

    def __init__(
        self,
        limits: PolicyLimits | None = None,
        default_policy: SupervisorPolicy | None = None,
    ) -> None:
        self.limits = limits or PolicyLimits()
        self.default_policy = default_policy or default_supervisor_policy()

    def validate(
        self,
        proposed_policy: SupervisorPolicy,
        previous_policy: SupervisorPolicy | None = None,
    ) -> PolicyValidationResult:
        messages: list[str] = []
        rejected: list[str] = []
        baseline = previous_policy or self.default_policy

        thermal = self._enum_value(
            proposed_policy.thermal_priority,
            Priority,
            baseline.thermal_priority,
            "thermal_priority",
            messages,
            rejected,
        )
        energy = self._enum_value(
            proposed_policy.energy_priority,
            Priority,
            baseline.energy_priority,
            "energy_priority",
            messages,
            rejected,
        )
        aggressiveness = self._enum_value(
            proposed_policy.controller_aggressiveness,
            ControllerAggressiveness,
            baseline.controller_aggressiveness,
            "controller_aggressiveness",
            messages,
            rejected,
        )
        target = self._finite_float(
            proposed_policy.target_zone_temperature_c,
            baseline.target_zone_temperature_c,
            "target_zone_temperature_c",
            messages,
            rejected,
        )
        target = self._clamp_float(
            target,
            self.limits.minimum_target_zone_temperature_c,
            self.limits.maximum_target_zone_temperature_c,
            "target_zone_temperature_c",
            messages,
        )
        if previous_policy is not None:
            target = self._limit_float_change(
                target,
                previous_policy.target_zone_temperature_c,
                self.limits.maximum_target_change_c,
                "target_zone_temperature_c",
                messages,
            )

        hold = self._integer(
            proposed_policy.minimum_action_hold_intervals,
            baseline.minimum_action_hold_intervals,
            "minimum_action_hold_intervals",
            messages,
            rejected,
        )
        hold = self._clamp_int(
            hold,
            self.limits.minimum_action_hold_intervals,
            self.limits.maximum_action_hold_intervals,
            "minimum_action_hold_intervals",
            messages,
        )
        duration = self._integer(
            proposed_policy.policy_duration_hours,
            baseline.policy_duration_hours,
            "policy_duration_hours",
            messages,
            rejected,
        )
        duration = self._clamp_int(
            duration,
            self.limits.minimum_policy_duration_hours,
            self.limits.maximum_policy_duration_hours,
            "policy_duration_hours",
            messages,
        )
        if previous_policy is not None:
            hold = self._limit_int_change(
                hold,
                previous_policy.minimum_action_hold_intervals,
                self.limits.maximum_hold_interval_change,
                "minimum_action_hold_intervals",
                messages,
            )
            duration = self._limit_int_change(
                duration,
                previous_policy.policy_duration_hours,
                self.limits.maximum_duration_change_hours,
                "policy_duration_hours",
                messages,
            )

        strategy = self._text(
            proposed_policy.strategy,
            baseline.strategy,
            "strategy",
            messages,
            rejected,
        )
        reason = self._text(
            proposed_policy.reason,
            baseline.reason,
            "reason",
            messages,
            rejected,
        )
        validated = SupervisorPolicy(
            thermal_priority=thermal,
            energy_priority=energy,
            controller_aggressiveness=aggressiveness,
            target_zone_temperature_c=target,
            minimum_action_hold_intervals=hold,
            policy_duration_hours=duration,
            strategy=strategy,
            reason=reason,
        )
        return PolicyValidationResult(
            validated_policy=validated,
            corrected=bool(messages),
            validation_status="; ".join(messages) if messages else "valid",
            rejected_fields=tuple(dict.fromkeys(rejected)),
        )

    @staticmethod
    def _enum_value(
        value: Any,
        enum_type: type[Priority] | type[ControllerAggressiveness],
        fallback: Any,
        field: str,
        messages: list[str],
        rejected: list[str],
    ) -> Any:
        try:
            return enum_type(value)
        except (TypeError, ValueError):
            messages.append(f"{field} rejected; previous/default retained")
            rejected.append(field)
            return fallback

    @staticmethod
    def _finite_float(
        value: Any,
        fallback: float,
        field: str,
        messages: list[str],
        rejected: list[str],
    ) -> float:
        if isinstance(value, bool):
            parsed = math.nan
        else:
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                parsed = math.nan
        if not math.isfinite(parsed):
            messages.append(f"{field} rejected as non-finite")
            rejected.append(field)
            return fallback
        return parsed

    @staticmethod
    def _integer(
        value: Any,
        fallback: int,
        field: str,
        messages: list[str],
        rejected: list[str],
    ) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            messages.append(f"{field} rejected as non-integer")
            rejected.append(field)
            return fallback
        return value

    @staticmethod
    def _text(
        value: Any,
        fallback: str,
        field: str,
        messages: list[str],
        rejected: list[str],
    ) -> str:
        if not isinstance(value, str) or not value.strip():
            messages.append(f"{field} rejected as empty")
            rejected.append(field)
            return fallback
        return value.strip()

    @staticmethod
    def _clamp_float(
        value: float,
        minimum: float,
        maximum: float,
        field: str,
        messages: list[str],
    ) -> float:
        clamped = min(maximum, max(minimum, value))
        if clamped != value:
            messages.append(f"{field} clamped to {clamped:.1f}")
        return clamped

    @staticmethod
    def _clamp_int(
        value: int,
        minimum: int,
        maximum: int,
        field: str,
        messages: list[str],
    ) -> int:
        clamped = min(maximum, max(minimum, value))
        if clamped != value:
            messages.append(f"{field} clamped to {clamped}")
        return clamped

    @staticmethod
    def _limit_float_change(
        value: float,
        previous: float,
        maximum_change: float,
        field: str,
        messages: list[str],
    ) -> float:
        limited = min(previous + maximum_change, max(previous - maximum_change, value))
        if limited != value:
            messages.append(f"{field} change limited to {limited:.1f}")
        return limited

    @staticmethod
    def _limit_int_change(
        value: int,
        previous: int,
        maximum_change: int,
        field: str,
        messages: list[str],
    ) -> int:
        limited = min(previous + maximum_change, max(previous - maximum_change, value))
        if limited != value:
            messages.append(f"{field} change limited to {limited}")
        return limited
