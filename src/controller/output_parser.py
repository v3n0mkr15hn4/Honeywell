"""Strict JSON parser for LLM control responses."""

from __future__ import annotations

import json
import math
from typing import Any

from controller.action import ControlAction


class OutputParserError(ValueError):
    """Raised when the LLM response cannot be converted to ``ControlAction``."""


def parse_response(text: str) -> ControlAction:
    """Parse a JSON-only LLM response into a ``ControlAction``."""

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OutputParserError(f"LLM response is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise OutputParserError("LLM response JSON must be an object.")

    required_keys = {
        "supply_air_temperature_setpoint",
        "strategy",
        "reason",
    }
    missing_keys = required_keys - data.keys()
    if missing_keys:
        missing = ", ".join(sorted(missing_keys))
        raise OutputParserError(f"LLM response missing required keys: {missing}")

    unexpected_keys = data.keys() - required_keys
    if unexpected_keys:
        unexpected = ", ".join(sorted(unexpected_keys))
        raise OutputParserError(f"LLM response has unexpected keys: {unexpected}")

    supply_air_setpoint = _parse_number(
        data["supply_air_temperature_setpoint"],
        "supply_air_temperature_setpoint",
    )
    strategy = _parse_text(data["strategy"], "strategy")
    reason = _parse_text(data["reason"], "reason")

    return ControlAction(
        supply_air_temperature_setpoint=supply_air_setpoint,
        strategy=strategy,
        reason=reason,
    )


def _parse_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool):
        raise OutputParserError(f"{field_name} must be numeric.")
    if not isinstance(value, (int, float)):
        raise OutputParserError(f"{field_name} must be numeric.")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise OutputParserError(f"{field_name} must be finite.")
    return parsed


def _parse_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OutputParserError(f"{field_name} must be a non-empty string.")
    return value.strip()
