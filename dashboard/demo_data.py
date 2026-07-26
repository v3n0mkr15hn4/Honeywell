"""Deterministic sanitized telemetry for dashboard-only demonstrations."""

from __future__ import annotations

import json
import math

import pandas as pd


def build_demo_telemetry() -> pd.DataFrame:
    """Create one clearly synthetic day without contacting external systems."""

    rows: list[dict[str, object]] = []
    current_policy = "P4"
    target = 32.5
    previous_applied = 23.0
    for timestep in range(1, 145):
        hour = timestep / 6.0
        zone = 32.1 + 0.7 * math.sin((hour - 5.0) * math.pi / 12.0)
        outdoor = 11.0 + 5.0 * math.sin((hour - 7.0) * math.pi / 12.0)
        facility = 107.0 + 8.0 * math.sin((hour - 6.0) * math.pi / 12.0)
        hvac = 12.0 + 2.0 * math.sin((hour - 8.0) * math.pi / 12.0)
        requested = 22.0 if zone > target else 24.0
        validated = max(
            previous_applied - 1.0,
            min(previous_applied + 1.0, requested),
        )
        opportunity = timestep % 18 == 0
        selected = "P6" if timestep == 54 else "P4"
        if opportunity:
            current_policy = selected
        candidates = [
            {
                "candidate_id": "P3",
                "mode": "balanced",
                "thermal_priority": "medium",
                "energy_priority": "medium",
                "aggressiveness": "normal",
                "target_zone_temperature_c": 32.0,
            },
            {
                "candidate_id": "P4",
                "mode": "energy_conservative",
                "thermal_priority": "medium",
                "energy_priority": "high",
                "aggressiveness": "conservative",
                "target_zone_temperature_c": 32.5,
            },
            {
                "candidate_id": "P6",
                "mode": "hold_current",
                "thermal_priority": "medium",
                "energy_priority": "high",
                "aggressiveness": "conservative",
                "target_zone_temperature_c": target,
            },
        ]
        ranking = [selected] + [
            item["candidate_id"]
            for item in candidates
            if item["candidate_id"] != selected
        ]
        rows.append(
            {
                "simulation_time": (
                    f"DEMO-01-01 {hour:.2f} h "
                    f"(zone timestep #{(timestep - 1) % 6 + 1})"
                ),
                "timestep": timestep,
                "simulated_hour": hour,
                "indoor_temp_c": zone,
                "outdoor_temp_c": outdoor,
                "facility_power_kw": facility,
                "hvac_power_kw": hvac,
                "requested_supply_air_setpoint_c": requested,
                "validated_supply_air_setpoint_c": validated,
                "applied_supply_air_setpoint_c": previous_applied,
                "measured_supply_air_temperature_c": previous_applied + 0.2,
                "target_zone_temperature_c": target,
                "zone_trend": "rising" if hour < 12 else "falling",
                "thermal_state": (
                    "above_target" if zone > target else "near_target"
                ),
                "outdoor_trend": "rising" if hour < 14 else "falling",
                "power_trend": "rising" if hour < 12 else "falling",
                "policy_strategy": (
                    "hold_current"
                    if current_policy == "P6"
                    else "energy_conservative"
                ),
                "candidate_count": len(candidates) if opportunity else "",
                "candidate_ids": (
                    json.dumps([item["candidate_id"] for item in candidates])
                    if opportunity
                    else "[]"
                ),
                "candidate_policy_summaries": (
                    json.dumps(candidates) if opportunity else "[]"
                ),
                "deterministic_recommendation_id": (
                    selected if opportunity else ""
                ),
                "deterministic_candidate_ranking": (
                    json.dumps(ranking) if opportunity else "[]"
                ),
                "llm_ranker_called": str(opportunity),
                "llm_raw_ranking": (
                    json.dumps(ranking) if opportunity else "[]"
                ),
                "llm_selected_policy_id": selected if opportunity else "",
                "llm_confidence": 0.85 if opportunity else None,
                "llm_reason": (
                    "Synthetic advisory explanation for dashboard demonstration."
                    if opportunity
                    else ""
                ),
                "ranking_validation_status": (
                    "valid candidate ranking" if opportunity else ""
                ),
                "final_selected_policy_id": selected if opportunity else "",
                "selected_policy_source": "llm_ranked" if opportunity else "",
                "supervisor_response_time_s": 4.2 if opportunity else None,
                "llm_request_completed": str(opportunity),
                "llm_failure_category": "",
                "deterministic_fallback_used": "False",
                "invalid_ranking_fallback": "False",
                "timeout_fallback": "False",
                "safety_corrected": str(validated != requested),
                "supervisor_policy_changed": str(
                    opportunity and timestep in {18, 54, 72}
                ),
                "policy_safety_corrected": "False",
                "validation_status": (
                    "valid"
                    if validated == requested
                    else "change limited to 1.0 C"
                ),
            }
        )
        previous_applied = validated
    return pd.DataFrame(rows)
