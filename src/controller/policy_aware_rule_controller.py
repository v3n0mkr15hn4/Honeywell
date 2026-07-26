"""Deterministic physical controller influenced by validated policy."""

from __future__ import annotations

from controller.action import ControlAction
from controller.controller_state import ControllerState
from controller.state import BuildingState
from controller.supervisor_policy import (
    ControllerAggressiveness,
    Priority,
    SupervisorPolicy,
    default_supervisor_policy,
)


class PolicyAwareRuleController:
    """Translate bounded policy into safe, deterministic rule thresholds."""

    controller_type = "PolicyAwareRuleController"
    uses_controller_state = True
    uses_supervisor_policy = True

    def decide(
        self,
        state: BuildingState,
        controller_state: ControllerState,
        policy: SupervisorPolicy | None = None,
    ) -> ControlAction:
        """Produce the physical node target; policy never contains that target."""

        active_policy = policy or default_supervisor_policy()
        previous_temperature = (
            controller_state.history[-1].zone_temperature
            if controller_state.history
            else None
        )
        rising = (
            previous_temperature is not None
            and state.zone_temperature - previous_temperature >= 0.2
        )
        high_threshold = self._high_threshold(active_policy)
        moderate_threshold = high_threshold - 3.0

        if (
            state.zone_temperature >= high_threshold
            or (
                rising
                and active_policy.thermal_priority == Priority.HIGH
            )
        ):
            proposed = 22.0
            strategy = "policy_increase_cooling"
            reason = (
                "Deterministic thermal rule lowers the node target because "
                "the zone is above the policy threshold or rising."
            )
        elif state.zone_temperature >= moderate_threshold:
            proposed = 23.0
            strategy = "policy_moderate_cooling"
            reason = (
                "Deterministic thermal rule selects moderate cooling within "
                "the validated policy band."
            )
        else:
            proposed = 25.0
            strategy = "policy_reduce_cooling"
            reason = (
                "Deterministic thermal rule raises the node target because "
                "the zone is below the validated policy band."
            )

        if (
            active_policy.energy_priority == Priority.HIGH
            and state.zone_temperature < high_threshold
        ):
            proposed = min(25.0, proposed + 1.0)
            strategy = "policy_energy_bias"
            reason = (
                "Deterministic energy-priority rule cautiously raises the "
                "node target while the zone remains thermally acceptable."
            )

        previous_action = controller_state.previous_action
        emergency = (
            state.zone_temperature
            >= active_policy.target_zone_temperature_c + 1.0
        )
        if (
            previous_action is not None
            and proposed
            != previous_action.supply_air_temperature_setpoint
            and controller_state.physical_action_hold_intervals_elapsed
            < active_policy.minimum_action_hold_intervals
            and not emergency
        ):
            return ControlAction(
                supply_air_temperature_setpoint=(
                    previous_action.supply_air_temperature_setpoint
                ),
                strategy="policy_minimum_hold",
                reason=(
                    "Deterministic controller holds the previous physical "
                    "action for the validated minimum hold interval."
                ),
            )

        return ControlAction(
            supply_air_temperature_setpoint=proposed,
            strategy=strategy,
            reason=reason,
        )

    @staticmethod
    def _high_threshold(policy: SupervisorPolicy) -> float:
        thermal_shift = {
            Priority.HIGH: 0.0,
            Priority.MEDIUM: 0.5,
            Priority.LOW: 1.0,
        }[policy.thermal_priority]
        energy_shift = {
            Priority.LOW: -0.5,
            Priority.MEDIUM: 0.0,
            Priority.HIGH: 0.5,
        }[policy.energy_priority]
        aggression_shift = {
            ControllerAggressiveness.AGGRESSIVE: -0.5,
            ControllerAggressiveness.NORMAL: 0.0,
            ControllerAggressiveness.CONSERVATIVE: 0.5,
        }[policy.controller_aggressiveness]
        return (
            policy.target_zone_temperature_c
            - 2.0
            + thermal_shift
            + energy_shift
            + aggression_shift
        )
