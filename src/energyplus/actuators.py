"""EnergyPlus actuator access for the Runtime API control loop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from controller.action import ControlAction
from energyplus.config import (
    ActuatorControlMode,
    SCHEDULE_COOLING_ACTUATOR,
    SCHEDULE_HEATING_ACTUATOR,
    SUPPLY_NODE_COOLING_ACTUATOR,
    ZONE_COOLING_ACTUATOR,
    ZONE_HEATING_ACTUATOR,
)


@dataclass(frozen=True)
class ActuatorSpec:
    """Exact component/control/key tuple exposed by EnergyPlus."""

    component_type: str
    control_type: str
    key: str


class ActuatorWriter:
    """Resolves actuator handles and applies validated ``ControlAction`` values.

    All ``set_actuator_value`` calls live here so controller logic cannot write
    directly to EnergyPlus.
    """

    def __init__(
        self,
        api: Any,
        control_mode: ActuatorControlMode = ActuatorControlMode.SCHEDULE,
        legacy_heating_setpoint_c: float = 18.0,
    ) -> None:
        self.api = api
        self.control_mode = control_mode
        self.legacy_heating_setpoint_c = legacy_heating_setpoint_c
        self.handles_initialized = False
        self.control_setpoint_handle = -1
        self.heating_setpoint_handle = -1
        self.cooling_spec, self.heating_spec = self._select_specs(control_mode)

    def initialize_handles(self, sim_state: Any) -> None:
        """Resolve actuator handles once EnergyPlus API data is available."""

        if self.handles_initialized:
            return

        if not self.api.exchange.api_data_fully_ready(sim_state):
            return

        self.control_setpoint_handle = self.api.exchange.get_actuator_handle(
            sim_state,
            self.cooling_spec.component_type,
            self.cooling_spec.control_type,
            self.cooling_spec.key,
        )
        self._print_actuator_status(
            self.cooling_spec.component_type,
            self.cooling_spec.control_type,
            self.cooling_spec.key,
            self.control_setpoint_handle,
        )

        self.heating_setpoint_handle = self.api.exchange.get_actuator_handle(
            sim_state,
            self.heating_spec.component_type,
            self.heating_spec.control_type,
            self.heating_spec.key,
        )
        self._print_actuator_status(
            self.heating_spec.component_type,
            self.heating_spec.control_type,
            self.heating_spec.key,
            self.heating_setpoint_handle,
        )

        self.handles_initialized = True

    def apply(self, sim_state: Any, action: ControlAction | None) -> None:
        """Apply the previously computed action at begin zone timestep."""

        if action is None:
            return

        self.initialize_handles(sim_state)

        if not self.handles_initialized:
            return

        if self.control_mode != ActuatorControlMode.SUPPLY_NODE_SETPOINT:
            self._write_control_setpoint(
                sim_state,
                action.supply_air_temperature_setpoint,
            )

        if self.heating_setpoint_handle != -1:
            self.api.exchange.set_actuator_value(
                sim_state,
                self.heating_setpoint_handle,
                self.legacy_heating_setpoint_c,
            )

    def apply_after_hvac_managers(
        self,
        sim_state: Any,
        action: ControlAction | None,
    ) -> None:
        """Apply a node setpoint after EnergyPlus setpoint managers run.

        ``SetpointManager:MixedAir`` writes the DX coil outlet-node target
        during HVAC manager processing. The Python override must therefore be
        refreshed at this later callback to affect the current system timestep.
        """

        if (
            action is None
            or self.control_mode != ActuatorControlMode.SUPPLY_NODE_SETPOINT
        ):
            return

        self.initialize_handles(sim_state)
        if self.handles_initialized:
            self._write_control_setpoint(
                sim_state,
                action.supply_air_temperature_setpoint,
            )

    def _write_control_setpoint(self, sim_state: Any, value: float) -> None:
        if self.control_setpoint_handle == -1:
            return
        self.api.exchange.set_actuator_value(
            sim_state,
            self.control_setpoint_handle,
            value,
        )
        readback = self.api.exchange.get_actuator_value(
            sim_state,
            self.control_setpoint_handle,
        )
        print(
            f"{self.api.exchange.current_time(sim_state):.2f} h | "
            f"Writing {self.cooling_spec.key} = {value:.1f} C "
            f"(readback={readback:.1f} C)"
        )

    @staticmethod
    def _select_specs(
        control_mode: ActuatorControlMode,
    ) -> tuple[ActuatorSpec, ActuatorSpec]:
        if control_mode == ActuatorControlMode.ZONE_SETPOINT:
            cooling = ZONE_COOLING_ACTUATOR
            heating = ZONE_HEATING_ACTUATOR
        elif control_mode == ActuatorControlMode.SUPPLY_NODE_SETPOINT:
            cooling = SUPPLY_NODE_COOLING_ACTUATOR
            heating = SCHEDULE_HEATING_ACTUATOR
        else:
            cooling = SCHEDULE_COOLING_ACTUATOR
            heating = SCHEDULE_HEATING_ACTUATOR
        return ActuatorSpec(*cooling), ActuatorSpec(*heating)

    @staticmethod
    def _print_actuator_status(
        component_type: str,
        control_type: str,
        key: str,
        handle: int,
    ) -> None:
        if handle == -1:
            print(
                f"[EnergyPlus] Could not find actuator '{component_type}' / "
                f"'{control_type}' / '{key}'."
            )
            return

        print(f"[EnergyPlus] Resolved actuator handle for '{key}' -> {handle}")
