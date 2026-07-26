"""Pure calculations and safe JSON parsing for dashboard views."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd


def boolean_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(False, index=frame.index, dtype=bool)
    return (
        frame[column]
        .astype("string")
        .str.strip()
        .str.casefold()
        .isin({"true", "1", "yes"})
    )


def safe_json_list(value: object) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None or pd.isna(value):
        return []
    try:
        parsed = json.loads(str(value))
    except (json.JSONDecodeError, TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def parse_candidate_summaries(value: object) -> list[dict[str, Any]]:
    return [
        item
        for item in safe_json_list(value)
        if isinstance(item, dict)
    ]


def watts_to_kilowatts(values: pd.Series) -> pd.Series:
    return pd.to_numeric(values, errors="coerce") / 1000.0


def operational_target_violation_rate(frame: pd.DataFrame) -> float | None:
    required = {"indoor_temp_c", "target_zone_temperature_c"}
    if not required.issubset(frame.columns):
        return None
    zone = pd.to_numeric(frame["indoor_temp_c"], errors="coerce")
    target = pd.to_numeric(
        frame["target_zone_temperature_c"],
        errors="coerce",
    )
    valid = zone.notna() & target.notna()
    if not valid.any():
        return None
    return float((zone[valid] > target[valid]).mean())


def cumulative_metrics(
    frame: pd.DataFrame,
    warning_count: int | None = None,
    severe_error_count: int | None = None,
) -> dict[str, int | float | None]:
    if frame.empty:
        return _empty_metrics(warning_count, severe_error_count)

    llm_calls = boolean_series(frame, "llm_ranker_called")
    completed = boolean_series(frame, "llm_request_completed")
    fallbacks = boolean_series(frame, "deterministic_fallback_used")
    safety = boolean_series(frame, "safety_corrected")
    strict = (
        frame.get(
            "ranking_validation_status",
            pd.Series("", index=frame.index),
        )
        .astype("string")
        .str.casefold()
        .str.contains("valid candidate ranking", na=False)
    )
    invalid = boolean_series(frame, "invalid_ranking_fallback")
    policy_changes = boolean_series(frame, "supervisor_policy_changed")
    latency = _numeric(frame, "supervisor_response_time_s")
    applied = _numeric(frame, "applied_supply_air_setpoint_c").dropna()

    return {
        "total_timesteps": len(frame),
        "nvidia_calls": int(llm_calls.sum()),
        "successful_nvidia_calls": int((llm_calls & completed).sum()),
        "strict_ranking_successes": int((llm_calls & strict).sum()),
        "invalid_rankings": int(invalid.sum()),
        "deterministic_fallbacks": int(fallbacks.sum()),
        "average_nim_latency_s": (
            float(latency.mean()) if not latency.dropna().empty else None
        ),
        "maximum_nim_latency_s": (
            float(latency.max()) if not latency.dropna().empty else None
        ),
        "policy_changes": int(policy_changes.sum()),
        "physical_actuator_changes": int(applied.diff().ne(0).sum() - 1)
        if not applied.empty
        else 0,
        "physical_safety_corrections": int(safety.sum()),
        "minimum_zone_temperature_c": _aggregate(
            frame,
            "indoor_temp_c",
            "min",
        ),
        "maximum_zone_temperature_c": _aggregate(
            frame,
            "indoor_temp_c",
            "max",
        ),
        "mean_zone_temperature_c": _aggregate(
            frame,
            "indoor_temp_c",
            "mean",
        ),
        "mean_hvac_power_kw": _aggregate(frame, "hvac_power_kw", "mean"),
        "mean_facility_power_kw": _aggregate(
            frame,
            "facility_power_kw",
            "mean",
        ),
        "operational_target_violation_rate": (
            operational_target_violation_rate(frame)
        ),
        "warning_count": warning_count,
        "severe_error_count": severe_error_count,
    }


def latest_supervisory_row(frame: pd.DataFrame) -> pd.Series | None:
    if frame.empty:
        return None
    has_candidates = pd.Series(False, index=frame.index)
    if "candidate_count" in frame.columns:
        has_candidates = (
            pd.to_numeric(frame["candidate_count"], errors="coerce")
            .fillna(0)
            .gt(0)
        )
    if "candidate_ids" in frame.columns:
        has_candidates = has_candidates | frame["candidate_ids"].map(
            lambda value: bool(safe_json_list(value))
        )
    rows = frame.loc[has_candidates]
    return None if rows.empty else rows.iloc[-1]


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(float("nan"), index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def _aggregate(
    frame: pd.DataFrame,
    column: str,
    operation: str,
) -> float | None:
    values = _numeric(frame, column).dropna()
    if values.empty:
        return None
    return float(getattr(values, operation)())


def _empty_metrics(
    warning_count: int | None,
    severe_error_count: int | None,
) -> dict[str, int | float | None]:
    return {
        "total_timesteps": 0,
        "nvidia_calls": 0,
        "successful_nvidia_calls": 0,
        "strict_ranking_successes": 0,
        "invalid_rankings": 0,
        "deterministic_fallbacks": 0,
        "average_nim_latency_s": None,
        "maximum_nim_latency_s": None,
        "policy_changes": 0,
        "physical_actuator_changes": 0,
        "physical_safety_corrections": 0,
        "minimum_zone_temperature_c": None,
        "maximum_zone_temperature_c": None,
        "mean_zone_temperature_c": None,
        "mean_hvac_power_kw": None,
        "mean_facility_power_kw": None,
        "operational_target_violation_rate": None,
        "warning_count": warning_count,
        "severe_error_count": severe_error_count,
    }
