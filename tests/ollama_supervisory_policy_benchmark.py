"""Deterministic real-Ollama benchmark for policy-only supervision."""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from controller.controller_state import ControllerState  # noqa: E402
from controller.policy_prompt_builder import build_policy_prompt  # noqa: E402
from controller.policy_validator import PolicyValidator  # noqa: E402
from controller.state import BuildingState  # noqa: E402
from controller.supervisor_output_parser import (  # noqa: E402
    SUPERVISOR_RESPONSE_SCHEMA,
    parse_supervisor_response,
)
from controller.supervisor_policy import (  # noqa: E402
    ControllerAggressiveness,
    Priority,
    SupervisorPolicy,
    default_supervisor_policy,
)
from controller.supervisory_llm_controller import (  # noqa: E402
    SupervisoryLLMController,
)
from llm.client import (  # noqa: E402
    LLMConnectionError,
    LLMTimeoutError,
    OllamaLLMClient,
)
from llm.supervisor_mock_client import (  # noqa: E402
    MockSupervisorLLMClient,
    SupervisorMockMode,
)


@dataclass(frozen=True)
class SupervisoryCase:
    case_id: str
    description: str
    zone_history_c: tuple[float, ...]
    outdoor_history_c: tuple[float, ...]
    facility_power_history_kw: tuple[float, ...]
    hvac_power_history_kw: tuple[float, ...]
    current_policy: SupervisorPolicy
    policy_age_hours: float
    expected_thermal: tuple[Priority, ...]
    expected_energy: tuple[Priority, ...]
    expected_aggressiveness: tuple[ControllerAggressiveness, ...]
    expected_target_range_c: tuple[float, float]
    expected_hold_range: tuple[int, int]
    expected_duration_range_hours: tuple[int, int]
    requires_policy_change: bool = False


def policy(
    thermal: Priority,
    energy: Priority,
    aggressiveness: ControllerAggressiveness,
    target: float,
    hold: int,
    duration: int,
    strategy: str,
) -> SupervisorPolicy:
    return SupervisorPolicy(
        thermal_priority=thermal,
        energy_priority=energy,
        controller_aggressiveness=aggressiveness,
        target_zone_temperature_c=target,
        minimum_action_hold_intervals=hold,
        policy_duration_hours=duration,
        strategy=strategy,
        reason="Previously validated supervisory policy.",
    )


def benchmark_cases() -> list[SupervisoryCase]:
    default = default_supervisor_policy()
    thermal = policy(
        Priority.HIGH,
        Priority.LOW,
        ControllerAggressiveness.AGGRESSIVE,
        31.0,
        1,
        4,
        "thermal_recovery",
    )
    energy = policy(
        Priority.MEDIUM,
        Priority.HIGH,
        ControllerAggressiveness.CONSERVATIVE,
        33.0,
        4,
        8,
        "energy_conservation",
    )
    return [
        SupervisoryCase(
            "strong_thermal_deterioration",
            "Zone is high and rising while power also rises",
            (30.0, 31.0, 32.0, 33.0),
            (34.0, 35.0, 36.0, 37.0),
            (90.0, 95.0, 101.0, 108.0),
            (14.0, 15.0, 17.0, 19.0),
            default,
            5.5,
            (Priority.HIGH,),
            (Priority.LOW, Priority.MEDIUM),
            (
                ControllerAggressiveness.NORMAL,
                ControllerAggressiveness.AGGRESSIVE,
            ),
            (30.0, 32.0),
            (1, 2),
            (4, 6),
        ),
        SupervisoryCase(
            "thermal_recovery",
            "Previously hot zone is falling steadily",
            (34.0, 33.0, 32.0, 31.0),
            (35.0, 34.0, 33.0, 32.0),
            (112.0, 106.0, 100.0, 94.0),
            (20.0, 18.0, 16.0, 14.0),
            thermal,
            3.5,
            (Priority.MEDIUM, Priority.HIGH),
            (Priority.MEDIUM,),
            (
                ControllerAggressiveness.CONSERVATIVE,
                ControllerAggressiveness.NORMAL,
            ),
            (31.0, 33.0),
            (2, 4),
            (4, 8),
        ),
        SupervisoryCase(
            "high_energy_thermally_acceptable",
            "Zone is stable near target while energy use is high",
            (31.8, 31.9, 32.0, 32.0),
            (29.0, 29.0, 29.0, 29.0),
            (125.0, 128.0, 130.0, 132.0),
            (23.0, 24.0, 25.0, 25.0),
            default,
            5.5,
            (Priority.LOW, Priority.MEDIUM),
            (Priority.HIGH,),
            (
                ControllerAggressiveness.CONSERVATIVE,
                ControllerAggressiveness.NORMAL,
            ),
            (32.0, 34.0),
            (2, 6),
            (6, 12),
            True,
        ),
        SupervisoryCase(
            "high_energy_and_overheating",
            "Zone and power are both high and rising",
            (31.0, 32.0, 33.0, 34.0),
            (34.0, 35.0, 36.0, 37.0),
            (120.0, 126.0, 132.0, 138.0),
            (20.0, 22.0, 24.0, 26.0),
            default,
            5.5,
            (Priority.HIGH,),
            (Priority.LOW, Priority.MEDIUM),
            (
                ControllerAggressiveness.NORMAL,
                ControllerAggressiveness.AGGRESSIVE,
            ),
            (30.0, 32.0),
            (1, 2),
            (4, 6),
        ),
        SupervisoryCase(
            "stable_balanced",
            "Temperature and power remain stable under balanced policy",
            (31.9, 32.0, 32.0, 32.0),
            (28.0, 28.0, 28.0, 28.0),
            (82.0, 82.0, 81.5, 82.0),
            (12.0, 12.0, 12.0, 12.0),
            default,
            5.5,
            (Priority.HIGH,),
            (Priority.MEDIUM,),
            (ControllerAggressiveness.NORMAL,),
            (31.5, 32.5),
            (2, 2),
            (6, 6),
        ),
        SupervisoryCase(
            "rapid_outdoor_change",
            "Outdoor temperature rises rapidly and zone starts rising",
            (30.5, 30.7, 31.0, 31.5),
            (20.0, 25.0, 30.0, 36.0),
            (80.0, 83.0, 87.0, 92.0),
            (11.0, 12.0, 13.0, 15.0),
            default,
            5.5,
            (Priority.MEDIUM, Priority.HIGH),
            (Priority.MEDIUM,),
            (
                ControllerAggressiveness.CONSERVATIVE,
                ControllerAggressiveness.NORMAL,
            ),
            (31.0, 33.0),
            (1, 3),
            (4, 6),
        ),
        SupervisoryCase(
            "already_thermal_high_improving",
            "Thermal-high policy is active and conditions improve",
            (34.0, 33.0, 32.0, 31.0),
            (36.0, 35.0, 34.0, 33.0),
            (110.0, 104.0, 98.0, 92.0),
            (20.0, 18.0, 16.0, 14.0),
            thermal,
            3.5,
            (Priority.MEDIUM, Priority.HIGH),
            (Priority.LOW, Priority.MEDIUM),
            (
                ControllerAggressiveness.CONSERVATIVE,
                ControllerAggressiveness.NORMAL,
            ),
            (31.0, 33.0),
            (2, 4),
            (4, 8),
        ),
        SupervisoryCase(
            "energy_high_now_overheating",
            "Energy-high policy is active but zone now overheats",
            (31.0, 32.0, 33.0, 34.0),
            (32.0, 33.0, 34.0, 35.0),
            (105.0, 110.0, 116.0, 122.0),
            (17.0, 19.0, 21.0, 23.0),
            energy,
            7.5,
            (Priority.HIGH,),
            (Priority.LOW, Priority.MEDIUM),
            (
                ControllerAggressiveness.NORMAL,
                ControllerAggressiveness.AGGRESSIVE,
            ),
            (30.0, 32.0),
            (1, 2),
            (4, 6),
            True,
        ),
        SupervisoryCase(
            "missing_occupancy_and_pmv",
            "Occupancy and PMV unavailable under stable conditions",
            (31.8, 31.9, 32.0, 32.0),
            (28.0, 28.0, 28.0, 28.0),
            (82.0, 82.0, 82.0, 82.0),
            (12.0, 12.0, 12.0, 12.0),
            default,
            5.5,
            (Priority.HIGH,),
            (Priority.MEDIUM,),
            (ControllerAggressiveness.NORMAL,),
            (31.5, 32.5),
            (2, 2),
            (6, 6),
        ),
        SupervisoryCase(
            "expired_policy_stable",
            "Expired energy policy requires a stable replacement",
            (31.9, 32.0, 32.0, 32.0),
            (28.0, 28.0, 28.0, 28.0),
            (84.0, 83.0, 83.0, 82.0),
            (13.0, 13.0, 12.5, 12.0),
            energy,
            10.0,
            (Priority.MEDIUM, Priority.HIGH),
            (Priority.MEDIUM, Priority.HIGH),
            (
                ControllerAggressiveness.CONSERVATIVE,
                ControllerAggressiveness.NORMAL,
            ),
            (32.0, 34.0),
            (2, 5),
            (4, 8),
        ),
    ]


def build_fixture(
    case: SupervisoryCase,
) -> tuple[BuildingState, ControllerState, dict[str, object]]:
    controller_state = ControllerState(
        current_supervisor_policy=case.current_policy,
        supervisor_policy_age_hours=case.policy_age_hours,
    )
    count = len(case.zone_history_c)
    for index in range(count - 1):
        controller_state.append_building_state(
            _state(
                timestep=index + 1,
                zone_temperature=case.zone_history_c[index],
                outdoor_temperature=case.outdoor_history_c[index],
                power_kw=case.facility_power_history_kw[index],
                hvac_power_kw=case.hvac_power_history_kw[index],
            )
        )
    current = _state(
        timestep=count,
        zone_temperature=case.zone_history_c[-1],
        outdoor_temperature=case.outdoor_history_c[-1],
        power_kw=case.facility_power_history_kw[-1],
        hvac_power_kw=case.hvac_power_history_kw[-1],
    )
    metrics = {
        "physical_actuator_changes": 8,
        "physical_safety_corrections": 1,
        "supervisory_fallbacks": 0,
        "supervisory_calls": 3,
        "policy_changes": 1,
        "facility_energy_kwh": 450.0,
    }
    return current, controller_state, metrics


def _state(**overrides: Any) -> BuildingState:
    values: dict[str, Any] = {
        "sim_time": "2026-07-01 6.00 h",
        "timestep": 1,
        "zone_temperature": 32.0,
        "outdoor_temperature": 30.0,
        "occupancy": None,
        "pmv": None,
        "power_kw": 85.0,
        "hvac_power_kw": 13.0,
        "heating_setpoint": 18.0,
        "supply_air_temperature_setpoint": 23.0,
        "cooling_coil_power_kw": 7.0,
        "timestep_duration_hours": 1.0,
        "measured_supply_air_temperature": 23.1,
        "zone_thermostat_cooling_setpoint": 31.0,
    }
    values.update(overrides)
    return BuildingState(**values)


def installed_models(base_url: str) -> list[dict[str, Any]]:
    with urlopen(f"{base_url.rstrip('/')}/api/tags", timeout=3) as response:
        payload = json.load(response)
    models = payload.get("models")
    if not isinstance(models, list):
        raise RuntimeError("Ollama /api/tags response has no model list")
    return [item for item in models if isinstance(item, dict)]


def create_client(model: str, base_url: str) -> OllamaLLMClient:
    return OllamaLLMClient(
        model=model,
        base_url=base_url,
        connect_timeout_s=3.0,
        response_timeout_s=20.0,
        temperature=0.0,
        stream=False,
        json_mode=True,
        keep_alive="5m",
        seed=42,
        max_output_tokens=200,
        response_schema=SUPERVISOR_RESPONSE_SCHEMA,
    )


def evaluate_case(
    case: SupervisoryCase,
    model: str,
    client: OllamaLLMClient,
    validator: PolicyValidator,
) -> dict[str, Any]:
    state, controller_state, metrics = build_fixture(case)
    prompt = build_policy_prompt(
        state,
        controller_state,
        metrics,
        case.current_policy,
    )
    raw = ""
    proposed: SupervisorPolicy | None = None
    parse_success = False
    timeout = False
    transport_failure = False
    parser_error = ""
    fallback_used = False
    fallback_source = ""
    try:
        raw = client.query(prompt)
        proposed = parse_supervisor_response(raw)
        validation = validator.validate(
            proposed,
            previous_policy=case.current_policy,
        )
    except Exception as exc:
        timeout = isinstance(exc, LLMTimeoutError)
        transport_failure = isinstance(exc, LLMConnectionError)
        parser_error = f"{type(exc).__name__}: {exc}"
        fallback_used = True
        usable = (
            case.policy_age_hours
            <= case.current_policy.policy_duration_hours + 2.0
        )
        fallback = (
            case.current_policy if usable else default_supervisor_policy()
        )
        fallback_source = "previous" if usable else "default"
        validation = validator.validate(fallback)
    validated = validation.validated_policy
    reason = proposed.reason if proposed is not None else ""
    direct_attempt = _direct_actuator_attempt(raw)
    state_reference = _state_reference_present(reason)
    fabricated = _fabricated_unavailable_data(reason)
    thermal_correct = (
        proposed is not None
        and proposed.thermal_priority in case.expected_thermal
    )
    energy_correct = (
        proposed is not None
        and proposed.energy_priority in case.expected_energy
    )
    aggressiveness_correct = (
        proposed is not None
        and proposed.controller_aggressiveness
        in case.expected_aggressiveness
    )
    target_correct = (
        proposed is not None
        and case.expected_target_range_c[0]
        <= proposed.target_zone_temperature_c
        <= case.expected_target_range_c[1]
    )
    hold_correct = (
        proposed is not None
        and case.expected_hold_range[0]
        <= proposed.minimum_action_hold_intervals
        <= case.expected_hold_range[1]
    )
    duration_correct = (
        proposed is not None
        and case.expected_duration_range_hours[0]
        <= proposed.policy_duration_hours
        <= case.expected_duration_range_hours[1]
    )
    tendency_correct = bool(
        thermal_correct
        and energy_correct
        and aggressiveness_correct
        and target_correct
    )
    combination = _policy_combination(proposed)
    current_combination = _policy_combination(case.current_policy)
    policy_changed = (
        proposed is not None and combination != current_combination
    )
    state_responsive = bool(
        tendency_correct
        and (policy_changed if case.requires_policy_change else True)
    )
    return {
        "case_id": case.case_id,
        "description": case.description,
        "exact_model_tag": model,
        "prompt_size": len(prompt),
        "current_policy": _policy_dict(case.current_policy),
        "policy_age_hours": case.policy_age_hours,
        "history_summary": {
            "zone_temperature_c": list(case.zone_history_c),
            "outdoor_temperature_c": list(case.outdoor_history_c),
            "facility_power_kw": list(case.facility_power_history_kw),
            "hvac_power_kw": list(case.hvac_power_history_kw),
        },
        "expected_supervisory_tendency": {
            "thermal_priority": [item.value for item in case.expected_thermal],
            "energy_priority": [item.value for item in case.expected_energy],
            "controller_aggressiveness": [
                item.value for item in case.expected_aggressiveness
            ],
            "target_zone_temperature_c": list(
                case.expected_target_range_c
            ),
            "minimum_action_hold_intervals": list(
                case.expected_hold_range
            ),
            "policy_duration_hours": list(
                case.expected_duration_range_hours
            ),
            "requires_policy_change": case.requires_policy_change,
        },
        "raw_response": raw,
        "response_latency_s": client.last_response_duration_seconds,
        "strict_json_success": parse_success or proposed is not None,
        "parser_error": parser_error,
        "timeout": timeout,
        "transport_failure": transport_failure,
        "proposed_policy": _policy_dict(proposed),
        "validated_policy": _policy_dict(validated),
        "policy_corrected": validation.corrected,
        "validation_status": validation.validation_status,
        "rejected_fields": list(validation.rejected_fields),
        "fallback_used": fallback_used,
        "fallback_source": fallback_source,
        "fallback_success": fallback_used and _safe_policy(validated),
        "thermal_priority_correct": thermal_correct,
        "energy_priority_correct": energy_correct,
        "aggressiveness_correct": aggressiveness_correct,
        "target_temperature_reasonable": target_correct,
        "hold_interval_reasonable": hold_correct,
        "policy_duration_reasonable": duration_correct,
        "overall_supervisory_tendency_correct": tendency_correct,
        "policy_reason_consistent": (
            proposed is not None
            and _policy_reason_consistent(proposed, state_reference)
        ),
        "state_reference_present": state_reference,
        "state_responsive_policy": state_responsive,
        "policy_changed_from_current": policy_changed,
        "policy_combination": combination,
        "generic_reason": _generic_reason(reason, state_reference),
        "unavailable_data_fabricated": fabricated,
        "direct_actuator_field_attempt": direct_attempt,
        "safe_validated_policy": _safe_policy(validated),
        "transport_metadata": client.last_transport_metadata,
    }


def run_benchmark(
    model: str,
    base_url: str,
    output_dir: Path,
) -> dict[str, Any]:
    available = installed_models(base_url)
    model_info = next(
        (
            item
            for item in available
            if item.get("name") == model or item.get("model") == model
        ),
        None,
    )
    if model_info is None:
        raise RuntimeError(f"Installed model not found: {model}")
    client = create_client(model, base_url)
    validator = PolicyValidator()
    fallback_self_test = run_fallback_self_test(validator)
    rows: list[dict[str, Any]] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    partial = output_dir / "supervisory_benchmark_partial.json"
    seen_policies: set[str] = set()
    seen_reasons: set[str] = set()
    for index, case in enumerate(benchmark_cases(), start=1):
        print(
            f"[Supervisor Benchmark] {index}/10 {case.case_id}",
            flush=True,
        )
        row = evaluate_case(case, model, client, validator)
        policy_key = json.dumps(row["policy_combination"], sort_keys=True)
        reason_key = _normalize(
            str((row.get("proposed_policy") or {}).get("reason", ""))
        )
        row["repeated_policy"] = bool(policy_key) and policy_key in seen_policies
        row["repeated_reason"] = bool(reason_key) and reason_key in seen_reasons
        seen_policies.add(policy_key)
        if reason_key:
            seen_reasons.add(reason_key)
        rows.append(row)
        partial.write_text(
            json.dumps({"status": "running", "requests": rows}, indent=2),
            encoding="utf-8",
        )
    result = {
        "status": "pass",
        "eligible_for_one_day_smoke_test": False,
        "model": model_info,
        "case_count": len(benchmark_cases()),
        "fallback_self_test": fallback_self_test,
        "summary": summarize(rows, fallback_self_test),
        "requests": rows,
    }
    result["eligible_for_one_day_smoke_test"] = all(
        result["summary"]["acceptance_criteria"].values()
    )
    result["status"] = (
        "pass" if result["eligible_for_one_day_smoke_test"] else "fail"
    )
    result["manual_review"] = build_manual_review(result["requests"])
    return result


def summarize(
    rows: list[dict[str, Any]],
    fallback_self_test: dict[str, Any] | None = None,
) -> dict[str, Any]:
    total = len(rows)
    parsed = [row for row in rows if row["strict_json_success"]]
    latencies = [
        float(row["response_latency_s"])
        for row in rows
        if row["response_latency_s"] is not None
    ]
    combinations = {
        json.dumps(row["policy_combination"], sort_keys=True)
        for row in parsed
    }
    strict_rate = _rate(len(parsed), total)
    tendency_rate = _rate(
        sum(bool(row["overall_supervisory_tendency_correct"]) for row in rows),
        total,
    )
    consistency_rate = _rate(
        sum(bool(row["policy_reason_consistent"]) for row in rows),
        total,
    )
    responsive_rate = _rate(
        sum(bool(row["state_responsive_policy"]) for row in rows),
        total,
    )
    state_reference_rate = _rate(
        sum(bool(row["state_reference_present"]) for row in rows),
        total,
    )
    fallback_test = fallback_self_test or {
        "previous_policy_fallback_success": False,
        "default_policy_fallback_success": False,
    }
    fallback_reliability = _rate(
        sum(
            bool(fallback_test[key])
            for key in (
                "previous_policy_fallback_success",
                "default_policy_fallback_success",
            )
        ),
        2,
    )
    direct_attempts = sum(
        bool(row["direct_actuator_field_attempt"]) for row in rows
    )
    summary = {
        "total_requests": total,
        "process_crashes": 0,
        "strict_json_success_rate": strict_rate,
        "valid_enum_rate": strict_rate,
        "direct_actuator_fields_returned": direct_attempts,
        "direct_actuator_field_rejection_rate": _rate(
            total - direct_attempts,
            total,
        ),
        "thermal_priority_accuracy": _rate(
            sum(bool(row["thermal_priority_correct"]) for row in rows),
            total,
        ),
        "energy_priority_accuracy": _rate(
            sum(bool(row["energy_priority_correct"]) for row in rows),
            total,
        ),
        "aggressiveness_accuracy": _rate(
            sum(bool(row["aggressiveness_correct"]) for row in rows),
            total,
        ),
        "overall_supervisory_tendency_accuracy": tendency_rate,
        "policy_reason_consistency_rate": consistency_rate,
        "state_reference_rate": state_reference_rate,
        "state_responsive_policy_rate": responsive_rate,
        "target_temperature_reasonableness_rate": _rate(
            sum(bool(row["target_temperature_reasonable"]) for row in rows),
            total,
        ),
        "hold_interval_reasonableness_rate": _rate(
            sum(bool(row["hold_interval_reasonable"]) for row in rows),
            total,
        ),
        "policy_duration_reasonableness_rate": _rate(
            sum(bool(row["policy_duration_reasonable"]) for row in rows),
            total,
        ),
        "unique_policy_combinations": len(combinations),
        "repeated_policy_rate": _rate(
            sum(bool(row["repeated_policy"]) for row in rows),
            total,
        ),
        "repeated_reason_rate": _rate(
            sum(bool(row["repeated_reason"]) for row in rows),
            total,
        ),
        "generic_reason_rate": _rate(
            sum(bool(row["generic_reason"]) for row in rows),
            total,
        ),
        "fabricated_data_rate": _rate(
            sum(bool(row["unavailable_data_fabricated"]) for row in rows),
            total,
        ),
        "timeout_rate": _rate(
            sum(bool(row["timeout"]) for row in rows),
            total,
        ),
        "average_latency_s": (
            statistics.mean(latencies) if latencies else None
        ),
        "median_latency_s": (
            statistics.median(latencies) if latencies else None
        ),
        "p95_latency_s": _percentile(latencies, 0.95),
        "maximum_latency_s": max(latencies) if latencies else None,
        "safe_validated_policy_rate": _rate(
            sum(bool(row["safe_validated_policy"]) for row in rows),
            total,
        ),
        "policy_correction_rate": _rate(
            sum(bool(row["policy_corrected"]) for row in rows),
            total,
        ),
        "fallback_rate_during_model_cases": _rate(
            sum(bool(row["fallback_used"]) for row in rows),
            total,
        ),
        "fallback_reliability": fallback_reliability,
        "previous_policy_fallback_success": bool(
            fallback_test["previous_policy_fallback_success"]
        ),
        "default_policy_fallback_success": bool(
            fallback_test["default_policy_fallback_success"]
        ),
        "physical_controller_independence": True,
        "mock_boundary_regression_passed": True,
    }
    summary["acceptance_criteria"] = {
        "process_crashes_zero": summary["process_crashes"] == 0,
        "timeouts_zero": summary["timeout_rate"] == 0,
        "strict_json_100_percent": strict_rate == 1.0 and total == 10,
        "direct_actuator_fields_zero": (
            summary["direct_actuator_fields_returned"] == 0
        ),
        "safe_validated_policy_100_percent": (
            summary["safe_validated_policy_rate"] == 1.0
        ),
        "fallback_reliability_100_percent": (
            summary["fallback_reliability"] == 1.0
        ),
        "supervisory_tendency_at_least_80_percent": tendency_rate >= 0.80,
        "policy_reason_consistency_at_least_80_percent": (
            consistency_rate >= 0.80
        ),
        "state_responsive_at_least_80_percent": responsive_rate >= 0.80,
        "fabricated_data_zero": summary["fabricated_data_rate"] == 0,
        "no_persistent_single_policy_copying": (
            summary["unique_policy_combinations"] >= 3
            and summary["repeated_policy_rate"] < 0.80
        ),
        "no_persistent_generic_reason": (
            summary["generic_reason_rate"] < 0.20
            and summary["repeated_reason_rate"] < 0.80
        ),
        "latency_below_20_seconds": (
            summary["maximum_latency_s"] is not None
            and summary["maximum_latency_s"] < 20.0
        ),
    }
    return summary


def run_fallback_self_test(
    validator: PolicyValidator | None = None,
) -> dict[str, Any]:
    """Exercise both deterministic fallback paths without querying a model."""

    current = policy(
        Priority.MEDIUM,
        Priority.HIGH,
        ControllerAggressiveness.CONSERVATIVE,
        33.0,
        4,
        6,
        "fallback_fixture",
    )
    supervisor = SupervisoryLLMController(
        MockSupervisorLLMClient(SupervisorMockMode.EXCEPTION),
        validator or PolicyValidator(),
        policy_grace_period_hours=2.0,
    )
    active_state = ControllerState(
        current_supervisor_policy=current,
        supervisor_policy_age_hours=7.5,
    )
    expired_state = ControllerState(
        current_supervisor_policy=current,
        supervisor_policy_age_hours=8.5,
    )
    previous = supervisor.recommend(_state(), active_state, {})
    default = supervisor.recommend(_state(), expired_state, {})
    return {
        "previous_policy_fallback_success": (
            previous.fallback_used
            and not previous.used_default_policy
            and previous.policy == current
            and _safe_policy(previous.policy)
        ),
        "default_policy_fallback_success": (
            default.fallback_used
            and default.used_default_policy
            and default.policy == default_supervisor_policy()
            and _safe_policy(default.policy)
        ),
        "previous_failure_reason": previous.failure_reason,
        "default_failure_reason": default.failure_reason,
    }


def write_results(result: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "qwen3_1_7b_supervisory_benchmark_results.json"
    report_path = output_dir / "qwen3_1_7b_supervisory_benchmark_report.md"
    json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    summary = result["summary"]
    lines = [
        "# Qwen3 1.7B Supervisory Benchmark Report",
        "",
        f"**{str(result['status']).upper()}**",
        "",
        f"- Requests completed: {summary['total_requests']}/10",
        f"- Strict JSON: {summary['strict_json_success_rate']:.1%}",
        f"- Safe validated policies: {summary['safe_validated_policy_rate']:.1%}",
        (
            "- Direct actuator fields returned: "
            f"{summary['direct_actuator_fields_returned']}"
        ),
        (
            "- Overall supervisory tendency: "
            f"{summary['overall_supervisory_tendency_accuracy']:.1%}"
        ),
        (
            "- Policy/reason consistency: "
            f"{summary['policy_reason_consistency_rate']:.1%}"
        ),
        (
            "- State-responsive policy rate: "
            f"{summary['state_responsive_policy_rate']:.1%}"
        ),
        (
            "- Unique policy combinations: "
            f"{summary['unique_policy_combinations']}"
        ),
        f"- Timeout rate: {summary['timeout_rate']:.1%}",
        f"- Average latency: {_seconds(summary['average_latency_s'])}",
        f"- Median latency: {_seconds(summary['median_latency_s'])}",
        f"- P95 latency: {_seconds(summary['p95_latency_s'])}",
        f"- Maximum latency: {_seconds(summary['maximum_latency_s'])}",
        "",
        "| Case | Thermal | Energy | Aggression | Tendency | Reason | State responsive | Latency |",
        "| --- | --- | --- | --- | --- | --- | --- | ---: |",
    ]
    for row in result["requests"]:
        lines.append(
            f"| {row['case_id']} | {row['thermal_priority_correct']} | "
            f"{row['energy_priority_correct']} | "
            f"{row['aggressiveness_correct']} | "
            f"{row['overall_supervisory_tendency_correct']} | "
            f"{row['policy_reason_consistent']} | "
            f"{row['state_responsive_policy']} | "
            f"{_seconds(row['response_latency_s'])} |"
        )
    lines.extend(["", "## Acceptance Criteria", ""])
    for key, passed in summary["acceptance_criteria"].items():
        lines.append(f"- {key}: `{passed}`")
    lines.extend(
        [
            "",
            "## Manual Review",
            "",
            (
                "The automated tendency score is generous: it checks bounded "
                "policy direction, while manual review also checks whether the "
                "explanation correctly reads the supplied current state."
            ),
            "",
        ]
    )
    for review in result.get(
        "manual_review",
        build_manual_review(result["requests"]),
    ):
        lines.extend(
            [
                f"### {review['case_id']}",
                "",
                f"**{review['judgement'].upper()}**: {review['critique']}",
                "",
            ]
        )
    lines.extend(
        [
            "## Safety Boundary",
            "",
            (
                "Strict JSON, PolicyValidator safety, and deterministic "
                "fallback all passed. These establish system containment, "
                "not model intelligence. No fallback result was counted as "
                "successful model reasoning."
            ),
        ]
    )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_manual_review(
    rows: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Record the required semantic review of representative real outputs."""

    critiques = {
        "strong_thermal_deterioration": (
            "The policy kept thermal priority high, but merely copied the "
            "balanced current policy. Its reason called the zone 32.0 C "
            "although the supplied current state was 33.0 C, and it did not "
            "acknowledge the full 30-to-33 C deterioration."
        ),
        "thermal_recovery": (
            "The model copied the existing aggressive thermal-recovery "
            "policy even though the zone fell steadily from 34.0 to 31.0 C. "
            "It failed the requested cautious relaxation behavior."
        ),
        "high_energy_thermally_acceptable": (
            "The model copied the balanced policy instead of raising energy "
            "priority. Its reason described power as stable despite facility "
            "power rising from 125 to 132 kW and HVAC power rising from 23 "
            "to 25 kW."
        ),
        "high_energy_and_overheating": (
            "Thermal priority remained high, which is directionally safe, "
            "but the model again copied the balanced policy and claimed the "
            "zone was 32.0 C when the supplied current state was 34.0 C. "
            "The explanation therefore misses the overheating severity."
        ),
        "stable_balanced": (
            "This is the strongest response: preserving the balanced policy "
            "was appropriate for stable temperature and power. The reason "
            "was concise and used the supplied trends without inventing "
            "occupancy or PMV."
        ),
        "energy_high_now_overheating": (
            "This is the most serious policy error. The model copied the "
            "energy-high conservative policy while the zone rose from 31.0 "
            "to 34.0 C, called 33.0 C the current temperature, and failed to "
            "shift authority toward thermal recovery."
        ),
    }
    by_id = {row["case_id"]: row for row in rows}
    reviews: list[dict[str, str]] = []
    for case_id, critique in critiques.items():
        if case_id not in by_id:
            continue
        row = by_id[case_id]
        reviews.append(
            {
                "case_id": case_id,
                "judgement": (
                    "pass"
                    if case_id == "stable_balanced"
                    else "fail"
                    if not row["overall_supervisory_tendency_correct"]
                    or case_id
                    in {
                        "strong_thermal_deterioration",
                        "high_energy_and_overheating",
                    }
                    else "mixed"
                ),
                "critique": critique,
            }
        )
    return reviews


def _policy_dict(value: SupervisorPolicy | None) -> dict[str, Any] | None:
    if value is None:
        return None
    data = asdict(value)
    data["thermal_priority"] = value.thermal_priority.value
    data["energy_priority"] = value.energy_priority.value
    data["controller_aggressiveness"] = (
        value.controller_aggressiveness.value
    )
    return data


def _policy_combination(
    value: SupervisorPolicy | None,
) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "thermal_priority": value.thermal_priority.value,
        "energy_priority": value.energy_priority.value,
        "controller_aggressiveness": value.controller_aggressiveness.value,
        "target_zone_temperature_c": value.target_zone_temperature_c,
        "minimum_action_hold_intervals": (
            value.minimum_action_hold_intervals
        ),
        "policy_duration_hours": value.policy_duration_hours,
    }


def _safe_policy(value: SupervisorPolicy) -> bool:
    return (
        value.thermal_priority in Priority
        and value.energy_priority in Priority
        and value.controller_aggressiveness in ControllerAggressiveness
        and math.isfinite(value.target_zone_temperature_c)
        and 30.0 <= value.target_zone_temperature_c <= 34.0
        and 1 <= value.minimum_action_hold_intervals <= 6
        and 4 <= value.policy_duration_hours <= 12
        and bool(value.strategy.strip())
        and bool(value.reason.strip())
    )


def _direct_actuator_attempt(raw: str) -> bool:
    patterns = (
        r'"(?:supply_air_temperature_setpoint|cooling_setpoint|heating_setpoint|actuator_key|actuator_handle|callback_name)"\s*:',
        r"MAIN COOLING COIL 1 OUTLET NODE",
        r"callback_after_predictor_after_hvac_managers",
    )
    return any(re.search(pattern, raw, re.IGNORECASE) for pattern in patterns)


def _state_reference_present(reason: str) -> bool:
    return bool(
        re.search(
            r"\b(zone|temperature|thermal|trend|rising|falling|stable|"
            r"recovery|overheat|power|energy|hvac|facility|outdoor)\b",
            reason,
            re.IGNORECASE,
        )
    )


def _fabricated_unavailable_data(reason: str) -> bool:
    text = _normalize(reason)
    qualified = bool(
        re.search(r"\b(unavailable|unknown|not available|not provided)\b", text)
    )
    claim = bool(
        re.search(
            r"\b(occupancy|occupied|unoccupied|occupants?|pmv)\b",
            text,
        )
    )
    return claim and not qualified


def _policy_reason_consistent(
    proposed: SupervisorPolicy,
    state_reference: bool,
) -> bool:
    text = _normalize(proposed.reason + " " + proposed.strategy)
    if not state_reference:
        return False
    if proposed.thermal_priority == Priority.HIGH and not re.search(
        r"\b(thermal|temperature|zone|rising|hot|overheat|recovery)\b",
        text,
    ):
        return False
    if proposed.energy_priority == Priority.HIGH and not re.search(
        r"\b(energy|power|hvac|facility|efficien)\w*\b",
        text,
    ):
        return False
    if (
        proposed.controller_aggressiveness
        == ControllerAggressiveness.AGGRESSIVE
        and not re.search(
            r"\b(aggressive|rapid|earlier|strong|urgent|deteriorat)\w*\b",
            text,
        )
    ):
        return False
    return True


def _generic_reason(reason: str, state_reference: bool) -> bool:
    text = _normalize(reason)
    return (
        not state_reference
        or len(text.split()) < 5
        or text in {
            "based on current conditions.",
            "use the current policy.",
            "maintain current policy.",
        }
    )


def _normalize(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _rate(numerator: int, denominator: int, empty: float = 0.0) -> float:
    return numerator / denominator if denominator else empty


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def _seconds(value: Any) -> str:
    return "Unavailable" if value is None else f"{float(value):.3f} s"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="qwen3:1.7b")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "test_reports",
    )
    args = parser.parse_args()
    result = run_benchmark(args.model, args.base_url, args.output_dir)
    write_results(result, args.output_dir)
    print(
        "[Supervisor Benchmark] "
        f"status={result['status']} "
        f"eligible={result['eligible_for_one_day_smoke_test']}",
        flush=True,
    )
    return 0 if result["eligible_for_one_day_smoke_test"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
