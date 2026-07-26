"""Rule-based controller for the cooling-coil outlet node target."""

from __future__ import annotations

from controller.action import ControlAction
from controller.controller_state import ControllerState
from controller.state import BuildingState


class RuleController:
    """Simple deterministic fallback with no EnergyPlus API dependency."""

    controller_type = "RuleController"
    uses_controller_state = True

    def decide(
        self,
        state: BuildingState,
        controller_state: ControllerState | None = None,
    ) -> ControlAction:
        """Lower the node target for more cooling; raise it for less cooling."""

        previous_temperature = None
        if controller_state is not None and controller_state.history:
            previous_temperature = controller_state.history[-1].zone_temperature
        temperature_rising = (
            previous_temperature is not None
            and state.zone_temperature - previous_temperature >= 0.2
        )

        if state.zone_temperature >= 30.0 or temperature_rising:
            return ControlAction(
                supply_air_temperature_setpoint=22.0,
                strategy="increase_cooling",
                reason=(
                    "Lower the cooling-coil outlet target because the zone is "
                    "hot or rising."
                ),
            )

        if state.zone_temperature >= 27.0:
            return ControlAction(
                supply_air_temperature_setpoint=23.0,
                strategy="moderate_cooling",
                reason=(
                    "Use a moderate cooling-coil outlet target while the zone "
                    "remains above the control threshold."
                ),
            )

        return ControlAction(
            supply_air_temperature_setpoint=25.0,
            strategy="reduce_cooling",
            reason=(
                "Raise the cooling-coil outlet target to reduce cooling demand "
                "while zone temperature is sufficiently controlled."
            ),
        )
