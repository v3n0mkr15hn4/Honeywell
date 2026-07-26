"""Processed facts used by bounded supervisory policy selection."""

from __future__ import annotations

from dataclasses import dataclass

from controller.supervisor_policy import SupervisorPolicy


@dataclass(frozen=True)
class StateSummary:
    """Deterministic state features; no raw EnergyPlus history is exposed."""

    current_zone_temperature_c: float
    target_zone_temperature_c: float
    zone_temperature_change_4h_c: float | None
    zone_trend: str
    thermal_state: str
    current_hvac_power_w: float | None
    current_facility_power_w: float | None
    facility_power_change_4h_w: float | None
    power_trend: str
    outdoor_temperature_change_4h_c: float | None
    outdoor_trend: str
    current_policy: SupervisorPolicy
    current_policy_age_hours: float
    current_mode: str
    history_sufficient: bool
    occupancy_available: bool
    pmv_available: bool
    high_power: bool
    contradictory_data: bool = False
