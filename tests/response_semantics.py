"""Deterministic semantic checks shared by local LLM diagnostics."""

from __future__ import annotations

import re
from typing import Any


def reason_directions(reason: str) -> set[str]:
    """Infer actuator directions explicitly claimed by a response reason."""

    text = normalize_text(reason)
    patterns = {
        "lower": (
            r"\b(?:lower|lowered|lowering)\b.{0,35}\b(?:setpoint|target|supply)",
            r"\b(?:setpoint|target|supply)\b.{0,35}\b(?:lower|lowered|lowering)",
            r"\bcolder\s+(?:supply|air)",
            r"\b(?:strengthen|strengthened|strengthening|increase|increased|more)"
            r"\b.{0,20}\bcooling\b",
        ),
        "higher": (
            r"\b(?:raise|raised|raising|higher)\b.{0,35}\b(?:setpoint|target|supply)",
            r"\b(?:setpoint|target|supply)\b.{0,35}\b(?:raise|raised|raising|higher)",
            r"\bwarmer\s+(?:supply|air)",
            r"\b(?:reduce|reduced|reducing|weaken|weakened|less)"
            r"\b.{0,20}\bcooling\b",
        ),
        "hold": (
            r"\b(?:hold|holding|maintain|maintained|maintaining|unchanged|"
            r"no (?:meaningful )?change|keep|keeping|retain|retained|"
            r"retaining)\b",
        ),
    }
    return {
        direction
        for direction, expressions in patterns.items()
        if any(re.search(expression, text) for expression in expressions)
    }


def state_reference_present(reason: str, case: Any) -> bool:
    """Return whether a reason refers to an actual state signal or trend."""

    text = normalize_text(reason)
    state_patterns = (
        r"\bzone(?: temperature)?\b",
        r"\b(?:temperature|power)\s+trend\b",
        r"\b(?:rising|falling|stable|overheating|hot)\b",
        r"\b(?:facility|hvac)\s+power\b",
        r"\b(?:thermal|cooling)\s+(?:load|demand)\b",
        r"\boutdoor\s+temperature\b",
    )
    if any(re.search(pattern, text) for pattern in state_patterns):
        return True
    relevant_values = (
        case.zone_temperature_c,
        case.outdoor_temperature_c,
        case.facility_power_kw,
        case.hvac_power_kw,
    )
    return any(
        re.search(rf"(?<!\d){value:g}(?:\.0)?(?!\d)", text)
        for value in relevant_values
    )


def previous_action_reference_present(reason: str, case: Any) -> bool:
    """Return whether a reason acknowledges the previous actuator action."""

    text = normalize_text(reason)
    if re.search(
        r"\b(?:previous|prior|current)\s+(?:action|setpoint|target|decision)\b",
        text,
    ):
        return True
    if re.search(
        r"\b(?:hold|holding|maintain|maintained|maintaining|unchanged|"
        r"no (?:meaningful )?change|keep|keeping|retain|retained|"
        r"retaining|lower limit|upper limit|minimum|maximum)\b",
        text,
    ):
        return True
    value = case.previous_setpoint_c
    return bool(re.search(rf"(?<!\d){value:g}(?:\.0)?\s*(?:c|°c)?(?!\d)", text))


def fabricates_unavailable_data(
    reason: str,
    occupancy: float | None,
    pmv: float | None,
) -> bool:
    """Detect unsupported occupancy or PMV claims when those inputs are absent."""

    text = normalize_text(reason)
    unavailable_qualified = bool(
        re.search(r"\b(?:unavailable|unknown|not available|not provided)\b", text)
    )
    occupancy_claim = bool(
        re.search(r"\b(?:occupancy|occupied|unoccupied|occupants?)\b", text)
    )
    pmv_claim = bool(re.search(r"\bpmv\b", text))
    return (
        occupancy is None and occupancy_claim and not unavailable_qualified
    ) or (pmv is None and pmv_claim and not unavailable_qualified)


def generic_reason(reason: str, state_reference: bool) -> bool:
    """Identify empty, placeholder, or state-free explanations."""

    text = normalize_text(reason)
    if not text:
        return True
    known_placeholders = {
        "short physical explanation.",
        "based on current conditions.",
        "adjusted based on current conditions.",
    }
    return text in known_placeholders or len(text.split()) < 4 or not state_reference


def normalize_text(value: str) -> str:
    """Normalize generated text for deterministic repetition comparisons."""

    return " ".join(value.strip().lower().split())
