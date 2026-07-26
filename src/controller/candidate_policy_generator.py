"""Generate bounded policy choices from deterministic state classifications."""

from __future__ import annotations

from dataclasses import replace

from controller.policy_candidate import CandidatePolicySet, PolicyCandidate
from controller.policy_validator import PolicyValidator
from controller.state_summary import StateSummary
from controller.supervisor_policy import (
    ControllerAggressiveness,
    Priority,
    SupervisorPolicy,
)


class CandidatePolicyGenerator:
    """Expose only fixed templates that are valid for the current state."""

    def __init__(self, validator: PolicyValidator | None = None) -> None:
        self.validator = validator or PolicyValidator()

    def generate(
        self,
        summary: StateSummary,
        current_policy: SupervisorPolicy,
    ) -> CandidatePolicySet:
        hot = summary.thermal_state in {
            "above_target",
            "far_above_target",
        }
        rising = summary.zone_trend in {"rising", "strongly_rising"}
        falling = summary.zone_trend in {"falling", "strongly_falling"}

        if not summary.history_sufficient or summary.contradictory_data:
            return self._set(
                ("P6",),
                "P6",
                "insufficient_or_contradictory_data",
                current_policy,
                emergency=True,
            )
        if (
            summary.thermal_state == "far_above_target"
            and summary.zone_trend == "strongly_rising"
        ):
            return self._set(
                ("P1",),
                "P1",
                "severe_thermal_deterioration",
                current_policy,
                emergency=True,
            )
        if (
            current_policy.energy_priority == Priority.HIGH
            and hot
            and rising
        ):
            return self._set(
                ("P1", "P2"),
                "P1",
                "overheating_under_energy_saving_policy",
                current_policy,
            )
        if hot and rising:
            return self._set(
                ("P1", "P2", "P3"),
                "P2",
                "hot_and_rising",
                current_policy,
            )
        if hot and falling:
            return self._set(
                ("P2", "P3", "P6"),
                "P3",
                "hot_but_recovering",
                current_policy,
            )
        if (
            summary.thermal_state in {"near_target", "below_target"}
            and summary.high_power
        ):
            return self._set(
                ("P3", "P4", "P5", "P6"),
                "P4",
                "thermally_acceptable_with_high_power",
                current_policy,
            )
        if summary.outdoor_trend == "strongly_rising":
            return self._set(
                ("P2", "P3", "P6"),
                "P3",
                "rapid_outdoor_load_increase",
                current_policy,
            )
        if (
            summary.thermal_state == "near_target"
            and summary.zone_trend == "stable"
            and summary.power_trend == "stable"
        ):
            return self._set(
                ("P3", "P4", "P6"),
                "P6",
                "stable_balanced_conditions",
                current_policy,
            )
        return self._set(
            ("P3", "P6"),
            "P6",
            "default_bounded_choice",
            current_policy,
        )

    def _set(
        self,
        ids: tuple[str, ...],
        recommendation: str,
        reason: str,
        current_policy: SupervisorPolicy,
        emergency: bool = False,
    ) -> CandidatePolicySet:
        score_order = [recommendation] + [
            candidate_id for candidate_id in ids if candidate_id != recommendation
        ]
        candidates = tuple(
            self._validated_candidate(
                self._template(candidate_id, current_policy),
                current_policy,
                float(len(score_order) - score_order.index(candidate_id)),
                reason,
            )
            for candidate_id in ids
        )
        return CandidatePolicySet(
            candidates=candidates,
            deterministic_recommendation_id=recommendation,
            deterministic_ranking=tuple(score_order),
            generation_reason=reason,
            emergency_forced=emergency,
            ambiguity_detected=len(candidates) > 1,
        )

    def _validated_candidate(
        self,
        candidate: PolicyCandidate,
        current_policy: SupervisorPolicy,
        score: float,
        rationale: str,
    ) -> PolicyCandidate:
        validation = self.validator.validate(
            candidate.to_policy(),
            previous_policy=current_policy,
        )
        policy = validation.validated_policy
        return replace(
            candidate,
            thermal_priority=policy.thermal_priority,
            energy_priority=policy.energy_priority,
            controller_aggressiveness=policy.controller_aggressiveness,
            target_zone_temperature_c=policy.target_zone_temperature_c,
            minimum_action_hold_intervals=policy.minimum_action_hold_intervals,
            policy_duration_hours=policy.policy_duration_hours,
            strategy=policy.strategy,
            reason=policy.reason,
            deterministic_score=score,
            rationale_code=rationale,
        )

    @staticmethod
    def _template(
        candidate_id: str,
        current: SupervisorPolicy,
    ) -> PolicyCandidate:
        values = {
            "P1": (
                "thermal_recovery_aggressive",
                Priority.HIGH,
                Priority.LOW,
                ControllerAggressiveness.AGGRESSIVE,
                31.0,
                1,
                4,
            ),
            "P2": (
                "thermal_recovery_balanced",
                Priority.HIGH,
                Priority.MEDIUM,
                ControllerAggressiveness.NORMAL,
                31.5,
                2,
                4,
            ),
            "P3": (
                "balanced",
                Priority.MEDIUM,
                Priority.MEDIUM,
                ControllerAggressiveness.NORMAL,
                32.0,
                2,
                4,
            ),
            "P4": (
                "energy_conservative",
                Priority.MEDIUM,
                Priority.HIGH,
                ControllerAggressiveness.CONSERVATIVE,
                32.5,
                3,
                4,
            ),
            "P5": (
                "energy_saving",
                Priority.LOW,
                Priority.HIGH,
                ControllerAggressiveness.CONSERVATIVE,
                33.0,
                4,
                4,
            ),
            "P6": (
                "hold_current",
                current.thermal_priority,
                current.energy_priority,
                current.controller_aggressiveness,
                current.target_zone_temperature_c,
                current.minimum_action_hold_intervals,
                current.policy_duration_hours,
            ),
        }
        if candidate_id not in values:
            raise ValueError(f"Unknown fixed candidate ID: {candidate_id}")
        mode, thermal, energy, aggression, target, hold, duration = values[
            candidate_id
        ]
        return PolicyCandidate(
            candidate_id=candidate_id,
            mode=mode,
            thermal_priority=thermal,
            energy_priority=energy,
            controller_aggressiveness=aggression,
            target_zone_temperature_c=target,
            minimum_action_hold_intervals=hold,
            policy_duration_hours=duration,
            strategy=mode,
            deterministic_score=0.0,
            rationale_code="",
            reason=f"Deterministic safe candidate: {mode}.",
        )
