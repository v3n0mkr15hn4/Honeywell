"""Building state passed into controller decision makers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BuildingState:
    """A complete snapshot of the building at one control timestep.

    The controller layer receives this object instead of talking directly to
    EnergyPlus. Fields that are unavailable in the current IDF can remain
    ``None`` while preserving the interface for future models.
    """

    sim_time: str
    timestep: int
    zone_temperature: float
    outdoor_temperature: float | None
    occupancy: float | None
    pmv: float | None
    power_kw: float | None
    hvac_power_kw: float | None
    heating_setpoint: float | None
    supply_air_temperature_setpoint: float | None
    cooling_coil_power_kw: float | None
    timestep_duration_hours: float | None = None
    measured_supply_air_temperature: float | None = None
    zone_thermostat_cooling_setpoint: float | None = None
    minimum_supply_air_setpoint_c: float = 22.0
    maximum_supply_air_setpoint_c: float = 25.0

    @property
    def cooling_setpoint(self) -> float | None:
        """Deprecated alias for the active supply-air node setpoint."""

        return self.supply_air_temperature_setpoint

    @property
    def cooling_coil_outlet_setpoint(self) -> float | None:
        """Compatibility alias with physically correct meaning."""

        return self.supply_air_temperature_setpoint

    @property
    def cooling_coil_outlet_temperature(self) -> float | None:
        """Compatibility alias for measured supply-air temperature."""

        return self.measured_supply_air_temperature
