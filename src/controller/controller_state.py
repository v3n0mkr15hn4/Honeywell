"""State maintained by the controller pipeline between callbacks."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from controller.action import ControlAction
from controller.state import BuildingState
from controller.supervisor_policy import (
    SupervisorPolicy,
    default_supervisor_policy,
)


@dataclass
class ControllerState:
    """Memory for the closed-loop controller.

    ``previous_action`` is applied at the next begin-zone-timestep callback.
    The next action is computed later, after EnergyPlus reports sensor values.
    """

    previous_action: ControlAction | None = None
    timestep: int = 0
    last_strategy: str = ""
    consecutive_llm_failures: int = 0
    last_llm_decision_timestep: int | None = None
    cooldown_intervals_remaining: int = 0
    cooldown_activations: int = 0
    last_fallback_reason: str = ""
    previous_validation_status: str = ""
    last_requested_action: ControlAction | None = None
    current_supervisor_policy: SupervisorPolicy = field(
        default_factory=default_supervisor_policy,
    )
    previous_supervisor_policy: SupervisorPolicy | None = None
    supervisor_policy_created_timestep: int = 0
    supervisor_policy_age_hours: float = 0.0
    last_supervisor_call_timestep: int | None = None
    hours_since_supervisor_call: float = 0.0
    supervisor_response_time_s: float | None = None
    supervisor_fallback_used: bool = False
    supervisor_failure_reason: str = ""
    supervisor_validation_status: str = "default policy"
    consecutive_supervisor_failures: int = 0
    supervisor_cooldown_remaining: int = 0
    supervisor_cooldown_activations: int = 0
    policy_change_count: int = 0
    physical_action_hold_intervals_elapsed: int = 0
    history: deque[BuildingState] = field(
        default_factory=lambda: deque(maxlen=72),
    )

    @property
    def previous_supply_air_temperature_setpoint(self) -> float | None:
        if self.previous_action is None:
            return None
        return self.previous_action.supply_air_temperature_setpoint

    @property
    def cooldown_active(self) -> bool:
        return self.cooldown_intervals_remaining > 0

    def append_building_state(self, state: BuildingState) -> None:
        """Retain a small bounded trend history without external libraries."""

        self.history.append(state)
