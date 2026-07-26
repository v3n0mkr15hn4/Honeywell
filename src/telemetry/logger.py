"""CSV telemetry for physical node-setpoint control."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import TextIO

from controller.action import ControlAction
from controller.state import BuildingState
from controller.supervisor_policy import SupervisorPolicy


class ControlLogger:
    """Write one unambiguous telemetry row per completed zone timestep."""

    FIELDNAMES = [
        "simulation_time",
        "timestep",
        "indoor_temp_c",
        "outdoor_temp_c",
        "facility_power_kw",
        "hvac_power_kw",
        "cooling_coil_power_kw",
        "requested_supply_air_setpoint_c",
        "validated_supply_air_setpoint_c",
        "applied_supply_air_setpoint_c",
        "measured_node_setpoint_c",
        "measured_supply_air_temperature_c",
        "zone_thermostat_cooling_setpoint_c",
        "legacy_cooling_setpoint_alias_c",
        "heating_thermostat_setpoint_c",
        "occupancy",
        "pmv",
        "controller_type",
        "decision_source",
        "strategy",
        "reason",
        "safety_corrected",
        "validation_status",
        "fallback_used",
        "llm_response_time_s",
        "llm_call_due",
        "llm_call_made",
        "action_reused",
        "decision_interval_timesteps",
        "timesteps_since_last_llm_call",
        "consecutive_llm_failures",
        "cooldown_active",
        "cooldown_intervals_remaining",
        "fallback_reason",
        "supervisor_enabled",
        "supervisor_provider",
        "supervisor_model",
        "supervisor_call_due",
        "supervisor_called",
        "supervisor_response_time_s",
        "supervisor_fallback_used",
        "supervisor_failure_reason",
        "supervisor_cooldown_active",
        "supervisor_policy_age_hours",
        "supervisor_policy_changed",
        "thermal_priority",
        "energy_priority",
        "controller_aggressiveness",
        "target_zone_temperature_c",
        "minimum_action_hold_intervals",
        "policy_duration_hours",
        "policy_strategy",
        "policy_reason",
        "policy_safety_corrected",
        "policy_validation_status",
        "candidate_generation_reason",
        "candidate_count",
        "candidate_ids",
        "candidate_policy_summaries",
        "deterministic_recommendation_id",
        "deterministic_candidate_ranking",
        "forced_single_candidate",
        "llm_ranker_called",
        "llm_raw_ranking",
        "llm_selected_policy_id",
        "llm_confidence",
        "llm_reason",
        "ranking_validation_status",
        "confidence_gate_status",
        "final_selected_policy_id",
        "selected_policy_source",
        "low_confidence_fallback",
        "invalid_ranking_fallback",
        "timeout_fallback",
        "llm_provider",
        "llm_model",
        "llm_request_started",
        "llm_request_completed",
        "llm_retry_count",
        "llm_http_status_category",
        "llm_failure_category",
        "deterministic_fallback_used",
        "control_point",
    ]

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file: TextIO = self.path.open("w", newline="", encoding="utf-8")
        self.writer = csv.DictWriter(self.file, fieldnames=self.FIELDNAMES)
        self.writer.writeheader()
        self.file.flush()

    def write(
        self,
        building_state: BuildingState,
        requested_action: ControlAction,
        validated_action: ControlAction,
        applied_action: ControlAction | None,
        validation_result: str,
        controller_type: str = "RuleController",
        llm_response_time_seconds: float | None = None,
        fallback_used: bool = False,
        safety_corrected: bool = False,
        llm_call_due: bool = False,
        llm_call_made: bool = False,
        action_reused: bool = False,
        decision_interval_timesteps: int = 1,
        timesteps_since_last_llm_call: int = 0,
        decision_source: str = "rule",
        consecutive_llm_failures: int = 0,
        cooldown_active: bool = False,
        cooldown_intervals_remaining: int = 0,
        fallback_reason: str = "",
        supervisor_enabled: bool = False,
        supervisor_provider: str = "",
        supervisor_model: str = "",
        supervisor_call_due: bool = False,
        supervisor_called: bool = False,
        supervisor_response_time_s: float | None = None,
        supervisor_fallback_used: bool = False,
        supervisor_failure_reason: str = "",
        supervisor_cooldown_active: bool = False,
        supervisor_policy_age_hours: float = 0.0,
        supervisor_policy_changed: bool = False,
        supervisor_policy: SupervisorPolicy | None = None,
        policy_safety_corrected: bool = False,
        policy_validation_status: str = "",
        candidate_metadata: dict[str, object] | None = None,
    ) -> None:
        """Append state, request, validated target, applied target, and metadata."""

        candidate = candidate_metadata or {}
        validated_setpoint = (
            validated_action.supply_air_temperature_setpoint
        )
        self.writer.writerow(
            {
                "simulation_time": building_state.sim_time,
                "timestep": building_state.timestep,
                "indoor_temp_c": self._format_optional(
                    building_state.zone_temperature,
                ),
                "outdoor_temp_c": self._format_optional(
                    building_state.outdoor_temperature,
                ),
                "facility_power_kw": self._format_optional(
                    building_state.power_kw,
                ),
                "hvac_power_kw": self._format_optional(
                    building_state.hvac_power_kw,
                ),
                "cooling_coil_power_kw": self._format_optional(
                    building_state.cooling_coil_power_kw,
                ),
                "requested_supply_air_setpoint_c": self._format_optional(
                    requested_action.supply_air_temperature_setpoint,
                ),
                "validated_supply_air_setpoint_c": self._format_optional(
                    validated_setpoint,
                ),
                "applied_supply_air_setpoint_c": self._format_optional(
                    applied_action.supply_air_temperature_setpoint
                    if applied_action
                    else None,
                ),
                "measured_node_setpoint_c": self._format_optional(
                    building_state.supply_air_temperature_setpoint,
                ),
                "measured_supply_air_temperature_c": self._format_optional(
                    building_state.measured_supply_air_temperature,
                ),
                "zone_thermostat_cooling_setpoint_c": self._format_optional(
                    building_state.zone_thermostat_cooling_setpoint,
                ),
                "legacy_cooling_setpoint_alias_c": self._format_optional(
                    validated_setpoint,
                ),
                "heating_thermostat_setpoint_c": self._format_optional(
                    building_state.heating_setpoint,
                ),
                "occupancy": self._format_optional(building_state.occupancy),
                "pmv": self._format_optional(building_state.pmv),
                "controller_type": controller_type,
                "decision_source": decision_source,
                "strategy": validated_action.strategy,
                "reason": validated_action.reason,
                "safety_corrected": str(safety_corrected),
                "validation_status": validation_result,
                "fallback_used": str(fallback_used),
                "llm_response_time_s": self._format_optional(
                    llm_response_time_seconds,
                ),
                "llm_call_due": str(llm_call_due),
                "llm_call_made": str(llm_call_made),
                "action_reused": str(action_reused),
                "decision_interval_timesteps": decision_interval_timesteps,
                "timesteps_since_last_llm_call": timesteps_since_last_llm_call,
                "consecutive_llm_failures": consecutive_llm_failures,
                "cooldown_active": str(cooldown_active),
                "cooldown_intervals_remaining": cooldown_intervals_remaining,
                "fallback_reason": fallback_reason,
                "supervisor_enabled": str(supervisor_enabled),
                "supervisor_provider": supervisor_provider,
                "supervisor_model": supervisor_model,
                "supervisor_call_due": str(supervisor_call_due),
                "supervisor_called": str(supervisor_called),
                "supervisor_response_time_s": self._format_optional(
                    supervisor_response_time_s,
                ),
                "supervisor_fallback_used": str(
                    supervisor_fallback_used
                ),
                "supervisor_failure_reason": supervisor_failure_reason,
                "supervisor_cooldown_active": str(
                    supervisor_cooldown_active
                ),
                "supervisor_policy_age_hours": self._format_optional(
                    supervisor_policy_age_hours,
                ),
                "supervisor_policy_changed": str(
                    supervisor_policy_changed
                ),
                "thermal_priority": (
                    supervisor_policy.thermal_priority.value
                    if supervisor_policy
                    else ""
                ),
                "energy_priority": (
                    supervisor_policy.energy_priority.value
                    if supervisor_policy
                    else ""
                ),
                "controller_aggressiveness": (
                    supervisor_policy.controller_aggressiveness.value
                    if supervisor_policy
                    else ""
                ),
                "target_zone_temperature_c": self._format_optional(
                    supervisor_policy.target_zone_temperature_c
                    if supervisor_policy
                    else None,
                ),
                "minimum_action_hold_intervals": (
                    supervisor_policy.minimum_action_hold_intervals
                    if supervisor_policy
                    else ""
                ),
                "policy_duration_hours": (
                    supervisor_policy.policy_duration_hours
                    if supervisor_policy
                    else ""
                ),
                "policy_strategy": (
                    supervisor_policy.strategy if supervisor_policy else ""
                ),
                "policy_reason": (
                    supervisor_policy.reason if supervisor_policy else ""
                ),
                "policy_safety_corrected": str(
                    policy_safety_corrected
                ),
                "policy_validation_status": policy_validation_status,
                "candidate_generation_reason": candidate.get(
                    "candidate_generation_reason",
                    "",
                ),
                "candidate_count": candidate.get("candidate_count", ""),
                "candidate_ids": json.dumps(
                    candidate.get("candidate_ids", []),
                    separators=(",", ":"),
                ),
                "candidate_policy_summaries": json.dumps(
                    candidate.get("candidate_policy_summaries", []),
                    separators=(",", ":"),
                ),
                "deterministic_recommendation_id": candidate.get(
                    "deterministic_recommendation_id",
                    "",
                ),
                "deterministic_candidate_ranking": json.dumps(
                    candidate.get("deterministic_candidate_ranking", []),
                    separators=(",", ":"),
                ),
                "forced_single_candidate": str(
                    candidate.get("forced_single_candidate", False)
                ),
                "llm_ranker_called": str(
                    candidate.get("llm_ranker_called", False)
                ),
                "llm_raw_ranking": json.dumps(
                    candidate.get("llm_raw_ranking", []),
                    separators=(",", ":"),
                ),
                "llm_selected_policy_id": candidate.get(
                    "llm_selected_policy_id",
                    "",
                ),
                "llm_confidence": self._format_optional(
                    candidate.get("llm_confidence")
                    if isinstance(
                        candidate.get("llm_confidence"),
                        (int, float),
                    )
                    else None
                ),
                "llm_reason": candidate.get("llm_reason", ""),
                "ranking_validation_status": candidate.get(
                    "ranking_validation_status",
                    "",
                ),
                "confidence_gate_status": candidate.get(
                    "confidence_gate_status",
                    "",
                ),
                "final_selected_policy_id": candidate.get(
                    "final_selected_policy_id",
                    "",
                ),
                "selected_policy_source": candidate.get(
                    "selected_policy_source",
                    "",
                ),
                "low_confidence_fallback": str(
                    candidate.get("low_confidence_fallback", False)
                ),
                "invalid_ranking_fallback": str(
                    candidate.get("invalid_ranking_fallback", False)
                ),
                "timeout_fallback": str(
                    candidate.get("timeout_fallback", False)
                ),
                "llm_provider": candidate.get("llm_provider", ""),
                "llm_model": candidate.get("llm_model", ""),
                "llm_request_started": str(
                    candidate.get("llm_request_started", False)
                ),
                "llm_request_completed": str(
                    candidate.get("llm_request_completed", False)
                ),
                "llm_retry_count": candidate.get("llm_retry_count", 0),
                "llm_http_status_category": candidate.get(
                    "llm_http_status_category",
                    "",
                ),
                "llm_failure_category": candidate.get(
                    "llm_failure_category",
                    "",
                ),
                "deterministic_fallback_used": str(
                    candidate.get("deterministic_fallback_used", False)
                ),
                "control_point": "MAIN COOLING COIL 1 OUTLET NODE",
            }
        )
        self.file.flush()

    def close(self) -> None:
        """Close the CSV file handle."""

        self.file.close()

    @staticmethod
    def _format_optional(value: float | None) -> str:
        if value is None:
            return ""
        return f"{value:.3f}"
