"""Prompt construction for supply-air temperature control."""

from __future__ import annotations

from controller.controller_state import ControllerState
from controller.state import BuildingState


def build_prompt(
    state: BuildingState,
    controller_state: ControllerState,
) -> str:
    """Build a deterministic prompt with physical semantics and trends."""

    previous_state = (
        controller_state.history[-1] if controller_state.history else None
    )
    hour_reference = _one_hour_reference(state, controller_state)
    previous_action = controller_state.previous_action

    return "\n".join(
        [
            "EnergyPlus Supervisory Control Task",
            "",
            "Control Variable",
            "",
            "You control the temperature setpoint of:",
            "MAIN COOLING COIL 1 OUTLET NODE",
            "",
            (
                "This is a cooling-coil outlet temperature setpoint, also "
                "described as a supply-air temperature target."
            ),
            "It is not a zone thermostat cooling setpoint.",
            "You are not directly setting the zone temperature.",
            "EnergyPlus calculates the resulting zone temperature and power use.",
            "",
            "Lower values generally provide colder supply air and stronger cooling.",
            "Higher values generally provide warmer supply air and reduced cooling.",
            "Avoid unnecessary setpoint changes and respect the previous action.",
            "",
            "Allowed range: 22.0 C to 25.0 C",
            "",
            "Current State",
            "",
            f"Simulation time: {state.sim_time}",
            f"Current zone temperature: {_format_celsius(state.zone_temperature)}",
            (
                "Previous zone temperature: "
                f"{_format_celsius(_value(previous_state, 'zone_temperature'))}"
            ),
            (
                "Zone temperature change over approximately one hour: "
                f"{_format_delta(state.zone_temperature, _value(hour_reference, 'zone_temperature'), 'C')}"
            ),
            (
                "Current node setpoint: "
                f"{_format_celsius(state.supply_air_temperature_setpoint)}"
            ),
            (
                "Measured supply-air temperature: "
                f"{_format_celsius(state.measured_supply_air_temperature)}"
            ),
            f"Outdoor temperature: {_format_celsius(state.outdoor_temperature)}",
            f"HVAC power: {_format_kw(state.hvac_power_kw)}",
            f"Facility power: {_format_kw(state.power_kw)}",
            f"Occupancy: {_format_optional_number(state.occupancy)}",
            f"PMV: {_format_optional_number(state.pmv)}",
            (
                "Facility power change over approximately one hour: "
                f"{_format_delta(state.power_kw, _value(hour_reference, 'power_kw'), 'kW')}"
            ),
            "",
            "Previous Validated Decision",
            "",
            (
                "Previous supply-air temperature setpoint: "
                f"{_format_celsius(previous_action.supply_air_temperature_setpoint if previous_action else None)}"
            ),
            (
                "Previous strategy: "
                f"{previous_action.strategy if previous_action else 'Unavailable'}"
            ),
            (
                "Previous reason: "
                f"{previous_action.reason if previous_action else 'Unavailable'}"
            ),
            (
                "Previous validation status: "
                f"{controller_state.previous_validation_status or 'Unavailable'}"
            ),
            "",
            "Required Response",
            "",
            "Return exactly one JSON object with exactly these fields:",
            (
                "- supply_air_temperature_setpoint: a finite number from "
                "22.0 through 25.0 C, chosen from the current state and trends."
            ),
            (
                "- strategy: a short non-empty string describing the action "
                "actually selected."
            ),
            (
                "- reason: a short non-empty explanation that references "
                "relevant state, trend, power, or the previous action and is "
                "consistent with the selected setpoint."
            ),
            "Do not return any other fields.",
            "",
            "Choose a state-dependent action.",
            "Do not copy a fixed default response or always return the same setpoint.",
            "Compare the current state with the previous validated decision.",
            "Use temperature trend and power trend when they are available.",
            "Hold the previous setpoint when no meaningful change is justified.",
            "Occupancy and PMV may be unavailable; do not invent them.",
            "",
            "Action and reason must agree:",
            (
                "- If the setpoint is lower than the previous setpoint, say "
                "that cooling is strengthened or the supply-air target is lowered."
            ),
            (
                "- If the setpoint is higher than the previous setpoint, say "
                "that cooling is reduced or the supply-air target is raised."
            ),
            "- If the setpoint is unchanged, justify holding it.",
            "",
            "Do not return cooling_setpoint or zone thermostat fields.",
            "Do not include prose, markdown, or code fences around the JSON.",
        ]
    )


def _one_hour_reference(
    state: BuildingState,
    controller_state: ControllerState,
) -> BuildingState | None:
    """Return the closest retained state at least one simulated hour old."""

    if not controller_state.history:
        return None
    default_duration = state.timestep_duration_hours
    elapsed = 0.0
    for candidate in reversed(controller_state.history):
        duration = candidate.timestep_duration_hours or default_duration
        if duration is None:
            return None
        elapsed += duration
        if elapsed >= 1.0 - 1e-9:
            return candidate
    return None


def _value(state: BuildingState | None, name: str) -> float | None:
    if state is None:
        return None
    value = getattr(state, name)
    return value if isinstance(value, (int, float)) else None


def _format_celsius(value: float | None) -> str:
    if value is None:
        return "Unavailable"
    return f"{value:.1f} C"


def _format_kw(value: float | None) -> str:
    if value is None:
        return "Unavailable"
    return f"{value:.3f} kW"


def _format_optional_number(value: float | None) -> str:
    if value is None:
        return "Unavailable"
    return f"{value:.3f}"


def _format_delta(
    current: float | None,
    previous: float | None,
    units: str,
) -> str:
    if current is None or previous is None:
        return "Unavailable"
    return f"{current - previous:+.3f} {units}"
