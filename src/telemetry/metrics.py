"""Aggregate metrics for EnergyPlus supply-air control runs."""

from __future__ import annotations

import math
import time
from pathlib import Path

from controller.action import ControlAction
from controller.state import BuildingState


class MetricsTracker:
    """Track physical performance, decision cadence, and fallback behavior."""

    def __init__(
        self,
        pmv_violation_threshold: float = 0.5,
        zone_temperature_target_threshold_c: float = 30.0,
    ) -> None:
        self.start_time = time.perf_counter()
        self.end_time: float | None = None
        self.energy_kwh = 0.0
        self.hvac_energy_kwh = 0.0
        self.cooling_coil_energy_kwh = 0.0
        self.energy_sample_count = 0
        self.power_kw_sum = 0.0
        self.power_sample_count = 0
        self.pmv_sum = 0.0
        self.pmv_sample_count = 0
        self.indoor_temp_sum = 0.0
        self.indoor_temp_sample_count = 0
        self.minimum_indoor_temp_c: float | None = None
        self.maximum_indoor_temp_c: float | None = None
        self.zone_temperature_target_violations = 0
        self.supply_air_temp_sum = 0.0
        self.supply_air_temp_sample_count = 0
        self.occupied_pmv_samples = 0
        self.occupied_pmv_violations = 0
        self.control_timesteps = 0
        self.controller_decisions = 0
        self.reused_actions = 0
        self.actuator_changes = 0
        self.safety_corrections = 0
        self.llm_requests = 0
        self.llm_failures = 0
        self.rule_fallbacks = 0
        self.cooldown_activations = 0
        self.llm_response_times: list[float] = []
        self.supervisory_calls = 0
        self.successful_supervisory_calls = 0
        self.supervisory_parser_failures = 0
        self.supervisory_timeouts = 0
        self.supervisory_fallbacks = 0
        self.policy_validation_corrections = 0
        self.policy_changes = 0
        self.policy_reuse_count = 0
        self.default_policy_usage_count = 0
        self.supervisor_cooldown_activations = 0
        self.supervisor_cooldown_hours = 0.0
        self.supervisor_response_times: list[float] = []
        self.candidate_supervisory_opportunities = 0
        self.forced_single_candidate_decisions = 0
        self.multi_candidate_llm_calls = 0
        self.successful_candidate_rankings = 0
        self.invalid_candidate_rankings = 0
        self.incomplete_candidate_rankings = 0
        self.duplicate_candidate_rankings = 0
        self.unknown_candidate_attempts = 0
        self.low_confidence_fallbacks = 0
        self.candidate_timeout_fallbacks = 0
        self.candidate_parser_failures = 0
        self.candidate_selection_distribution: dict[str, int] = {}
        self.candidate_confidences: list[float] = []
        self.nvidia_nim_calls = 0
        self.nvidia_nim_successful_calls = 0
        self.nvidia_nim_authentication_failures = 0
        self.nvidia_nim_rate_limit_failures = 0
        self.nvidia_nim_timeouts = 0
        self.nvidia_nim_network_failures = 0
        self.nvidia_nim_server_failures = 0
        self.nvidia_nim_deterministic_fallbacks = 0
        self.controller_type = "Unknown"
        self.energyplus_exit_code: int | None = None
        self.pmv_violation_threshold = pmv_violation_threshold
        self.zone_temperature_target_threshold_c = (
            zone_temperature_target_threshold_c
        )
        self._last_applied_action: ControlAction | None = None

    def record_actuator_application(self, action: ControlAction | None) -> None:
        """Count changes in the applied physical node-setpoint action."""

        if action is None:
            return
        current = action.supply_air_temperature_setpoint
        previous = (
            self._last_applied_action.supply_air_temperature_setpoint
            if self._last_applied_action
            else None
        )
        if previous is None or current != previous:
            self.actuator_changes += 1
        self._last_applied_action = action

    def record_timestep(
        self,
        building_state: BuildingState,
        decision_made: bool,
        safety_corrected: bool,
        llm_call_made: bool,
        llm_failure: bool,
        fallback_used: bool,
        action_reused: bool,
        controller_type: str,
        llm_response_time_seconds: float | None,
        cooldown_activated: bool = False,
        supervisor_call_due: bool = False,
        supervisor_called: bool = False,
        supervisor_failure: bool = False,
        supervisor_parser_failure: bool = False,
        supervisor_timeout: bool = False,
        supervisor_fallback_used: bool = False,
        supervisor_validation_corrected: bool = False,
        supervisor_policy_changed: bool = False,
        supervisor_policy_reused: bool = False,
        default_policy_used: bool = False,
        supervisor_response_time_s: float | None = None,
        supervisor_cooldown_active: bool = False,
        supervisor_cooldown_activated: bool = False,
        candidate_metadata: dict[str, object] | None = None,
    ) -> None:
        """Record one completed non-warmup zone timestep."""

        self.controller_type = controller_type
        self.control_timesteps += 1
        if decision_made:
            self.controller_decisions += 1
        if action_reused:
            self.reused_actions += 1

        if self._is_finite(building_state.power_kw):
            self.power_kw_sum += building_state.power_kw
            self.power_sample_count += 1
            if self._is_finite(building_state.timestep_duration_hours):
                self.energy_kwh += (
                    building_state.power_kw
                    * building_state.timestep_duration_hours
                )
                self.energy_sample_count += 1

        if self._is_finite(building_state.timestep_duration_hours):
            timestep_hours = building_state.timestep_duration_hours
            if self._is_finite(building_state.hvac_power_kw):
                self.hvac_energy_kwh += (
                    building_state.hvac_power_kw * timestep_hours
                )
            if self._is_finite(building_state.cooling_coil_power_kw):
                self.cooling_coil_energy_kwh += (
                    building_state.cooling_coil_power_kw * timestep_hours
                )

        if self._is_finite(building_state.pmv):
            self.pmv_sum += building_state.pmv
            self.pmv_sample_count += 1
            if self._is_occupied(building_state.occupancy):
                self.occupied_pmv_samples += 1
                if abs(building_state.pmv) > self.pmv_violation_threshold:
                    self.occupied_pmv_violations += 1

        if self._is_finite(building_state.zone_temperature):
            self.indoor_temp_sum += building_state.zone_temperature
            self.indoor_temp_sample_count += 1
            self.minimum_indoor_temp_c = (
                building_state.zone_temperature
                if self.minimum_indoor_temp_c is None
                else min(
                    self.minimum_indoor_temp_c,
                    building_state.zone_temperature,
                )
            )
            self.maximum_indoor_temp_c = (
                building_state.zone_temperature
                if self.maximum_indoor_temp_c is None
                else max(
                    self.maximum_indoor_temp_c,
                    building_state.zone_temperature,
                )
            )
            if (
                building_state.zone_temperature
                > self.zone_temperature_target_threshold_c
            ):
                self.zone_temperature_target_violations += 1

        if self._is_finite(building_state.measured_supply_air_temperature):
            self.supply_air_temp_sum += (
                building_state.measured_supply_air_temperature
            )
            self.supply_air_temp_sample_count += 1

        if safety_corrected:
            self.safety_corrections += 1
        if llm_call_made:
            self.llm_requests += 1
        if llm_failure:
            self.llm_failures += 1
        if fallback_used:
            self.rule_fallbacks += 1
        if cooldown_activated:
            self.cooldown_activations += 1
        if self._is_finite(llm_response_time_seconds):
            self.llm_response_times.append(llm_response_time_seconds)
        if supervisor_called:
            self.supervisory_calls += 1
            if not supervisor_failure:
                self.successful_supervisory_calls += 1
        if supervisor_parser_failure:
            self.supervisory_parser_failures += 1
        if supervisor_timeout:
            self.supervisory_timeouts += 1
        if supervisor_fallback_used:
            self.supervisory_fallbacks += 1
        if supervisor_validation_corrected:
            self.policy_validation_corrections += 1
        if supervisor_policy_changed:
            self.policy_changes += 1
        if supervisor_policy_reused:
            self.policy_reuse_count += 1
        if default_policy_used:
            self.default_policy_usage_count += 1
        if supervisor_cooldown_activated:
            self.supervisor_cooldown_activations += 1
        if (
            supervisor_cooldown_active
            and self._is_finite(building_state.timestep_duration_hours)
        ):
            self.supervisor_cooldown_hours += (
                building_state.timestep_duration_hours
            )
        if self._is_finite(supervisor_response_time_s):
            self.supervisor_response_times.append(
                supervisor_response_time_s
            )
        candidate = candidate_metadata or {}
        if candidate:
            self.candidate_supervisory_opportunities += 1
            if candidate.get("forced_single_candidate") is True:
                self.forced_single_candidate_decisions += 1
            if candidate.get("llm_ranker_called") is True:
                self.multi_candidate_llm_calls += 1
            if candidate.get("selected_policy_source") == "llm_selected":
                self.successful_candidate_rankings += 1
            if candidate.get("invalid_ranking_fallback") is True:
                self.invalid_candidate_rankings += 1
            status = str(candidate.get("ranking_validation_status", "")).lower()
            if "incomplete" in status:
                self.incomplete_candidate_rankings += 1
            if "duplicate" in status:
                self.duplicate_candidate_rankings += 1
            if "unknown" in status:
                self.unknown_candidate_attempts += 1
            if candidate.get("low_confidence_fallback") is True:
                self.low_confidence_fallbacks += 1
            if candidate.get("timeout_fallback") is True:
                self.candidate_timeout_fallbacks += 1
            if supervisor_parser_failure:
                self.candidate_parser_failures += 1
            selected_id = str(
                candidate.get("final_selected_policy_id", "")
            )
            if selected_id:
                self.candidate_selection_distribution[selected_id] = (
                    self.candidate_selection_distribution.get(selected_id, 0)
                    + 1
                )
            confidence = candidate.get("llm_confidence")
            if self._is_finite(confidence):
                self.candidate_confidences.append(float(confidence))
            if (
                candidate.get("llm_provider") == "nvidia_nim"
                and candidate.get("llm_ranker_called") is True
            ):
                self.nvidia_nim_calls += 1
                if candidate.get("llm_request_completed") is True:
                    self.nvidia_nim_successful_calls += 1
                category = str(candidate.get("llm_failure_category", ""))
                if category in {"authentication_error", "permission_error"}:
                    self.nvidia_nim_authentication_failures += 1
                elif category == "rate_limit_error":
                    self.nvidia_nim_rate_limit_failures += 1
                elif category == "timeout":
                    self.nvidia_nim_timeouts += 1
                elif category == "transport_error":
                    self.nvidia_nim_network_failures += 1
                elif category == "server_error":
                    self.nvidia_nim_server_failures += 1
                if candidate.get("deterministic_fallback_used") is True:
                    self.nvidia_nim_deterministic_fallbacks += 1

    def snapshot(self) -> dict[str, int | float]:
        """Return bounded counters for supervisory prompt construction."""

        return {
            "physical_actuator_changes": self.actuator_changes,
            "physical_safety_corrections": self.safety_corrections,
            "supervisory_fallbacks": self.supervisory_fallbacks,
            "supervisory_calls": self.supervisory_calls,
            "policy_changes": self.policy_changes,
            "facility_energy_kwh": self.energy_kwh,
        }

    def finish(self, energyplus_exit_code: int | None = None) -> None:
        self.end_time = time.perf_counter()
        self.energyplus_exit_code = energyplus_exit_code

    def build_summary(self) -> str:
        duration = (self.end_time or time.perf_counter()) - self.start_time
        return "\n".join(
            [
                "Controller Metrics Summary",
                "",
                f"Controller Type: {self.controller_type}",
                f"EnergyPlus Exit Code: {self._format_int(self.energyplus_exit_code)}",
                f"Simulation Wall-Clock Duration Seconds: {duration:.3f}",
                f"Total Energy Consumption kWh: {self.energy_kwh:.6f}",
                f"Facility Energy kWh: {self.energy_kwh:.6f}",
                f"HVAC Energy kWh: {self.hvac_energy_kwh:.6f}",
                f"Cooling-Coil Energy kWh: {self.cooling_coil_energy_kwh:.6f}",
                f"Average Sampled Facility Power kW: {self._average_power_kw()}",
                "Energy Metric Source: Facility Total Electricity Demand Rate [W]",
                "Energy Conversion: W -> kW, then kW * timestep hours -> kWh",
                f"Energy Samples Integrated: {self.energy_sample_count}",
                f"Average Valid PMV: {self._average_pmv()}",
                f"PMV Comfort Threshold: abs(PMV) > {self.pmv_violation_threshold:.3f}",
                f"Occupied Comfort Violation Rate: {self._occupied_violation_rate()}",
                f"Average Indoor Temperature C: {self._average_indoor_temp()}",
                f"Minimum Indoor Temperature C: {self._format_float(self.minimum_indoor_temp_c)}",
                f"Maximum Indoor Temperature C: {self._format_float(self.maximum_indoor_temp_c)}",
                (
                    "Zone Temperature Target Threshold C: "
                    f"{self.zone_temperature_target_threshold_c:.3f}"
                ),
                (
                    "Zone Temperature Target Violation Rate: "
                    f"{self._zone_temperature_violation_rate()}"
                ),
                (
                    "Average Measured Supply-Air Temperature C: "
                    f"{self._average_supply_air_temp()}"
                ),
                f"Total Control Timesteps: {self.control_timesteps}",
                f"Total Controller Decisions: {self.controller_decisions}",
                f"Total Reused Actions: {self.reused_actions}",
                f"Total Supply-Air Setpoint Changes: {self.actuator_changes}",
                (
                    "Actuator Change Definition: one changed applied "
                    "supply-air temperature setpoint"
                ),
                f"Total Safety Corrections: {self.safety_corrections}",
                f"Total LLM Requests: {self.llm_requests}",
                f"Total LLM Failures: {self.llm_failures}",
                f"Total RuleController Fallbacks: {self.rule_fallbacks}",
                f"Total LLM Cooldown Activations: {self.cooldown_activations}",
                f"Average LLM Response Time Seconds: {self._average_llm_response_time()}",
                f"P95 LLM Response Time Seconds: {self._p95_llm_response_time()}",
                f"Maximum LLM Response Time Seconds: {self._max_llm_response_time()}",
                f"Total Supervisory Calls: {self.supervisory_calls}",
                (
                    "Successful Supervisory Calls: "
                    f"{self.successful_supervisory_calls}"
                ),
                (
                    "Supervisory Parser Failures: "
                    f"{self.supervisory_parser_failures}"
                ),
                f"Supervisory Timeouts: {self.supervisory_timeouts}",
                f"Supervisory Fallbacks: {self.supervisory_fallbacks}",
                (
                    "Policy Validation Corrections: "
                    f"{self.policy_validation_corrections}"
                ),
                f"Policy Changes: {self.policy_changes}",
                f"Policy Reuse Count: {self.policy_reuse_count}",
                (
                    "Default Policy Usage Count: "
                    f"{self.default_policy_usage_count}"
                ),
                (
                    "Supervisor Cooldown Activations: "
                    f"{self.supervisor_cooldown_activations}"
                ),
                (
                    "Supervisor Cooldown Hours: "
                    f"{self.supervisor_cooldown_hours:.6f}"
                ),
                (
                    "Average Supervisory Latency Seconds: "
                    f"{self._response_average(self.supervisor_response_times)}"
                ),
                (
                    "P95 Supervisory Latency Seconds: "
                    f"{self._response_p95(self.supervisor_response_times)}"
                ),
                (
                    "Maximum Supervisory Latency Seconds: "
                    f"{self._response_max(self.supervisor_response_times)}"
                ),
                (
                    "Candidate Supervisory Opportunities: "
                    f"{self.candidate_supervisory_opportunities}"
                ),
                (
                    "Forced Single-Candidate Decisions: "
                    f"{self.forced_single_candidate_decisions}"
                ),
                (
                    "Multi-Candidate LLM Calls: "
                    f"{self.multi_candidate_llm_calls}"
                ),
                (
                    "Successful Valid Candidate Rankings: "
                    f"{self.successful_candidate_rankings}"
                ),
                (
                    "Invalid Candidate Rankings: "
                    f"{self.invalid_candidate_rankings}"
                ),
                (
                    "Incomplete Candidate Rankings: "
                    f"{self.incomplete_candidate_rankings}"
                ),
                (
                    "Duplicate-ID Candidate Rankings: "
                    f"{self.duplicate_candidate_rankings}"
                ),
                (
                    "Unknown Candidate ID Attempts: "
                    f"{self.unknown_candidate_attempts}"
                ),
                (
                    "Low-Confidence Candidate Fallbacks: "
                    f"{self.low_confidence_fallbacks}"
                ),
                (
                    "Candidate Timeout Fallbacks: "
                    f"{self.candidate_timeout_fallbacks}"
                ),
                (
                    "Candidate Parser Failures: "
                    f"{self.candidate_parser_failures}"
                ),
                (
                    "Candidate Selection Distribution: "
                    f"{self.candidate_selection_distribution}"
                ),
                (
                    "Average Candidate Confidence: "
                    f"{self._response_average(self.candidate_confidences)}"
                ),
                (
                    "Median Supervisory Latency Seconds: "
                    f"{self._response_median(self.supervisor_response_times)}"
                ),
                f"Total NVIDIA NIM Calls: {self.nvidia_nim_calls}",
                (
                    "Successful NVIDIA NIM Calls: "
                    f"{self.nvidia_nim_successful_calls}"
                ),
                (
                    "NVIDIA NIM Authentication Failures: "
                    f"{self.nvidia_nim_authentication_failures}"
                ),
                (
                    "NVIDIA NIM Rate-Limit Failures: "
                    f"{self.nvidia_nim_rate_limit_failures}"
                ),
                f"NVIDIA NIM Timeouts: {self.nvidia_nim_timeouts}",
                (
                    "NVIDIA NIM Network Failures: "
                    f"{self.nvidia_nim_network_failures}"
                ),
                (
                    "NVIDIA NIM Server Failures: "
                    f"{self.nvidia_nim_server_failures}"
                ),
                (
                    "NVIDIA NIM Deterministic Fallbacks: "
                    f"{self.nvidia_nim_deterministic_fallbacks}"
                ),
            ]
        )

    def write_summary(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        summary = self.build_summary()
        path.write_text(summary + "\n", encoding="utf-8")
        print()
        print(summary)
        print(f"[Telemetry] Metrics summary written to: {path}")

    def _average_power_kw(self) -> str:
        if self.power_sample_count == 0:
            return "Unavailable"
        return f"{self.power_kw_sum / self.power_sample_count:.6f}"

    def _average_pmv(self) -> str:
        if self.pmv_sample_count == 0:
            return "Unavailable"
        return f"{self.pmv_sum / self.pmv_sample_count:.6f}"

    def _average_indoor_temp(self) -> str:
        if self.indoor_temp_sample_count == 0:
            return "Unavailable"
        return f"{self.indoor_temp_sum / self.indoor_temp_sample_count:.6f}"

    def _occupied_violation_rate(self) -> str:
        if self.occupied_pmv_samples == 0:
            return "Unavailable"
        return f"{self.occupied_pmv_violations / self.occupied_pmv_samples:.6f}"

    def _zone_temperature_violation_rate(self) -> str:
        if self.indoor_temp_sample_count == 0:
            return "Unavailable"
        return (
            f"{self.zone_temperature_target_violations / self.indoor_temp_sample_count:.6f}"
        )

    def _average_supply_air_temp(self) -> str:
        if self.supply_air_temp_sample_count == 0:
            return "Unavailable"
        return (
            f"{self.supply_air_temp_sum / self.supply_air_temp_sample_count:.6f}"
        )

    def _average_llm_response_time(self) -> str:
        if not self.llm_response_times:
            return "Unavailable"
        return f"{sum(self.llm_response_times) / len(self.llm_response_times):.6f}"

    def _max_llm_response_time(self) -> str:
        if not self.llm_response_times:
            return "Unavailable"
        return f"{max(self.llm_response_times):.6f}"

    def _p95_llm_response_time(self) -> str:
        if not self.llm_response_times:
            return "Unavailable"
        values = sorted(self.llm_response_times)
        index = max(0, math.ceil(len(values) * 0.95) - 1)
        return f"{values[index]:.6f}"

    @staticmethod
    def _response_average(values: list[float]) -> str:
        if not values:
            return "Unavailable"
        return f"{sum(values) / len(values):.6f}"

    @staticmethod
    def _response_max(values: list[float]) -> str:
        if not values:
            return "Unavailable"
        return f"{max(values):.6f}"

    @staticmethod
    def _response_p95(values: list[float]) -> str:
        if not values:
            return "Unavailable"
        ordered = sorted(values)
        index = max(0, math.ceil(len(ordered) * 0.95) - 1)
        return f"{ordered[index]:.6f}"

    @staticmethod
    def _response_median(values: list[float]) -> str:
        if not values:
            return "Unavailable"
        ordered = sorted(values)
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return f"{ordered[middle]:.6f}"
        return f"{(ordered[middle - 1] + ordered[middle]) / 2:.6f}"

    @staticmethod
    def _is_finite(value: float | None) -> bool:
        return value is not None and math.isfinite(value)

    @staticmethod
    def _is_occupied(value: float | None) -> bool:
        return value is not None and math.isfinite(value) and value > 0

    @staticmethod
    def _format_int(value: int | None) -> str:
        if value is None:
            return "Unavailable"
        return str(value)

    @staticmethod
    def _format_float(value: float | None) -> str:
        if value is None:
            return "Unavailable"
        return f"{value:.6f}"
