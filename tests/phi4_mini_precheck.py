"""Guarded cold/warm viability precheck for one installed Phi-4 Mini tag."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

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
    benchmark_cases,
    build_fixture,
    installed_models,
)


def run_precheck(
    model_tag: str,
    base_url: str,
    output_dir: Path,
    resume_warm: bool = False,
    report_prefix: str = "phi4_mini",
) -> dict[str, Any]:
    model_info = next(
        (
            model
            for model in installed_models(base_url)
            if model.get("name") == model_tag
        ),
        None,
    )
    if model_info is None:
        raise RuntimeError(f"Installed model tag not found: {model_tag}")

    case = next(case for case in benchmark_cases() if case.case_id == "hot_rising")
    state, controller_state = build_fixture(case)
    prompt = build_prompt(state, controller_state)
    client = OllamaLLMClient(
        model=model_tag,
        base_url=base_url,
        connect_timeout_s=3,
        response_timeout_s=20,
        temperature=0,
        stream=False,
        json_mode=True,
        keep_alive="5m",
        max_output_tokens=128,
    )
    validator = SafetyValidator()
    fallback = RuleController()
    json_path = output_dir / f"{report_prefix}_precheck_results.json"
    requests: list[dict[str, Any]] = []
    if resume_warm:
        if not json_path.exists():
            raise RuntimeError("Cannot resume warm precheck without cold results")
        previous = json.loads(json_path.read_text(encoding="utf-8"))
        requests = list(previous.get("requests", []))
        if not requests or requests[0].get("request_kind") != "cold":
            raise RuntimeError("Existing precheck does not contain a cold request")

    completed_kinds = {str(row["request_kind"]) for row in requests}
    request_kinds = [
        kind
        for kind in ("cold", "warm_1", "warm_2", "warm_3")
        if kind not in completed_kinds
    ]
    if resume_warm:
        request_kinds = [
            kind for kind in request_kinds if kind.startswith("warm")
        ]

    for request_kind in request_kinds:
        raw_response = ""
        requested_action = None
        parse_success = False
        fallback_used = False
        failure_reason = ""
        timeout = False
        transport_failure = False
        try:
            raw_response = client.query(prompt)
            requested_action = parse_response(raw_response)
        except Exception as exc:
            timeout = isinstance(exc, LLMTimeoutError)
            transport_failure = isinstance(exc, LLMConnectionError)
            fallback_used = True
            failure_reason = f"{type(exc).__name__}: {exc}"
            requested_action = fallback.decide(state, controller_state)
        else:
            parse_success = True

        validation = validator.validate(
            requested_action,
            previous_action=controller_state.previous_action,
        )
        parsed_setpoint = (
            requested_action.supply_air_temperature_setpoint
            if parse_success
            else None
        )
        direction = (
            "lower"
            if parsed_setpoint is not None
            and parsed_setpoint < case.previous_setpoint_c - 0.05
            else "higher"
            if parsed_setpoint is not None
            and parsed_setpoint > case.previous_setpoint_c + 0.05
            else "hold"
            if parsed_setpoint is not None
            else "fallback"
        )
        row = {
            "request_kind": request_kind,
            "model_tag": model_tag,
            "prompt_length": len(prompt),
            "raw_response": raw_response,
            "response_latency_s": client.last_response_duration_seconds,
            "timeout": timeout,
            "transport_failure": transport_failure,
            "strict_json_parse_success": parse_success,
            "failure_reason": failure_reason,
            "requested_setpoint_c": parsed_setpoint,
            "validated_setpoint_c": (
                validation.action.supply_air_temperature_setpoint
            ),
            "safety_corrected": validation.corrected,
            "validation_status": validation.status,
            "fallback_used": fallback_used,
            "expected_direction": "lower",
            "actual_direction": direction,
            "direction_correct": direction == "lower",
            "final_inside_safe_range": (
                22.0
                <= validation.action.supply_air_temperature_setpoint
                <= 25.0
            ),
            "final_change_limited": (
                abs(
                    validation.action.supply_air_temperature_setpoint
                    - case.previous_setpoint_c
                )
                <= 1.0 + 1e-9
            ),
            "transport_metadata": client.last_transport_metadata,
        }
        requests.append(row)
        print(
            f"[Phi Precheck] {request_kind}: "
            f"latency={row['response_latency_s']:.3f}s "
            f"timeout={timeout} json={parse_success}",
            flush=True,
        )

        # A non-streaming timeout may leave server-side work running. Stop
        # immediately rather than contaminating the remaining measurements.
        if timeout:
            break

    warm = [row for row in requests if str(row["request_kind"]).startswith("warm")]
    warm_latencies = [
        float(row["response_latency_s"])
        for row in warm
        if row["response_latency_s"] is not None
    ]
    median_warm = (
        statistics.median(warm_latencies)
        if len(warm_latencies) == 3
        else None
    )
    with urlopen(f"{base_url.rstrip('/')}/api/ps", timeout=3) as response:
        running_envelope = json.load(response)
    running_names = {
        str(model.get("name"))
        for model in running_envelope.get("models", [])
        if isinstance(model, dict)
    }
    model_loaded = (
        any(bool(row["strict_json_parse_success"]) for row in requests)
        or model_tag in running_names
    )
    criteria = {
        "model_loaded": model_loaded,
        "three_warm_requests_completed": len(warm) == 3,
        "no_warm_timeouts": (
            len(warm) == 3 and not any(row["timeout"] for row in warm)
        ),
        "at_least_two_warm_strict_json": (
            sum(bool(row["strict_json_parse_success"]) for row in warm) >= 2
        ),
        "median_warm_latency_at_most_10_s": (
            median_warm is not None and median_warm <= 10
        ),
        "all_final_actions_safe": all(
            bool(row["final_inside_safe_range"]) for row in requests
        ),
        "all_final_changes_rate_limited": all(
            bool(row["final_change_limited"]) for row in requests
        ),
        "no_repeated_direction_confusion": (
            sum(not bool(row["direction_correct"]) for row in warm) <= 1
            if len(warm) == 3
            else False
        ),
    }
    result = {
        "status": "pass" if all(criteria.values()) else "fail",
        "eligible_for_full_benchmark": all(criteria.values()),
        "model": model_info,
        "representative_case_id": case.case_id,
        "prompt_length": len(prompt),
        "prompt_contract_checks": {
            "actuator_name": "MAIN COOLING COIL 1 OUTLET NODE" in prompt,
            "safe_range": "Allowed range: 22.0 C to 25.0 C" in prompt,
            "lower_is_stronger": "Lower values generally provide colder" in prompt,
            "higher_is_weaker": "Higher values generally provide warmer" in prompt,
            "occupancy_unavailable": "Occupancy: Unavailable" in prompt,
            "pmv_unavailable": "PMV: Unavailable" in prompt,
            "exact_json_field": "supply_air_temperature_setpoint" in prompt,
        },
        "cold_start_latency_s": (
            requests[0]["response_latency_s"] if requests else None
        ),
        "median_warm_latency_s": median_warm,
        "warm_strict_json_count": sum(
            bool(row["strict_json_parse_success"]) for row in warm
        ),
        "criteria": criteria,
        "queue_contamination_risk": any(row["timeout"] for row in requests),
        "requests": requests,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"{report_prefix}_precheck_report.md"
    json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    report_path.write_text(build_report(result), encoding="utf-8")
    return result


def build_report(result: dict[str, Any]) -> str:
    model = result["model"]
    details = model.get("details", {})
    lines = [
        f"# {model.get('name')} Precheck Report",
        "",
        f"**{str(result['status']).upper()}**",
        "",
        f"- Exact tag: `{model.get('name')}`",
        f"- Size: {int(model.get('size', 0)) / 1_000_000_000:.3f} GB",
        f"- Parameters: {details.get('parameter_size', 'Unavailable')}",
        f"- Quantization: {details.get('quantization_level', 'Unavailable')}",
        f"- Prompt length: {result['prompt_length']} characters",
        f"- Cold latency: {_format_seconds(result['cold_start_latency_s'])}",
        f"- Median warm latency: {_format_seconds(result['median_warm_latency_s'])}",
        f"- Warm strict JSON responses: {result['warm_strict_json_count']}/3",
        "",
        "| Request | Latency | Timeout | JSON | Requested | Validated | Fallback | Direction |",
        "| --- | ---: | --- | --- | ---: | ---: | --- | --- |",
    ]
    for row in result["requests"]:
        lines.append(
            f"| {row['request_kind']} | "
            f"{_format_seconds(row['response_latency_s'])} | "
            f"{row['timeout']} | {row['strict_json_parse_success']} | "
            f"{row['requested_setpoint_c']} | {row['validated_setpoint_c']} | "
            f"{row['fallback_used']} | {row['actual_direction']} |"
        )
    lines.extend(["", "## Criteria", ""])
    for name, passed in result["criteria"].items():
        lines.append(f"- {name}: `{passed}`")
    lines.extend(
        [
            "",
            "A timeout stops the precheck immediately because a closed client "
            "connection does not prove server-side generation was cancelled.",
            "",
        ]
    )
    return "\n".join(lines)


def _format_seconds(value: Any) -> str:
    if value is None:
        return "Unavailable"
    return f"{float(value):.3f} s"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--resume-warm", action="store_true")
    parser.add_argument("--report-prefix", default="phi4_mini")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "test_reports",
    )
    args = parser.parse_args()
    result = run_precheck(
        args.model,
        args.base_url,
        args.output_dir,
        resume_warm=args.resume_warm,
        report_prefix=args.report_prefix,
    )
    print(
        f"[Phi Precheck] eligible={result['eligible_for_full_benchmark']}",
        flush=True,
    )
    return 0 if result["eligible_for_full_benchmark"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
