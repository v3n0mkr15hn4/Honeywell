"""Prompt construction for low-frequency supervisory policy."""

from __future__ import annotations

import statistics
from typing import Any, Iterable

from controller.controller_state import ControllerState
from controller.state import BuildingState
from controller.supervisor_policy import SupervisorPolicy


def build_policy_prompt(
    current_state: BuildingState,
    controller_state: ControllerState,
    metrics_snapshot: dict[str, Any],
    current_policy: SupervisorPolicy,
) -> str:
    """Build a compact policy-only prompt from bounded state history."""

    history = list(controller_state.history)
    states = history + [current_state]
    zone_values = _finite_values(
        state.zone_temperature for state in states
    )
    facility_values = _finite_values(state.power_kw for state in states)
    hvac_values = _finite_values(state.hvac_power_kw for state in states)
    outdoor_values = _finite_values(
        state.outdoor_temperature for state in states
    )
    oldest = history[0] if history else None

    return "\n".join(
        [
            "EnergyPlus Supervisory Policy Task",
            "",
            "Role and Authority",
            (
                "You recommend bounded high-level policy only. You do not "
                "control an actuator or choose a physical setpoint."
            ),
            (
                "A deterministic RuleController converts validated policy "
                "into every physical ControlAction."
            ),
            (
                "Every physical action still passes through SafetyValidator "
                "before ActuatorWriter."
            ),
            (
                "The controlled node is MAIN COOLING COIL 1 OUTLET NODE. "
                "A lower node setpoint means stronger cooling, but you must "
                "not choose or return that setpoint."
            ),
            (
                "The policy remains active for several hours. Avoid "
                "unnecessary policy changes."
            ),
            "",
            "Current and Recent State",
            f"Simulation time: {current_state.sim_time}",
            (
                "Current zone temperature: "
                f"{_number(current_state.zone_temperature, 'C')}"
            ),
            f"Recent zone minimum: {_minimum(zone_values, 'C')}",
            f"Recent zone maximum: {_maximum(zone_values, 'C')}",
            f"Recent zone average: {_average(zone_values, 'C')}",
            (
                "Zone temperature trend across retained history: "
                f"{_trend(current_state.zone_temperature, _value(oldest, 'zone_temperature'), 'C')}"
            ),
            f"Current HVAC power: {_number(current_state.hvac_power_kw, 'kW')}",
            f"Recent HVAC power average: {_average(hvac_values, 'kW')}",
            (
                "Current facility power: "
                f"{_number(current_state.power_kw, 'kW')}"
            ),
            (
                "Recent facility power average: "
                f"{_average(facility_values, 'kW')}"
            ),
            (
                "Facility power trend across retained history: "
                f"{_trend(current_state.power_kw, _value(oldest, 'power_kw'), 'kW')}"
            ),
            (
                "Outdoor temperature trend across retained history: "
                f"{_trend(current_state.outdoor_temperature, _value(oldest, 'outdoor_temperature'), 'C')}"
            ),
            (
                "Current physical supply-air setpoint: "
                f"{_number(current_state.supply_air_temperature_setpoint, 'C')}"
            ),
            f"Recent outdoor temperature average: {_average(outdoor_values, 'C')}",
            "Occupancy: Unavailable" if current_state.occupancy is None else (
                f"Occupancy: {current_state.occupancy:.3f}"
            ),
            "PMV: Unavailable" if current_state.pmv is None else (
                f"PMV: {current_state.pmv:.3f}"
            ),
            "",
            "Run Metrics",
            (
                "Physical actuator changes: "
                f"{metrics_snapshot.get('physical_actuator_changes', 0)}"
            ),
            (
                "Physical safety corrections: "
                f"{metrics_snapshot.get('physical_safety_corrections', 0)}"
            ),
            (
                "Previous supervisory fallbacks: "
                f"{metrics_snapshot.get('supervisory_fallbacks', 0)}"
            ),
            "",
            "Current Validated Policy",
            f"Thermal priority: {current_policy.thermal_priority.value}",
            f"Energy priority: {current_policy.energy_priority.value}",
            (
                "Controller aggressiveness: "
                f"{current_policy.controller_aggressiveness.value}"
            ),
            (
                "Zone temperature target: "
                f"{current_policy.target_zone_temperature_c:.1f} C"
            ),
            (
                "Minimum physical-action hold intervals: "
                f"{current_policy.minimum_action_hold_intervals}"
            ),
            f"Policy duration: {current_policy.policy_duration_hours} hours",
            f"Policy strategy: {current_policy.strategy}",
            (
                "Policy age: "
                f"{controller_state.supervisor_policy_age_hours:.3f} hours"
            ),
            "",
            "Required JSON Contract",
            "Return exactly one JSON object with exactly these fields:",
            "- thermal_priority: low, medium, or high",
            "- energy_priority: low, medium, or high",
            (
                "- controller_aggressiveness: conservative, normal, "
                "or aggressive"
            ),
            (
                "- target_zone_temperature_c: finite zone thermal target "
                "within configured policy limits"
            ),
            (
                "- minimum_action_hold_intervals: integer within configured "
                "policy limits"
            ),
            (
                "- policy_duration_hours: integer within configured policy "
                "limits"
            ),
            "- strategy: short non-empty policy description",
            (
                "- reason: short non-empty explanation referencing relevant "
                "state, history, power, or current policy"
            ),
            "",
            (
                "Never return supply_air_temperature_setpoint, "
                "cooling_setpoint, heating_setpoint, an actuator key, or a "
                "callback name."
            ),
            "Return JSON only, without markdown, prose, or code fences.",
        ]
    )


def _finite_values(values: Iterable[float | None]) -> list[float]:
    return [float(value) for value in values if value is not None]


def _value(state: BuildingState | None, name: str) -> float | None:
    if state is None:
        return None
    value = getattr(state, name)
    return float(value) if value is not None else None


def _number(value: float | None, units: str) -> str:
    return "Unavailable" if value is None else f"{value:.3f} {units}"


def _minimum(values: list[float], units: str) -> str:
    return "Unavailable" if not values else f"{min(values):.3f} {units}"


def _maximum(values: list[float], units: str) -> str:
    return "Unavailable" if not values else f"{max(values):.3f} {units}"


def _average(values: list[float], units: str) -> str:
    return (
        "Unavailable"
        if not values
        else f"{statistics.mean(values):.3f} {units}"
    )


def _trend(
    current: float | None,
    previous: float | None,
    units: str,
) -> str:
    if current is None or previous is None:
        return "Unavailable"
    return f"{current - previous:+.3f} {units}"
