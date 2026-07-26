"""Deterministic real-Ollama benchmark that runs without EnergyPlus."""

from __future__ import annotations

import argparse
import json
import math
import platform
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

from controller.action import ControlAction  # noqa: E402
from controller.controller_state import ControllerState  # noqa: E402
from controller.output_parser import parse_response  # noqa: E402
from controller.prompt_builder import build_prompt  # noqa: E402
from controller.rule_controller import RuleController  # noqa: E402
from controller.safety import SafetyValidator  # noqa: E402
from controller.state import BuildingState  # noqa: E402
from llm.client import (  # noqa: E402
    LLMConnectionError,
    LLMTimeoutError,
    OllamaLLMClient,
)
from response_semantics import (  # noqa: E402
    fabricates_unavailable_data,
    generic_reason,
    normalize_text,
    previous_action_reference_present,
    reason_directions,
    state_reference_present,
)


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    description: str
    zone_temperature_c: float
    previous_zone_temperature_c: float | None
    one_hour_zone_temperature_c: float | None
    outdoor_temperature_c: float
    facility_power_kw: float
    one_hour_facility_power_kw: float | None
    hvac_power_kw: float
    previous_setpoint_c: float
    expected_directions: tuple[str, ...]
    no_change_expected: bool = False
    occupancy: float | None = None
    pmv: float | None = None
    previous_strategy: str = "benchmark_previous"
    previous_reason: str = "Previous validated benchmark action."
    previous_validation_status: str = "valid"


def benchmark_cases() -> list[BenchmarkCase]:
    """Return the fixed benchmark corpus shared by every model."""

    return [
        BenchmarkCase("hot_rising", "Very hot and rising zone", 33, 32, 30, 38, 105, 90, 18, 24, ("lower",)),
        BenchmarkCase("hot_stable", "Hot and stable zone", 31, 31, 31, 34, 95, 94, 15, 23, ("lower", "hold")),
        BenchmarkCase("hot_falling", "Hot but rapidly falling zone", 30, 29.5, 33, 30, 88, 100, 13, 22, ("hold", "higher")),
        BenchmarkCase("moderate_high_hvac", "Moderate zone with high HVAC power", 27, 27, 27, 28, 100, 92, 22, 23, ("hold", "higher")),
        BenchmarkCase("moderate_low_hvac", "Moderate zone with low HVAC power", 27, 27, 27, 25, 72, 74, 5, 24, ("hold",), True),
        BenchmarkCase("previous_22", "Previous supply-air target is 22 C", 32, 31.5, 30, 36, 98, 91, 17, 22, ("hold",)),
        BenchmarkCase("previous_23", "Previous supply-air target is 23 C", 32, 31, 29, 36, 99, 88, 17, 23, ("lower",)),
        BenchmarkCase("previous_24", "Previous supply-air target is 24 C", 30, 30, 29.5, 32, 91, 89, 14, 24, ("lower", "hold")),
        BenchmarkCase("previous_25", "Previous supply-air target is 25 C", 26, 26, 26, 22, 74, 75, 6, 25, ("hold",), True),
        BenchmarkCase("power_rising", "Facility and HVAC power are rising", 27, 27, 27, 28, 104, 80, 21, 23, ("hold", "higher")),
        BenchmarkCase("power_falling", "Power falling while hot zone rises", 31, 30.5, 29, 34, 88, 110, 13, 24, ("lower",)),
        BenchmarkCase("hot_outdoor", "High outdoor temperature and hot zone", 31, 30.5, 29, 41, 101, 93, 18, 24, ("lower",)),
        BenchmarkCase("cool_outdoor", "Lower outdoor temperature and controlled zone", 26, 26, 26, 15, 70, 76, 5, 23, ("hold", "higher")),
        BenchmarkCase("missing_occupancy", "Occupancy unavailable", 31, 30.5, 29, 34, 94, 88, 16, 24, ("lower",), occupancy=None),
        BenchmarkCase("missing_pmv", "PMV unavailable under stable conditions", 26, 26, 26, 22, 73, 73, 6, 24, ("hold",), True, pmv=None),
        BenchmarkCase("missing_power_trend", "One-hour power trend unavailable", 26, 26, 26, 24, 75, None, 7, 24, ("hold",), True),
        BenchmarkCase("missing_temperature_trend", "Temperature trend unavailable", 31, None, None, 33, 92, 88, 15, 24, ("lower",)),
        BenchmarkCase(
            "previous_fallback",
            "Previous action came from fallback",
            30,
            29.5,
            32,
            29,
            87,
            98,
            12,
            22,
            ("hold", "higher"),
            previous_strategy="increase_cooling",
            previous_reason="RuleController fallback after transport failure.",
            previous_validation_status="valid fallback action",
        ),
        BenchmarkCase(
            "previous_safety_correction",
            "Previous action was safety corrected",
            27,
            27,
            27,
            27,
            82,
            82,
            9,
            24,
            ("hold",),
            True,
            previous_strategy="rate_limited",
            previous_reason="Previous model request exceeded the rate limit.",
            previous_validation_status="rate-limited to 24.0 C",
        ),
        BenchmarkCase("stable_hold", "Stable state where no change is desirable", 26.5, 26.5, 26.5, 23, 76, 76, 7, 23, ("hold",), True),
    ]


def build_fixture(case: BenchmarkCase) -> tuple[BuildingState, ControllerState]:
    state = _state(
        timestep=6,
        zone_temperature=case.zone_temperature_c,
        outdoor_temperature=case.outdoor_temperature_c,
        power_kw=case.facility_power_kw,
        hvac_power_kw=case.hvac_power_kw,
        occupancy=case.occupancy,
        pmv=case.pmv,
        supply_air_temperature_setpoint=case.previous_setpoint_c,
    )
    previous_action = ControlAction(
        case.previous_setpoint_c,
        case.previous_strategy,
        case.previous_reason,
    )
    controller_state = ControllerState(
        previous_action=previous_action,
        timestep=5,
        last_strategy=case.previous_strategy,
        previous_validation_status=case.previous_validation_status,
    )
    if case.previous_zone_temperature_c is not None:
        start_temp = (
            case.one_hour_zone_temperature_c
            if case.one_hour_zone_temperature_c is not None
            else case.previous_zone_temperature_c
        )
        start_power = (
            case.one_hour_facility_power_kw
            if case.one_hour_facility_power_kw is not None
            else None
        )
        for index in range(6):
            fraction = index / 5
            temperature = start_temp + (
                case.previous_zone_temperature_c - start_temp
            ) * fraction
            power = (
                None
                if start_power is None
                else start_power
                + (case.facility_power_kw - start_power) * fraction
            )
            controller_state.append_building_state(
                _state(
                    timestep=index,
                    zone_temperature=temperature,
                    outdoor_temperature=case.outdoor_temperature_c,
                    power_kw=power,
                    hvac_power_kw=case.hvac_power_kw,
                    occupancy=case.occupancy,
                    pmv=case.pmv,
                    supply_air_temperature_setpoint=case.previous_setpoint_c,
                )
            )
    return state, controller_state


def _state(**overrides: Any) -> BuildingState:
    values: dict[str, Any] = {
        "sim_time": "2026-07-01 1.00 h",
        "timestep": 1,
        "zone_temperature": 27.0,
        "outdoor_temperature": 25.0,
        "occupancy": None,
        "pmv": None,
        "power_kw": 80.0,
        "hvac_power_kw": 10.0,
        "heating_setpoint": 18.0,
        "supply_air_temperature_setpoint": 23.0,
        "cooling_coil_power_kw": 6.0,
        "timestep_duration_hours": 1 / 6,
        "measured_supply_air_temperature": 23.1,
        "zone_thermostat_cooling_setpoint": 31.0,
    }
    values.update(overrides)
    return BuildingState(**values)


def installed_models(base_url: str) -> list[dict[str, Any]]:
    with urlopen(f"{base_url.rstrip('/')}/api/tags", timeout=3) as response:
        envelope = json.load(response)
    models = envelope.get("models")
    if not isinstance(models, list):
        raise RuntimeError("Ollama /api/tags response is missing models")
    return [item for item in models if isinstance(item, dict)]


def run_model(
    model_info: dict[str, Any],
    base_url: str,
    response_timeout_s: float,
    acceptable_latency_s: float,
    output_path: Path,
) -> dict[str, Any]:
    model_name = str(model_info.get("name") or model_info.get("model"))
    client = OllamaLLMClient(
        model=model_name,
        base_url=base_url,
        connect_timeout_s=3,
        response_timeout_s=response_timeout_s,
        temperature=0,
        stream=False,
        json_mode=True,
        keep_alive="5m",
    )
    validator = SafetyValidator()
    fallback = RuleController()
    requests: list[dict[str, Any]] = []

    for index, case in enumerate(benchmark_cases(), start=1):
        print(
            f"[Benchmark] {model_name}: {index}/20 {case.case_id}",
            flush=True,
        )
        state, controller_state = build_fixture(case)
        prompt = build_prompt(state, controller_state)
        raw_response = ""
        parsed_action: ControlAction | None = None
        requested_action: ControlAction
        parse_success = False
        timeout = False
        transport_failure = False
        fallback_used = False
        fallback_success = False
        failure_reason = ""

        try:
            raw_response = client.query(prompt)
            parsed_action = parse_response(raw_response)
            requested_action = parsed_action
            parse_success = True
        except Exception as exc:
            timeout = isinstance(exc, LLMTimeoutError)
            transport_failure = isinstance(exc, LLMConnectionError)
            fallback_used = True
            failure_reason = f"{type(exc).__name__}: {exc}"
            requested_action = fallback.decide(state, controller_state)
            fallback_success = True

        validation = validator.validate(
            requested_action,
            previous_action=controller_state.previous_action,
        )
        requested_value = (
            parsed_action.supply_air_temperature_setpoint
            if parsed_action is not None
            else None
        )
        actual_direction = (
            _direction(requested_value, case.previous_setpoint_c)
            if requested_value is not None
            else "fallback"
        )
        direction_correct = (
            actual_direction in case.expected_directions
            if parse_success
            else False
        )
        reason = parsed_action.reason if parsed_action is not None else ""
        detected_reason_directions = reason_directions(reason)
        reason_direction = (
            next(iter(detected_reason_directions))
            if len(detected_reason_directions) == 1
            else None
        )
        has_state_reference = state_reference_present(reason, case)
        normalized_output = normalize_text(raw_response)
        normalized_reason = normalize_text(reason)
        final_change = abs(
            validation.action.supply_air_temperature_setpoint
            - case.previous_setpoint_c
        )
        requests.append(
            {
                "model_name": model_name,
                "test_case_id": case.case_id,
                "description": case.description,
                "prompt_length": len(prompt),
                "raw_response": raw_response,
                "response_latency_s": client.last_response_duration_seconds,
                "timeout": timeout,
                "transport_failure": transport_failure,
                "failure_reason": failure_reason,
                "strict_json_parse_success": parse_success,
                "parsed_requested_setpoint_c": requested_value,
                "validated_setpoint_c": (
                    validation.action.supply_air_temperature_setpoint
                ),
                "safety_corrected": validation.corrected,
                "validation_status": validation.status,
                "fallback_used": fallback_used,
                "fallback_success": fallback_success,
                "strategy": validation.action.strategy,
                "reason": validation.action.reason,
                "previous_setpoint_c": case.previous_setpoint_c,
                "zone_temperature_trend_c": _delta(
                    case.zone_temperature_c,
                    case.one_hour_zone_temperature_c,
                ),
                "power_trend_kw": _delta(
                    case.facility_power_kw,
                    case.one_hour_facility_power_kw,
                ),
                "expected_physical_directions": list(
                    case.expected_directions
                ),
                "actual_physical_direction": actual_direction,
                "direction_correct": direction_correct,
                "action_direction_correct": direction_correct,
                "reason_directions_detected": sorted(
                    detected_reason_directions
                ),
                "reason_direction_correct": (
                    parse_success
                    and reason_direction in case.expected_directions
                ),
                "action_reason_consistent": (
                    parse_success and reason_direction == actual_direction
                ),
                "state_reference_present": (
                    parse_success and has_state_reference
                ),
                "previous_action_reference_present": (
                    parse_success
                    and previous_action_reference_present(reason, case)
                ),
                "fabricated_unavailable_data": (
                    parse_success
                    and fabricates_unavailable_data(
                        reason,
                        occupancy=case.occupancy,
                        pmv=case.pmv,
                    )
                ),
                "generic_reason": (
                    not parse_success
                    or generic_reason(reason, has_state_reference)
                ),
                "normalized_output": normalized_output,
                "normalized_reason": normalized_reason,
                "repeated_output": (
                    bool(normalized_output)
                    and normalized_output
                    in {
                        str(row["normalized_output"])
                        for row in requests
                    }
                ),
                "repeated_reason": (
                    bool(normalized_reason)
                    and normalized_reason
                    in {
                        str(row["normalized_reason"])
                        for row in requests
                    }
                ),
                "unnecessary_change": (
                    case.no_change_expected and actual_direction != "hold"
                ),
                "limit_sticking": requested_value in {22.0, 25.0},
                "final_inside_safe_range": (
                    22.0
                    <= validation.action.supply_air_temperature_setpoint
                    <= 25.0
                ),
                "final_change_limited": final_change <= 1.0 + 1e-9,
                "transport_metadata": client.last_transport_metadata,
            }
        )
        output_path.write_text(
            json.dumps(
                {
                    "status": "running",
                    "model": model_info,
                    "requests": requests,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    summary = summarize(
        model_name,
        requests,
        acceptable_latency_s,
    )
    return {
        "model": model_info,
        "summary": summary,
        "manual_review_candidates": _manual_review_candidates(requests),
        "requests": requests,
    }


def summarize(
    model_name: str,
    requests: list[dict[str, Any]],
    acceptable_latency_s: float,
) -> dict[str, Any]:
    total = len(requests)
    parsed = [row for row in requests if row["strict_json_parse_success"]]
    latencies = [
        float(row["response_latency_s"])
        for row in requests
        if row["response_latency_s"] is not None
    ]
    requested_values = [
        float(row["parsed_requested_setpoint_c"])
        for row in parsed
        if row["parsed_requested_setpoint_c"] is not None
    ]
    reasons = [str(row["reason"]).strip() for row in parsed]
    no_change_cases = [
        row
        for row in requests
        if "hold" in row["expected_physical_directions"]
        and len(row["expected_physical_directions"]) == 1
    ]
    strict_rate = _rate(len(parsed), total)
    direction_rate = _rate(
        sum(bool(row["direction_correct"]) for row in requests),
        total,
    )
    reason_direction_rate = _rate(
        sum(bool(row.get("reason_direction_correct")) for row in requests),
        total,
    )
    action_reason_consistency_rate = _rate(
        sum(bool(row.get("action_reason_consistent")) for row in requests),
        total,
    )
    state_reference_rate = _rate(
        sum(bool(row.get("state_reference_present")) for row in requests),
        total,
    )
    previous_action_reference_rate = _rate(
        sum(
            bool(row.get("previous_action_reference_present"))
            for row in requests
        ),
        total,
    )
    repeated_output_rate = _rate(
        sum(bool(row.get("repeated_output")) for row in requests),
        total,
    )
    generic_reason_rate = _rate(
        sum(bool(row.get("generic_reason")) for row in requests),
        total,
    )
    fallback_rows = [row for row in requests if row["fallback_used"]]
    at_22 = _rate(sum(value == 22.0 for value in requested_values), len(parsed))
    at_25 = _rate(sum(value == 25.0 for value in requested_values), len(parsed))
    average_latency = statistics.mean(latencies) if latencies else math.inf
    summary = {
        "model_name": model_name,
        "total_requests": total,
        "process_crashes": 0,
        "strict_json_success_rate": strict_rate,
        "parser_failure_rate": _rate(total - len(parsed), total),
        "timeout_rate": _rate(sum(bool(row["timeout"]) for row in requests), total),
        "transport_failure_rate": _rate(
            sum(bool(row["transport_failure"]) for row in requests),
            total,
        ),
        "fallback_rate": _rate(len(fallback_rows), total),
        "fallback_success_rate": _rate(
            sum(bool(row["fallback_success"]) for row in fallback_rows),
            len(fallback_rows),
            empty=1.0,
        ),
        "safety_correction_rate": _rate(
            sum(bool(row["safety_corrected"]) for row in requests),
            total,
        ),
        "physical_direction_accuracy": direction_rate,
        "action_direction_accuracy": direction_rate,
        "reason_direction_accuracy": reason_direction_rate,
        "action_reason_consistency_rate": action_reason_consistency_rate,
        "state_reference_rate": state_reference_rate,
        "previous_action_reference_rate": previous_action_reference_rate,
        "repeated_output_rate": repeated_output_rate,
        "generic_reason_rate": generic_reason_rate,
        "fabricated_unavailable_data_count": sum(
            bool(row.get("fabricated_unavailable_data"))
            for row in requests
        ),
        "no_change_correctness_rate": _rate(
            sum(
                row["actual_physical_direction"] == "hold"
                for row in no_change_cases
            ),
            len(no_change_cases),
        ),
        "average_latency_s": average_latency,
        "median_latency_s": statistics.median(latencies) if latencies else None,
        "p95_latency_s": _percentile(latencies, 0.95),
        "maximum_latency_s": max(latencies) if latencies else None,
        "mean_absolute_requested_change_c": (
            statistics.mean(
                abs(
                    float(row["parsed_requested_setpoint_c"])
                    - float(row["previous_setpoint_c"])
                )
                for row in parsed
            )
            if parsed
            else None
        ),
        "outputs_exactly_22_rate": at_22,
        "outputs_exactly_25_rate": at_25,
        "action_diversity": len(set(requested_values)),
        "unique_requested_values_c": sorted(set(requested_values)),
        "repeated_reason_rate": _rate(
            len(reasons) - len(set(reasons)),
            len(reasons),
        ),
        "final_safe_range_rate": _rate(
            sum(bool(row["final_inside_safe_range"]) for row in requests),
            total,
        ),
        "final_rate_limit_compliance_rate": _rate(
            sum(bool(row["final_change_limited"]) for row in requests),
            total,
        ),
        "acceptable_latency_threshold_s": acceptable_latency_s,
    }
    critical = {
        "zero_process_crashes": summary["process_crashes"] == 0,
        "strict_json_at_least_95_percent": strict_rate >= 0.95,
        "all_final_actions_safe": summary["final_safe_range_rate"] == 1.0,
        "all_final_changes_rate_limited": (
            summary["final_rate_limit_compliance_rate"] == 1.0
        ),
        "all_fallbacks_succeeded": summary["fallback_success_rate"] == 1.0,
        "direction_accuracy_at_least_85_percent": direction_rate >= 0.85,
        "reason_direction_accuracy_at_least_85_percent": (
            reason_direction_rate >= 0.85
        ),
        "action_reason_consistency_at_least_90_percent": (
            action_reason_consistency_rate >= 0.90
        ),
        "state_reference_at_least_80_percent": state_reference_rate >= 0.80,
        "no_persistent_fixed_output": (
            summary["action_diversity"] >= 3
            and repeated_output_rate < 0.80
        ),
        "no_persistent_generic_reason": (
            summary["repeated_reason_rate"] < 0.80
            and generic_reason_rate < 0.20
        ),
        "no_fabricated_occupancy_or_pmv": (
            summary["fabricated_unavailable_data_count"] == 0
        ),
        "not_persistently_at_22": at_22 < 0.8,
        "not_persistently_at_25": at_25 < 0.8,
        "latency_within_threshold": average_latency <= acceptable_latency_s,
        "maximum_normal_latency_below_15_seconds": (
            summary["maximum_latency_s"] is not None
            and summary["maximum_latency_s"] < 15.0
        ),
    }
    summary["critical_criteria"] = critical
    summary["eligible_for_energyplus_smoke_test"] = all(critical.values())
    summary["latency_verdict"] = (
        "excellent"
        if average_latency < 2
        else "acceptable"
        if average_latency < 5
        else "concerning"
        if average_latency <= 15
        else "poor"
    )
    return summary


def _manual_review_candidates(
    requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    wanted = {
        "hot_rising",
        "hot_falling",
        "moderate_high_hvac",
        "missing_temperature_trend",
        "stable_hold",
    }
    return [
        {
            "test_case_id": row["test_case_id"],
            "raw_response": row["raw_response"],
            "expected_physical_directions": row[
                "expected_physical_directions"
            ],
            "actual_physical_direction": row["actual_physical_direction"],
            "direction_correct": row["direction_correct"],
            "reason_direction_correct": row["reason_direction_correct"],
            "action_reason_consistent": row["action_reason_consistent"],
            "state_reference_present": row["state_reference_present"],
            "previous_action_reference_present": row[
                "previous_action_reference_present"
            ],
        }
        for row in requests
        if row["test_case_id"] in wanted
    ]


def write_reports(results: list[dict[str, Any]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "ollama_model_benchmark_results.json"
    markdown_path = output_dir / "ollama_model_benchmark_report.md"
    selected_path = output_dir / "selected_model_report.md"
    payload = {
        "benchmark_version": 2,
        "deterministic": True,
        "fixture_count": len(benchmark_cases()),
        "hardware_platform": platform.platform(),
        "models": results,
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# Ollama Model Benchmark Report",
        "",
        "The same 20 deterministic fixtures and prompt contract were used for every model.",
        "",
        "| Model | JSON | Action direction | Reason direction | Action/reason | Diversity | Repeated output | Avg latency | Verdict |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for result in results:
        summary = result["summary"]
        lines.append(
            f"| {summary['model_name']} | "
            f"{summary['strict_json_success_rate']:.1%} | "
            f"{summary['action_direction_accuracy']:.1%} | "
            f"{summary['reason_direction_accuracy']:.1%} | "
            f"{summary['action_reason_consistency_rate']:.1%} | "
            f"{summary['action_diversity']} | "
            f"{summary['repeated_output_rate']:.1%} | "
            f"{summary['average_latency_s']:.3f} s | "
            f"{'Eligible' if summary['eligible_for_energyplus_smoke_test'] else 'Rejected'} |"
        )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    eligible = [
        result
        for result in results
        if result["summary"]["eligible_for_energyplus_smoke_test"]
    ]
    selected = min(
        eligible,
        key=lambda result: (
            -result["summary"]["strict_json_success_rate"],
            -result["summary"]["physical_direction_accuracy"],
            result["summary"]["fallback_rate"],
            result["summary"]["safety_correction_rate"],
            result["summary"]["average_latency_s"],
            int(result["model"].get("size", 0)),
        ),
        default=None,
    )
    selected_lines = ["# Selected Model Report", ""]
    if selected is None:
        selected_lines.extend(
            [
                "**No model selected.**",
                "",
                "No installed model met every critical benchmark criterion.",
            ]
        )
    else:
        model = selected["model"]
        summary = selected["summary"]
        details = model.get("details", {})
        selected_lines.extend(
            [
                f"- Selected model: `{summary['model_name']}`",
                f"- Exact tag: `{model.get('name')}`",
                f"- Parameter size: {details.get('parameter_size', 'Unavailable')}",
                f"- File size: {int(model.get('size', 0)) / 1_000_000_000:.3f} GB",
                f"- Quantization: {details.get('quantization_level', 'Unavailable')}",
                f"- Hardware: {platform.platform()}",
                f"- Benchmark requests: {summary['total_requests']}",
                f"- JSON success: {summary['strict_json_success_rate']:.1%}",
                f"- Direction accuracy: {summary['physical_direction_accuracy']:.1%}",
                f"- Safety corrections: {summary['safety_correction_rate']:.1%}",
                f"- Fallback rate: {summary['fallback_rate']:.1%}",
                f"- Average latency: {summary['average_latency_s']:.3f} s",
                f"- P95 latency: {summary['p95_latency_s']:.3f} s",
                "",
                "It was selected strictly from measured eligible results. "
                "With one installed model, this is an eligibility decision, "
                "not a meaningful multi-model comparison.",
            ]
        )
    selected_path.write_text(
        "\n".join(selected_lines) + "\n",
        encoding="utf-8",
    )


def _direction(value: float, previous: float, epsilon: float = 0.05) -> str:
    if value < previous - epsilon:
        return "lower"
    if value > previous + epsilon:
        return "higher"
    return "hold"


def _delta(current: float, previous: float | None) -> float | None:
    return None if previous is None else current - previous


def _rate(numerator: int, denominator: int, empty: float = 0.0) -> float:
    return numerator / denominator if denominator else empty


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", action="append")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--response-timeout-s", type=float, default=20.0)
    parser.add_argument("--acceptable-latency-s", type=float, default=15.0)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "test_reports",
    )
    args = parser.parse_args()

    available = installed_models(args.base_url)
    selected_names = set(args.model or [])
    selected = [
        model
        for model in available
        if not selected_names
        or model.get("name") in selected_names
        or model.get("model") in selected_names
    ]
    if not selected:
        names = [str(model.get("name")) for model in available]
        raise SystemExit(
            f"No selected model is installed. Installed models: {names}"
        )

    partial_path = args.output_dir / "ollama_model_benchmark_partial.json"
    results = []
    for model in selected:
        results.append(
            run_model(
                model,
                args.base_url,
                args.response_timeout_s,
                args.acceptable_latency_s,
                partial_path,
            )
        )
    write_reports(results, args.output_dir)
    print(
        "[Benchmark] Reports written to "
        f"{args.output_dir / 'ollama_model_benchmark_report.md'}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
