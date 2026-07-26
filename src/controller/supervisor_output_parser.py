"""Strict parser for policy-only supervisory LLM responses."""

from __future__ import annotations

import json
import math
from typing import Any

from controller.supervisor_policy import (
    ControllerAggressiveness,
    Priority,
    SupervisorPolicy,
)


class SupervisorOutputParserError(ValueError):
    """Raised when a supervisory response violates the policy contract."""


SUPERVISOR_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "thermal_priority": {
            "type": "string",
            "enum": [item.value for item in Priority],
        },
        "energy_priority": {
            "type": "string",
            "enum": [item.value for item in Priority],
        },
        "controller_aggressiveness": {
            "type": "string",
            "enum": [item.value for item in ControllerAggressiveness],
        },
        "target_zone_temperature_c": {"type": "number"},
        "minimum_action_hold_intervals": {"type": "integer"},
        "policy_duration_hours": {"type": "integer"},
        "strategy": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": [
        "thermal_priority",
        "energy_priority",
        "controller_aggressiveness",
        "target_zone_temperature_c",
        "minimum_action_hold_intervals",
        "policy_duration_hours",
        "strategy",
        "reason",
    ],
    "additionalProperties": False,
}
REQUIRED_KEYS = frozenset(SUPERVISOR_RESPONSE_SCHEMA["required"])


def parse_supervisor_response(text: str) -> SupervisorPolicy:
    """Decode exact policy JSON without applying range corrections."""

    try:
        data = json.loads(
            text,
            parse_constant=lambda value: (_raise_nonfinite(value)),
        )
    except (json.JSONDecodeError, SupervisorOutputParserError) as exc:
        raise SupervisorOutputParserError(
            f"Supervisor response is not strict JSON: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise SupervisorOutputParserError(
            "Supervisor response JSON must be an object."
        )
    missing = REQUIRED_KEYS - data.keys()
    extra = data.keys() - REQUIRED_KEYS
    if missing:
        raise SupervisorOutputParserError(
            "Supervisor response missing required keys: "
            + ", ".join(sorted(missing))
        )
    if extra:
        raise SupervisorOutputParserError(
            "Supervisor response has unexpected keys: "
            + ", ".join(sorted(extra))
        )

    return SupervisorPolicy(
        thermal_priority=_enum(
            data["thermal_priority"],
            Priority,
            "thermal_priority",
        ),
        energy_priority=_enum(
            data["energy_priority"],
            Priority,
            "energy_priority",
        ),
        controller_aggressiveness=_enum(
            data["controller_aggressiveness"],
            ControllerAggressiveness,
            "controller_aggressiveness",
        ),
        target_zone_temperature_c=_number(
            data["target_zone_temperature_c"],
            "target_zone_temperature_c",
        ),
        minimum_action_hold_intervals=_integer(
            data["minimum_action_hold_intervals"],
            "minimum_action_hold_intervals",
        ),
        policy_duration_hours=_integer(
            data["policy_duration_hours"],
            "policy_duration_hours",
        ),
        strategy=_text(data["strategy"], "strategy"),
        reason=_text(data["reason"], "reason"),
    )


def _enum(value: Any, enum_type: type, field: str) -> Any:
    if not isinstance(value, str):
        raise SupervisorOutputParserError(f"{field} must be a string.")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise SupervisorOutputParserError(
            f"{field} has unsupported value: {value}"
        ) from exc


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SupervisorOutputParserError(f"{field} must be numeric.")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise SupervisorOutputParserError(f"{field} must be finite.")
    return parsed


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SupervisorOutputParserError(f"{field} must be an integer.")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SupervisorOutputParserError(
            f"{field} must be a non-empty string."
        )
    return value.strip()


def _raise_nonfinite(value: str) -> None:
    raise SupervisorOutputParserError(f"Non-finite JSON number: {value}")
