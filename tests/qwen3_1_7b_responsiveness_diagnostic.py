"""Final state-responsiveness diagnostic for the installed qwen3:1.7b model."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from controller.action import ControlAction  # noqa: E402
from controller.output_parser import parse_response  # noqa: E402
from controller.prompt_builder import build_prompt  # noqa: E402
from controller.rule_controller import RuleController  # noqa: E402
from controller.safety import SafetyValidator  # noqa: E402
from llm.client import (  # noqa: E402
    LLMConnectionError,
    LLMTimeoutError,
    OllamaLLMClient,
)
from ollama_model_benchmark import (  # noqa: E402
    BenchmarkCase,
    benchmark_cases,
    build_fixture,
    installed_models,
)
from response_semantics import (  # noqa: E402
    fabricates_unavailable_data as _fabricates_unavailable_data,
    generic_reason as _generic_reason,
    normalize_text as _normalize,
    previous_action_reference_present as _previous_action_reference_present,
    reason_directions as _reason_directions,
    state_reference_present as _state_reference_present,
)

MODEL_TAG = "qwen3:1.7b"
REPORT_NAME = "qwen3_1_7b_responsiveness_diagnostic_report.md"
RESULTS_NAME = "qwen3_1_7b_responsiveness_diagnostic_results.json"


def diagnostic_cases() -> list[BenchmarkCase]:
    """Return the fixed five-case responsiveness corpus."""

    existing = {case.case_id: case for case in benchmark_cases()}
    stable_lower_limit = BenchmarkCase(
        case_id="stable_lower_limit",
        description="Stable state at the 22 C lower limit",
        zone_temperature_c=26.5,
        previous_zone_temperature_c=26.5,
        one_hour_zone_temperature_c=26.5,
        outdoor_temperature_c=23.0,
        facility_power_kw=76.0,
        one_hour_facility_power_kw=76.0,
        hvac_power_kw=7.0,
        previous_setpoint_c=22.0,
        expected_directions=("hold", "higher"),
        no_change_expected=True,
    )
    return [
        existing["hot_rising"],
        existing["hot_falling"],
        existing["stable_hold"],
        stable_lower_limit,
        existing["previous_25"],
    ]


def run_diagnostic(
    base_url: str,
    output_dir: Path,
    response_timeout_s: float = 20.0,
) -> dict[str, Any]:
    """Run sequential requests and persist evidence even after a stop failure."""

    models = installed_models(base_url)
    model_info = next(
        (
            model
            for model in models
            if model.get("name") == MODEL_TAG or model.get("model") == MODEL_TAG
        ),
        None,
    )
    if model_info is None:
        installed = [
            str(model.get("name") or model.get("model")) for model in models
        ]
        raise RuntimeError(
            f"Required installed model {MODEL_TAG!r} was not found. "
            f"Installed tags: {installed}"
        )

    client = OllamaLLMClient(
        model=MODEL_TAG,
        base_url=base_url,
        connect_timeout_s=3.0,
        response_timeout_s=response_timeout_s,
        temperature=0.0,
        stream=False,
        json_mode=True,
        keep_alive="5m",
        seed=42,
        max_output_tokens=128,
    )
    validator = SafetyValidator()
    fallback = RuleController()
    rows: list[dict[str, Any]] = []
    output_dir.mkdir(parents=True, exist_ok=True)

    for index, case in enumerate(diagnostic_cases(), start=1):
        state, controller_state = build_fixture(case)
        prompt = build_prompt(state, controller_state)
        raw_response = ""
        parsed_action: ControlAction | None = None
        requested_action: ControlAction
        parse_success = False
        timeout = False
        transport_failure = False
        fallback_used = False
        failure_reason = ""

        print(
            f"[Responsiveness] {index}/5 {case.case_id}",
            flush=True,
        )
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

        validation = validator.validate(
            requested_action,
            previous_action=controller_state.previous_action,
        )
        requested_setpoint = (
            parsed_action.supply_air_temperature_setpoint
            if parsed_action is not None
            else None
        )
        action_direction = (
            _direction(requested_setpoint, case.previous_setpoint_c)
            if requested_setpoint is not None
            else "fallback"
        )
        reason = parsed_action.reason if parsed_action is not None else ""
        reason_directions = _reason_directions(reason)
        unambiguous_reason_direction = (
            next(iter(reason_directions))
            if len(reason_directions) == 1
            else None
        )
        state_reference = _state_reference_present(reason, case)
        previous_reference = _previous_action_reference_present(reason, case)
        fabricated_unavailable_data = _fabricates_unavailable_data(
            reason,
            occupancy=case.occupancy,
            pmv=case.pmv,
        )
        normalized_output = _normalize(raw_response)
        normalized_reason = _normalize(reason)
        previous_outputs = {
            str(row["normalized_output"]) for row in rows
        }
        previous_reasons = {
            str(row["normalized_reason"]) for row in rows
        }
        final_setpoint = validation.action.supply_air_temperature_setpoint

        row = {
            "case_id": case.case_id,
            "description": case.description,
            "previous_setpoint_c": case.previous_setpoint_c,
            "state": {
                "zone_temperature_c": case.zone_temperature_c,
                "zone_temperature_trend_c": _delta(
                    case.zone_temperature_c,
                    case.one_hour_zone_temperature_c,
                ),
                "outdoor_temperature_c": case.outdoor_temperature_c,
                "facility_power_kw": case.facility_power_kw,
                "power_trend_kw": _delta(
                    case.facility_power_kw,
                    case.one_hour_facility_power_kw,
                ),
                "hvac_power_kw": case.hvac_power_kw,
                "occupancy": case.occupancy,
                "pmv": case.pmv,
            },
            "expected_directions": list(case.expected_directions),
            "prompt_length": len(prompt),
            "raw_response": raw_response,
            "strict_json_success": parse_success,
            "failure_reason": failure_reason,
            "requested_setpoint_c": requested_setpoint,
            "validated_setpoint_c": final_setpoint,
            "action_direction": action_direction,
            "action_direction_correct": (
                parse_success and action_direction in case.expected_directions
            ),
            "reason_directions_detected": sorted(reason_directions),
            "reason_direction_correct": (
                parse_success
                and unambiguous_reason_direction in case.expected_directions
            ),
            "action_reason_consistent": (
                parse_success
                and unambiguous_reason_direction == action_direction
            ),
            "state_reference_present": state_reference,
            "previous_action_reference_present": previous_reference,
            "fabricated_unavailable_data": fabricated_unavailable_data,
            "generic_reason": _generic_reason(reason, state_reference),
            "safety_correction": validation.corrected,
            "validation_status": validation.status,
            "final_action_safe": 22.0 <= final_setpoint <= 25.0,
            "final_change_rate_limited": (
                abs(final_setpoint - case.previous_setpoint_c) <= 1.0 + 1e-9
            ),
            "fallback_used": fallback_used,
            "latency_s": client.last_response_duration_seconds,
            "timeout": timeout,
            "transport_failure": transport_failure,
            "normalized_output": normalized_output,
            "normalized_reason": normalized_reason,
            "repeated_output": normalized_output in previous_outputs,
            "repeated_reason": (
                bool(normalized_reason) and normalized_reason in previous_reasons
            ),
            "transport_metadata": client.last_transport_metadata,
        }
        rows.append(row)
        _write_results(
            output_dir / RESULTS_NAME,
            _build_result(model_info, rows, status="running"),
        )

        # A timeout can leave server-side work running. A parser failure is also
        # an explicit stop condition for this final diagnostic.
        if timeout or not parse_success:
            break

    result = _build_result(model_info, rows)
    _write_results(output_dir / RESULTS_NAME, result)
    (output_dir / REPORT_NAME).write_text(
        build_report(result),
        encoding="utf-8",
    )
    return result


def _build_result(
    model_info: dict[str, Any],
    rows: list[dict[str, Any]],
    status: str | None = None,
) -> dict[str, Any]:
    completed = len(rows)
    parsed_rows = [row for row in rows if row["strict_json_success"]]
    requested_values = [
        float(row["requested_setpoint_c"])
        for row in parsed_rows
        if row["requested_setpoint_c"] is not None
    ]
    reasons = [
        str(row["normalized_reason"])
        for row in parsed_rows
        if row["normalized_reason"]
    ]
    by_id = {str(row["case_id"]): row for row in rows}
    criteria = {
        "all_five_cases_completed": completed == 5,
        "strict_json_5_of_5": (
            completed == 5
            and sum(bool(row["strict_json_success"]) for row in rows) == 5
        ),
        "zero_timeouts": not any(bool(row["timeout"]) for row in rows),
        "zero_fallbacks": not any(bool(row["fallback_used"]) for row in rows),
        "safe_final_actions_5_of_5": (
            completed == 5
            and all(bool(row["final_action_safe"]) for row in rows)
        ),
        "at_least_three_unique_requested_values": (
            len(set(requested_values)) >= 3
        ),
        "action_direction_correct_at_least_4_of_5": (
            sum(bool(row["action_direction_correct"]) for row in rows) >= 4
        ),
        "reason_direction_correct_at_least_4_of_5": (
            sum(bool(row["reason_direction_correct"]) for row in rows) >= 4
        ),
        "action_reason_consistent_at_least_4_of_5": (
            sum(bool(row["action_reason_consistent"]) for row in rows) >= 4
        ),
        "stable_midrange_held": (
            by_id.get("stable_hold", {}).get("action_direction") == "hold"
        ),
        "lower_limit_not_lowered": (
            by_id.get("stable_lower_limit", {}).get("action_direction")
            in {"hold", "higher"}
        ),
        "upper_limit_not_lowered_without_evidence": (
            by_id.get("previous_25", {}).get("action_direction") == "hold"
        ),
        "reasons_not_identical_or_generic": (
            len(set(reasons)) >= 3
            and sum(bool(row["generic_reason"]) for row in rows) <= 1
        ),
        "state_referenced_at_least_4_of_5": (
            sum(bool(row["state_reference_present"]) for row in rows) >= 4
        ),
        "no_fabricated_occupancy_or_pmv": not any(
            bool(row["fabricated_unavailable_data"]) for row in rows
        ),
    }
    passed = completed == 5 and all(criteria.values())
    latencies = [
        float(row["latency_s"])
        for row in rows
        if row["latency_s"] is not None
    ]
    summary = {
        "completed_requests": completed,
        "strict_json_successes": sum(
            bool(row["strict_json_success"]) for row in rows
        ),
        "timeouts": sum(bool(row["timeout"]) for row in rows),
        "transport_failures": sum(
            bool(row["transport_failure"]) for row in rows
        ),
        "fallbacks": sum(bool(row["fallback_used"]) for row in rows),
        "safe_final_actions": sum(
            bool(row["final_action_safe"]) for row in rows
        ),
        "unique_requested_values_c": sorted(set(requested_values)),
        "action_direction_correct": sum(
            bool(row["action_direction_correct"]) for row in rows
        ),
        "reason_direction_correct": sum(
            bool(row["reason_direction_correct"]) for row in rows
        ),
        "action_reason_consistent": sum(
            bool(row["action_reason_consistent"]) for row in rows
        ),
        "state_reference_present": sum(
            bool(row["state_reference_present"]) for row in rows
        ),
        "previous_action_reference_present": sum(
            bool(row["previous_action_reference_present"]) for row in rows
        ),
        "repeated_output_count": sum(
            bool(row["repeated_output"]) for row in rows
        ),
        "repeated_reason_count": sum(
            bool(row["repeated_reason"]) for row in rows
        ),
        "generic_reason_count": sum(
            bool(row["generic_reason"]) for row in rows
        ),
        "average_latency_s": (
            statistics.mean(latencies) if latencies else None
        ),
        "median_latency_s": (
            statistics.median(latencies) if latencies else None
        ),
        "maximum_latency_s": max(latencies) if latencies else None,
    }
    return {
        "status": status or ("pass" if passed else "fail"),
        "eligible_for_full_benchmark": passed,
        "model": model_info,
        "prompt_leakage_removed": True,
        "diagnostic_case_count": 5,
        "summary": summary,
        "criteria": criteria,
        "requests": rows,
    }


def rescore_saved_results(path: Path) -> dict[str, Any]:
    """Recompute semantic scores without issuing another model request."""

    saved = json.loads(path.read_text(encoding="utf-8"))
    cases = {case.case_id: case for case in diagnostic_cases()}
    rows = list(saved["requests"])
    for row in rows:
        case = cases[str(row["case_id"])]
        action = parse_response(str(row["raw_response"]))
        reason_directions = _reason_directions(action.reason)
        reason_direction = (
            next(iter(reason_directions))
            if len(reason_directions) == 1
            else None
        )
        state_reference = _state_reference_present(action.reason, case)
        row["reason_directions_detected"] = sorted(reason_directions)
        row["reason_direction_correct"] = (
            reason_direction in case.expected_directions
        )
        row["action_reason_consistent"] = (
            reason_direction == row["action_direction"]
        )
        row["state_reference_present"] = state_reference
        row["previous_action_reference_present"] = (
            _previous_action_reference_present(action.reason, case)
        )
        row["fabricated_unavailable_data"] = _fabricates_unavailable_data(
            action.reason,
            occupancy=case.occupancy,
            pmv=case.pmv,
        )
        row["generic_reason"] = _generic_reason(
            action.reason,
            state_reference,
        )

    result = _build_result(saved["model"], rows)
    _write_results(path, result)
    (path.parent / REPORT_NAME).write_text(
        build_report(result),
        encoding="utf-8",
    )
    return result


def build_report(result: dict[str, Any]) -> str:
    """Render the compact human-readable diagnostic report."""

    summary = result["summary"]
    lines = [
        "# Qwen3 1.7B Responsiveness Diagnostic",
        "",
        f"**{str(result['status']).upper()}**",
        "",
        f"- Exact model tag: `{MODEL_TAG}`",
        f"- Completed requests: {summary['completed_requests']}/5",
        f"- Strict JSON: {summary['strict_json_successes']}/5",
        f"- Timeouts: {summary['timeouts']}",
        f"- Safe final actions: {summary['safe_final_actions']}/5",
        (
            "- Unique requested setpoints: "
            f"{summary['unique_requested_values_c']}"
        ),
        (
            "- Action-direction correctness: "
            f"{summary['action_direction_correct']}/5"
        ),
        (
            "- Reason-direction correctness: "
            f"{summary['reason_direction_correct']}/5"
        ),
        (
            "- Action/reason consistency: "
            f"{summary['action_reason_consistent']}/5"
        ),
        (
            "- State references: "
            f"{summary['state_reference_present']}/5"
        ),
        (
            "- Previous-action references: "
            f"{summary['previous_action_reference_present']}/5"
        ),
        f"- Repeated outputs: {summary['repeated_output_count']}/5",
        f"- Repeated reasons: {summary['repeated_reason_count']}/5",
        f"- Average latency: {_seconds(summary['average_latency_s'])}",
        f"- Maximum latency: {_seconds(summary['maximum_latency_s'])}",
        "",
        "## Case Results",
        "",
        (
            "| Case | Previous | Expected | Requested | Direction | "
            "Action correct | Reason correct | Consistent | State ref | "
            "Previous ref | Latency |"
        ),
        (
            "| --- | ---: | --- | ---: | --- | --- | --- | --- | --- | "
            "--- | ---: |"
        ),
    ]
    for row in result["requests"]:
        lines.append(
            f"| {row['case_id']} | {row['previous_setpoint_c']} | "
            f"{'/'.join(row['expected_directions'])} | "
            f"{row['requested_setpoint_c']} | {row['action_direction']} | "
            f"{row['action_direction_correct']} | "
            f"{row['reason_direction_correct']} | "
            f"{row['action_reason_consistent']} | "
            f"{row['state_reference_present']} | "
            f"{row['previous_action_reference_present']} | "
            f"{_seconds(row['latency_s'])} |"
        )
    lines.extend(["", "## Raw Responses", ""])
    for row in result["requests"]:
        lines.extend(
            [
                f"### {row['case_id']}",
                "",
                "```json",
                str(row["raw_response"]),
                "```",
                "",
            ]
        )
    lines.extend(["## Pass Criteria", ""])
    for name, passed in result["criteria"].items():
        lines.append(f"- {name}: `{passed}`")
    lines.extend(
        [
            "",
            (
                "Fallback actions are recorded for final-system safety only and "
                "never count as successful model decisions."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _direction(value: float, previous: float, epsilon: float = 0.05) -> str:
    if value < previous - epsilon:
        return "lower"
    if value > previous + epsilon:
        return "higher"
    return "hold"


def _delta(current: float, previous: float | None) -> float | None:
    return None if previous is None else current - previous


def _seconds(value: Any) -> str:
    return "Unavailable" if value is None else f"{float(value):.3f} s"


def _write_results(path: Path, result: dict[str, Any]) -> None:
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--response-timeout-s", type=float, default=20.0)
    parser.add_argument(
        "--rescore-existing",
        action="store_true",
        help="Rescore the saved raw responses without querying Ollama.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "test_reports",
    )
    args = parser.parse_args()
    if args.rescore_existing:
        result = rescore_saved_results(args.output_dir / RESULTS_NAME)
    else:
        result = run_diagnostic(
            base_url=args.base_url,
            output_dir=args.output_dir,
            response_timeout_s=args.response_timeout_s,
        )
    print(
        "[Responsiveness] "
        f"status={result['status']} "
        f"eligible={result['eligible_for_full_benchmark']}",
        flush=True,
    )
    return 0 if result["eligible_for_full_benchmark"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
