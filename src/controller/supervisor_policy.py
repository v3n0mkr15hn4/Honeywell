"""Bounded high-level policy used by deterministic physical control."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ControllerAggressiveness(str, Enum):
    CONSERVATIVE = "conservative"
    NORMAL = "normal"
    AGGRESSIVE = "aggressive"


@dataclass(frozen=True)
class SupervisorPolicy:
    """Validated guidance that contains no physical actuator command."""

    thermal_priority: Priority
    energy_priority: Priority
    controller_aggressiveness: ControllerAggressiveness
    target_zone_temperature_c: float
    minimum_action_hold_intervals: int
    policy_duration_hours: int
    strategy: str
    reason: str


def default_supervisor_policy() -> SupervisorPolicy:
    """Return the deterministic policy used when supervision is unavailable."""

    return SupervisorPolicy(
        thermal_priority=Priority.HIGH,
        energy_priority=Priority.MEDIUM,
        controller_aggressiveness=ControllerAggressiveness.NORMAL,
        target_zone_temperature_c=32.0,
        minimum_action_hold_intervals=2,
        policy_duration_hours=6,
        strategy="balanced_default",
        reason="Safe deterministic startup policy.",
    )
