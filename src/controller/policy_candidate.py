"""Immutable, actuator-free policy candidates."""

from __future__ import annotations

from dataclasses import dataclass

from controller.supervisor_policy import (
    ControllerAggressiveness,
    Priority,
    SupervisorPolicy,
)


@dataclass(frozen=True)
class PolicyCandidate:
    """One complete, deterministically generated SupervisorPolicy option."""

    candidate_id: str
    mode: str
    thermal_priority: Priority
    energy_priority: Priority
    controller_aggressiveness: ControllerAggressiveness
    target_zone_temperature_c: float
    minimum_action_hold_intervals: int
    policy_duration_hours: int
    strategy: str
    deterministic_score: float
    rationale_code: str
    reason: str

    def to_policy(self) -> SupervisorPolicy:
        return SupervisorPolicy(
            thermal_priority=self.thermal_priority,
            energy_priority=self.energy_priority,
            controller_aggressiveness=self.controller_aggressiveness,
            target_zone_temperature_c=self.target_zone_temperature_c,
            minimum_action_hold_intervals=self.minimum_action_hold_intervals,
            policy_duration_hours=self.policy_duration_hours,
            strategy=self.strategy,
            reason=self.reason,
        )


@dataclass(frozen=True)
class CandidatePolicySet:
    candidates: tuple[PolicyCandidate, ...]
    deterministic_recommendation_id: str
    deterministic_ranking: tuple[str, ...]
    generation_reason: str
    emergency_forced: bool
    ambiguity_detected: bool

    def candidate(self, candidate_id: str) -> PolicyCandidate | None:
        return next(
            (
                candidate
                for candidate in self.candidates
                if candidate.candidate_id == candidate_id
            ),
            None,
        )
