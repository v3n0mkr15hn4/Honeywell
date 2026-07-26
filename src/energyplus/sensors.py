"""EnergyPlus sensor access for the Runtime API control loop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from controller.state import BuildingState
from energyplus.config import (
    ActuatorControlMode,
    SUPPLY_NODE_MAX_SETPOINT_C,
    SUPPLY_NODE_MIN_SETPOINT_C,
    ZONE_NAME,
)


@dataclass(frozen=True)
class VariableSpec:
    """Name/key pair used by EnergyPlus to identify an output variable."""

    name: str
    key: str
    required: bool = False


class SensorReader:
    """Requests variables, resolves handles, and builds ``BuildingState``.

    This is the only component that reads EnergyPlus output variables. The
    controller receives the resulting dataclass and remains API-independent.
    """

    ZONE_TEMPERATURE = "zone_temperature"
    OUTDOOR_TEMPERATURE = "outdoor_temperature"
    COOLING_COIL_POWER = "cooling_coil_power"
    FACILITY_POWER = "facility_power"
    HVAC_POWER = "hvac_power"
    HEATING_SETPOINT = "heating_setpoint"
    ZONE_THERMOSTAT_COOLING_SETPOINT = "zone_thermostat_cooling_setpoint"
    COOLING_COIL_OUTLET_TEMPERATURE = "cooling_coil_outlet_temperature"
    COOLING_COIL_OUTLET_SETPOINT = "cooling_coil_outlet_setpoint"

    def __init__(
        self,
        api: Any,
        control_mode: ActuatorControlMode = ActuatorControlMode.SUPPLY_NODE_SETPOINT,
    ) -> None:
        self.api = api
        self.control_mode = control_mode
        self.handles_initialized = False
        self.handles: dict[str, int] = {}
        self.variables: dict[str, VariableSpec] = {
            self.ZONE_TEMPERATURE: VariableSpec(
                "Zone Mean Air Temperature",
                ZONE_NAME,
                required=True,
            ),
            self.OUTDOOR_TEMPERATURE: VariableSpec(
                "Site Outdoor Air Drybulb Temperature",
                "Environment",
            ),
            self.COOLING_COIL_POWER: VariableSpec(
                "Cooling Coil Electricity Rate",
                "Main Cooling Coil 1",
                required=True,
            ),
            self.FACILITY_POWER: VariableSpec(
                "Facility Total Electricity Demand Rate",
                "Whole Building",
            ),
            self.HVAC_POWER: VariableSpec(
                "Facility Total HVAC Electricity Demand Rate",
                "Whole Building",
            ),
            self.HEATING_SETPOINT: VariableSpec(
                "Zone Thermostat Heating Setpoint Temperature",
                ZONE_NAME,
            ),
            self.ZONE_THERMOSTAT_COOLING_SETPOINT: VariableSpec(
                "Zone Thermostat Cooling Setpoint Temperature",
                ZONE_NAME,
            ),
            self.COOLING_COIL_OUTLET_TEMPERATURE: VariableSpec(
                "System Node Temperature",
                "Main Cooling Coil 1 Outlet Node",
            ),
            self.COOLING_COIL_OUTLET_SETPOINT: VariableSpec(
                "System Node Setpoint Temperature",
                "Main Cooling Coil 1 Outlet Node",
            ),
        }

    def request_variables(self, sim_state: Any) -> None:
        """Request all configured output variables before the simulation starts."""

        for spec in self.variables.values():
            self.api.exchange.request_variable(sim_state, spec.name, spec.key)

    def initialize_handles(self, sim_state: Any) -> None:
        """Resolve variable handles after EnergyPlus exposes API data."""

        if self.handles_initialized:
            return

        if not self.api.exchange.api_data_fully_ready(sim_state):
            return

        for field_name, spec in self.variables.items():
            handle = self.api.exchange.get_variable_handle(
                sim_state,
                spec.name,
                spec.key,
            )
            self.handles[field_name] = handle
            if handle == -1:
                level = "required" if spec.required else "optional"
                print(
                    f"[EnergyPlus] Could not find {level} variable "
                    f"'{spec.name}' for key '{spec.key}'."
                )
                continue

            print(
                f"[EnergyPlus] Resolved variable handle for "
                f"'{spec.key}: {spec.name}' -> {handle}"
            )

        self.handles_initialized = True

    def read(self, sim_state: Any, timestep: int) -> BuildingState | None:
        """Read live EnergyPlus values and return one building snapshot."""

        self.initialize_handles(sim_state)

        if not self.handles_initialized:
            return None

        if self.api.exchange.warmup_flag(sim_state):
            return None

        zone_temperature = self._read_required(self.ZONE_TEMPERATURE, sim_state)
        if zone_temperature is None:
            return None

        cooling_coil_power_w = self._read_optional(self.COOLING_COIL_POWER, sim_state)
        facility_power_w = self._read_optional(self.FACILITY_POWER, sim_state)
        hvac_power_w = self._read_optional(self.HVAC_POWER, sim_state)
        thermostat_cooling_setpoint = self._read_optional(
            self.ZONE_THERMOSTAT_COOLING_SETPOINT,
            sim_state,
        )
        coil_outlet_setpoint = self._read_optional(
            self.COOLING_COIL_OUTLET_SETPOINT,
            sim_state,
        )
        return BuildingState(
            sim_time=self.format_simulation_clock(sim_state),
            timestep=timestep,
            zone_temperature=zone_temperature,
            outdoor_temperature=self._read_optional(
                self.OUTDOOR_TEMPERATURE,
                sim_state,
            ),
            occupancy=None,
            pmv=None,
            power_kw=self._watts_to_kw(facility_power_w),
            hvac_power_kw=self._watts_to_kw(hvac_power_w),
            heating_setpoint=self._read_optional(self.HEATING_SETPOINT, sim_state),
            # This field always represents the physical coil outlet node. Legacy
            # actuator modes remain available for diagnostics but do not change
            # the meaning of the controller's supply-air state.
            supply_air_temperature_setpoint=coil_outlet_setpoint,
            cooling_coil_power_kw=self._watts_to_kw(cooling_coil_power_w),
            timestep_duration_hours=self._zone_timestep_hours(sim_state),
            measured_supply_air_temperature=self._read_optional(
                self.COOLING_COIL_OUTLET_TEMPERATURE,
                sim_state,
            ),
            zone_thermostat_cooling_setpoint=thermostat_cooling_setpoint,
            minimum_supply_air_setpoint_c=SUPPLY_NODE_MIN_SETPOINT_C,
            maximum_supply_air_setpoint_c=SUPPLY_NODE_MAX_SETPOINT_C,
        )

    def format_simulation_clock(self, sim_state: Any) -> str:
        """Build a readable date/time string from EnergyPlus time APIs."""

        year = self.api.exchange.year(sim_state)
        month = self.api.exchange.month(sim_state)
        day = self.api.exchange.day_of_month(sim_state)
        current_time_hours = self.api.exchange.current_time(sim_state)
        zone_step_number = self.api.exchange.zone_time_step_number(sim_state)

        return (
            f"{year:04d}-{month:02d}-{day:02d} "
            f"{current_time_hours:.2f} h "
            f"(zone timestep #{zone_step_number})"
        )

    def _read_required(self, field_name: str, sim_state: Any) -> float | None:
        handle = self.handles.get(field_name, -1)
        if handle == -1:
            return None
        return self.api.exchange.get_variable_value(sim_state, handle)

    def _read_optional(self, field_name: str, sim_state: Any) -> float | None:
        handle = self.handles.get(field_name, -1)
        if handle == -1:
            return None
        return self.api.exchange.get_variable_value(sim_state, handle)

    @staticmethod
    def _watts_to_kw(value_w: float | None) -> float | None:
        if value_w is None:
            return None
        return value_w / 1000.0

    def _zone_timestep_hours(self, sim_state: Any) -> float | None:
        timestep = getattr(self.api.exchange, "zone_time_step", None)
        if timestep is None:
            return None
        return timestep(sim_state)
