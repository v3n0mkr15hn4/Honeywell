from __future__ import annotations

from controller.controller_state import ControllerState
from controller.state_summary import StateSummary
from controller.supervisor_policy import (
    ControllerAggressiveness,
    Priority,
    SupervisorPolicy,
    default_supervisor_policy,
)
from test_support import make_state


def make_summary(**overrides: object) -> StateSummary:
    current = overrides.pop("current_policy", default_supervisor_policy())
    values: dict[str, object] = {
        "current_zone_temperature_c": 32.0,
        "target_zone_temperature_c": 32.0,
        "zone_temperature_change_4h_c": 0.0,
        "zone_trend": "stable",
        "thermal_state": "near_target",
        "current_hvac_power_w": 12_000.0,
        "current_facility_power_w": 80_000.0,
        "facility_power_change_4h_w": 0.0,
        "power_trend": "stable",
        "outdoor_temperature_change_4h_c": 0.0,
        "outdoor_trend": "stable",
        "current_policy": current,
        "current_policy_age_hours": 3.0,
        "current_mode": current.strategy,
        "history_sufficient": True,
        "occupancy_available": False,
        "pmv_available": False,
        "high_power": False,
        "contradictory_data": False,
    }
    values.update(overrides)
    return StateSummary(**values)  # type: ignore[arg-type]


def energy_policy() -> SupervisorPolicy:
    return SupervisorPolicy(
        thermal_priority=Priority.MEDIUM,
        energy_priority=Priority.HIGH,
        controller_aggressiveness=ControllerAggressiveness.CONSERVATIVE,
        target_zone_temperature_c=33.0,
        minimum_action_hold_intervals=4,
        policy_duration_hours=4,
        strategy="energy_saving",
        reason="Previously validated energy policy.",
    )


def ranker_controller_state(
    policy: SupervisorPolicy | None = None,
) -> ControllerState:
    controller_state = ControllerState(
        current_supervisor_policy=policy or default_supervisor_policy(),
        supervisor_policy_age_hours=3.0,
    )
    controller_state.append_building_state(
        make_state(
            timestep=1,
            zone_temperature=32.0,
            power_kw=120.0,
            hvac_power_kw=22.0,
            outdoor_temperature=30.0,
            timestep_duration_hours=1.0,
        )
    )
    controller_state.append_building_state(
        make_state(
            timestep=2,
            zone_temperature=32.0,
            power_kw=122.0,
            hvac_power_kw=22.0,
            outdoor_temperature=30.0,
            timestep_duration_hours=1.0,
        )
    )
    return controller_state
