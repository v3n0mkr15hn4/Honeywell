from __future__ import annotations

from controller.state import BuildingState


def make_state(**overrides: object) -> BuildingState:
    values: dict[str, object] = {
        "sim_time": "2026-01-01 1.00 h",
        "timestep": 1,
        "zone_temperature": 30.0,
        "outdoor_temperature": 35.0,
        "occupancy": None,
        "pmv": None,
        "power_kw": 80.0,
        "hvac_power_kw": 10.0,
        "heating_setpoint": 18.0,
        "supply_air_temperature_setpoint": 23.0,
        "cooling_coil_power_kw": 6.0,
        "timestep_duration_hours": 1 / 6,
        "measured_supply_air_temperature": 23.1,
        "zone_thermostat_cooling_setpoint": 31.0,
    }
    values.update(overrides)
    return BuildingState(**values)  # type: ignore[arg-type]
