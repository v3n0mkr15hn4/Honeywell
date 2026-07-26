"""Guarded one-day EnergyPlus smoke test for NVIDIA candidate ranking."""

from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "src", ROOT / "tests"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from energyplus.config import (  # noqa: E402
    ControllerType,
    EnergyPlusConfig,
    LLMProvider,
)
from energyplus.runner import run_simulation  # noqa: E402


MODEL = "nvidia/llama-3.3-nemotron-super-49b-v1.5"
REPORTS = ROOT / "test_reports"
GATE_RESULTS = REPORTS / "nvidia_nim_candidate_ranking_results.json"
RESULTS_PATH = REPORTS / "nvidia_nim_one_day_smoke_test_results.json"
REPORT_PATH = REPORTS / "nvidia_nim_one_day_smoke_test_report.md"


def build_one_day_idf_text(source: str) -> str:
    """Run only the first RunPeriod, constrained to January 1."""

    source = _replace_object_field(
        source,
        "SimulationControl",
        "Run Simulation for Sizing Periods",
        "No",
    )
    spans = _idf_object_spans(source, "RunPeriod")
    if not spans:
        raise ValueError("The source IDF has no RunPeriod object.")

    first_start, first_end = spans[0]
    first = source[first_start:first_end]
    first = _replace_idf_field(first, "Name", "NVIDIA NIM One Day")
    first = _replace_idf_field(first, "Begin Month", "1")
    first = _replace_idf_field(first, "Begin Day of Month", "1")
    first = _replace_idf_field(first, "End Month", "1")
    first = _replace_idf_field(first, "End Day of Month", "1")

    pieces = [source[:first_start], first]
    cursor = first_end
    for start, end in spans[1:]:
        pieces.append(source[cursor:start])
        cursor = end
    pieces.append(source[cursor:])
    result = "".join(pieces)

    remaining = _idf_object_spans(result, "RunPeriod")
    if len(remaining) != 1:
        raise ValueError("Generated IDF must contain exactly one RunPeriod.")
    return result


def _replace_object_field(
    source: str,
    object_type: str,
    label: str,
    value: str,
) -> str:
    spans = _idf_object_spans(source, object_type)
    if len(spans) != 1:
        raise ValueError(
            f"Expected exactly one {object_type} object; found {len(spans)}."
        )
    start, end = spans[0]
    updated = _replace_idf_field(source[start:end], label, value)
    return source[:start] + updated + source[end:]


def _idf_object_spans(source: str, object_type: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    object_start: int | None = None
    object_name = ""
    offset = 0

    for line in source.splitlines(keepends=True):
        code = line.split("!", 1)[0].strip()
        if object_start is None and code:
            object_start = offset
            object_name = code.split(",", 1)[0].strip()
        if object_start is not None and ";" in code:
            end = offset + len(line)
            if object_name.casefold() == object_type.casefold():
                spans.append((object_start, end))
            object_start = None
            object_name = ""
        offset += len(line)
    return spans


def _replace_idf_field(block: str, label: str, value: str) -> str:
    pattern = re.compile(
        rf"^(\s*)[^,!;]*([,;]\s*!-\s*{re.escape(label)}(?:\s.*)?)$",
        re.MULTILINE | re.IGNORECASE,
    )
    updated, count = pattern.subn(rf"\g<1>{value}\g<2>", block, count=1)
    if count != 1:
        raise ValueError(f"Could not set RunPeriod field: {label}")
    return updated


def parse_energyplus_error_counts(text: str) -> tuple[int, int]:
    """Return warning and severe counts from the EnergyPlus completion line."""

    matches = re.findall(
        r"EnergyPlus Completed.*?(\d+)\s+Warning.*?(\d+)\s+Severe",
        text,
        flags=re.IGNORECASE,
    )
    if matches:
        warning, severe = matches[-1]
        return int(warning), int(severe)
    warning_count = len(re.findall(r"\*\*\s*Warning\s*\*\*", text))
    severe_count = len(re.findall(r"\*\*\s*Severe\s*\*\*", text))
    return warning_count, severe_count


def analyze_telemetry(path: Path) -> dict[str, Any]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = set(reader.fieldnames or [])

    required_fields = {
        "validated_supply_air_setpoint_c",
        "applied_supply_air_setpoint_c",
        "safety_corrected",
        "candidate_ids",
        "final_selected_policy_id",
        "llm_ranker_called",
        "llm_raw_ranking",
        "llm_selected_policy_id",
        "llm_confidence",
        "llm_reason",
        "llm_request_completed",
        "llm_retry_count",
        "llm_failure_category",
        "deterministic_fallback_used",
    }
    missing_fields = sorted(required_fields - fieldnames)

    validated = _float_values(rows, "validated_supply_air_setpoint_c")
    applied = _float_values(rows, "applied_supply_air_setpoint_c")
    changes = [
        abs(current - previous)
        for previous, current in zip(validated, validated[1:])
    ]

    opportunity_rows = [row for row in rows if _candidate_ids(row)]
    llm_rows = [
        row
        for row in opportunity_rows
        if _is_true(row.get("llm_ranker_called", ""))
    ]
    provenance_violations: list[dict[str, str]] = []
    for row in opportunity_rows:
        selected = row.get("final_selected_policy_id", "")
        candidates = _candidate_ids(row)
        if not selected or selected not in candidates:
            provenance_violations.append(
                {
                    "simulation_time": row.get("simulation_time", ""),
                    "selected": selected,
                    "candidates": ",".join(candidates),
                }
            )

    failed_llm_rows = [
        row for row in llm_rows if row.get("llm_failure_category", "")
    ]
    unsafe_failure_rows = [
        row
        for row in failed_llm_rows
        if not _is_true(row.get("deterministic_fallback_used", ""))
    ]
    reviews = [
        {
            "simulation_time": row.get("simulation_time", ""),
            "candidate_ids": _candidate_ids(row),
            "ranking": _json_list(row.get("llm_raw_ranking", "")),
            "selected_policy_id": row.get("llm_selected_policy_id", ""),
            "confidence": _optional_float(row.get("llm_confidence", "")),
            "reason": row.get("llm_reason", ""),
            "request_completed": _is_true(
                row.get("llm_request_completed", "")
            ),
            "retry_count": int(row.get("llm_retry_count", "0") or 0),
            "failure_category": row.get("llm_failure_category", ""),
            "fallback_used": _is_true(
                row.get("deterministic_fallback_used", "")
            ),
        }
        for row in llm_rows
    ]

    return {
        "telemetry_rows": len(rows),
        "missing_telemetry_fields": missing_fields,
        "supervisory_opportunities": len(opportunity_rows),
        "llm_calls": len(llm_rows),
        "forced_single_candidate_decisions": sum(
            _is_true(row.get("forced_single_candidate", ""))
            for row in opportunity_rows
        ),
        "llm_failures": len(failed_llm_rows),
        "unsafe_llm_failure_rows": len(unsafe_failure_rows),
        "deterministic_fallbacks": sum(
            _is_true(row.get("deterministic_fallback_used", ""))
            for row in opportunity_rows
        ),
        "safety_corrections": sum(
            _is_true(row.get("safety_corrected", "")) for row in rows
        ),
        "minimum_validated_setpoint_c": min(validated, default=None),
        "maximum_validated_setpoint_c": max(validated, default=None),
        "minimum_applied_setpoint_c": min(applied, default=None),
        "maximum_applied_setpoint_c": max(applied, default=None),
        "maximum_validated_change_c": max(changes, default=0.0),
        "setpoints_within_limits": bool(validated)
        and bool(applied)
        and all(22.0 <= value <= 25.0 for value in validated + applied),
        "maximum_change_within_limit": all(
            change <= 1.0 + 1e-9 for change in changes
        ),
        "candidate_provenance_violations": provenance_violations,
        "all_final_policies_from_candidate_set": (
            bool(opportunity_rows) and not provenance_violations
        ),
        "all_failures_fell_back_safely": not unsafe_failure_rows,
        "nvidia_response_reviews": reviews,
    }


def _float_values(rows: list[dict[str, str]], field: str) -> list[float]:
    return [
        float(row[field])
        for row in rows
        if row.get(field, "").strip()
    ]


def _candidate_ids(row: dict[str, str]) -> list[str]:
    return _json_list(row.get("candidate_ids", ""))


def _json_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _optional_float(value: str) -> float | None:
    return float(value) if value.strip() else None


def _is_true(value: str) -> bool:
    return value.strip().casefold() == "true"


def _blocked_result(reason: str) -> dict[str, Any]:
    return {
        "status": "blocked",
        "provider": "nvidia_nim",
        "model": MODEL,
        "request_made": False,
        "reason": reason,
    }


def run() -> dict[str, Any]:
    REPORTS.mkdir(parents=True, exist_ok=True)
    if not os.environ.get("NVIDIA_NIM_API_KEY", "").strip():
        return _blocked_result(
            "NVIDIA_NIM_API_KEY is not configured in this process."
        )
    if not GATE_RESULTS.exists():
        return _blocked_result("The NVIDIA six-case gate result is missing.")
    gate = json.loads(GATE_RESULTS.read_text(encoding="utf-8"))
    if not gate.get("eligible_for_one_day_smoke_test"):
        return _blocked_result("The NVIDIA six-case gate did not pass.")

    source_idf = ROOT / "1ZoneDataCenterCRAC_wApproachTemp.idf"
    generated_idf = REPORTS / "nvidia_nim_one_day_generated.idf"
    generated_idf.write_text(
        build_one_day_idf_text(source_idf.read_text(encoding="utf-8")),
        encoding="utf-8",
    )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = REPORTS / f"nvidia_nim_one_day_output_{stamp}"
    config = EnergyPlusConfig(
        idf_path=generated_idf,
        output_dir=output_dir,
        control_log_path=output_dir / "control_log.csv",
        summary_report_path=output_dir / "control_summary.txt",
        controller_type=ControllerType.HYBRID_SUPERVISORY,
        llm_provider=LLMProvider.NVIDIA_NIM,
        supervisor_enabled=True,
        supervisor_interval_hours=3.0,
        nvidia_nim_model=MODEL,
        nvidia_nim_base_url="https://integrate.api.nvidia.com/v1",
        nvidia_nim_timeout_s=30.0,
        nvidia_nim_max_retries=1,
        nvidia_nim_max_tokens=256,
        nvidia_nim_temperature=0.0,
        nvidia_nim_top_p=1.0,
    )

    started = time.perf_counter()
    exit_code = run_simulation(config)
    wall_clock_s = time.perf_counter() - started

    err_path = output_dir / "eplusout.err"
    err_text = (
        err_path.read_text(encoding="utf-8", errors="replace")
        if err_path.exists()
        else ""
    )
    warning_count, severe_count = parse_energyplus_error_counts(err_text)
    telemetry = analyze_telemetry(config.control_log_path)
    metrics_summary = _parse_metrics(config.summary_report_path)

    checks = {
        "energyplus_exit_code_zero": exit_code == 0,
        "zero_severe_errors": severe_count == 0,
        "telemetry_complete": (
            telemetry["telemetry_rows"] > 0
            and not telemetry["missing_telemetry_fields"]
        ),
        "physical_setpoint_within_22_to_25_c": telemetry[
            "setpoints_within_limits"
        ],
        "physical_change_within_1_c": telemetry[
            "maximum_change_within_limit"
        ],
        "all_policies_from_candidate_set": telemetry[
            "all_final_policies_from_candidate_set"
        ],
        "all_api_failures_fell_back_safely": telemetry[
            "all_failures_fell_back_safely"
        ],
        "exactly_one_day_of_control_timesteps": (
            telemetry["telemetry_rows"] == 144
        ),
        "exactly_eight_supervisory_opportunities": (
            telemetry["supervisory_opportunities"] == 8
        ),
    }
    return {
        "status": "pass" if all(checks.values()) else "fail",
        "manual_review_status": "pending",
        "provider": "nvidia_nim",
        "model": MODEL,
        "configuration": {
            "simulated_days": 1,
            "supervisor_interval_hours": 3.0,
            "timeout_s": 30.0,
            "maximum_retries": 1,
            "physical_setpoint_limits_c": [22.0, 25.0],
            "maximum_physical_change_c": 1.0,
        },
        "output_directory": str(output_dir.relative_to(ROOT)),
        "energyplus_exit_code": exit_code,
        "energyplus_warning_count": warning_count,
        "energyplus_severe_error_count": severe_count,
        "simulation_wall_clock_s": wall_clock_s,
        "checks": checks,
        "telemetry": telemetry,
        "metrics_summary": metrics_summary,
    }


def _parse_metrics(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        if ": " in line:
            key, value = line.split(": ", 1)
            result[key] = value
    return result


def write_results(result: dict[str, Any]) -> None:
    RESULTS_PATH.write_text(
        json.dumps(result, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# NVIDIA NIM One-Day EnergyPlus Smoke Test",
        "",
        f"**{result['status'].upper()}**",
        "",
        f"- Provider: `{result['provider']}`",
        f"- Model: `{result['model']}`",
    ]
    if result["status"] == "blocked":
        lines.extend(
            [
                "- EnergyPlus run: `NOT STARTED`",
                f"- Reason: {result['reason']}",
            ]
        )
    else:
        telemetry = result["telemetry"]
        lines.extend(
            [
                f"- EnergyPlus exit code: `{result['energyplus_exit_code']}`",
                (
                    "- EnergyPlus warnings: "
                    f"`{result['energyplus_warning_count']}`"
                ),
                (
                    "- EnergyPlus severe errors: "
                    f"`{result['energyplus_severe_error_count']}`"
                ),
                (
                    "- Simulation wall-clock duration: "
                    f"`{result['simulation_wall_clock_s']:.3f} s`"
                ),
                (
                    "- Supervisory opportunities: "
                    f"`{telemetry['supervisory_opportunities']}`"
                ),
                f"- Actual NVIDIA calls: `{telemetry['llm_calls']}`",
                f"- Deterministic fallbacks: `{telemetry['deterministic_fallbacks']}`",
                f"- Safety corrections: `{telemetry['safety_corrections']}`",
                (
                    "- Validated setpoint range: "
                    f"`{telemetry['minimum_validated_setpoint_c']}` to "
                    f"`{telemetry['maximum_validated_setpoint_c']} C`"
                ),
                (
                    "- Maximum physical decision change: "
                    f"`{telemetry['maximum_validated_change_c']:.3f} C`"
                ),
                (
                    "- Manual response review: "
                    f"`{result['manual_review_status'].upper()}`"
                ),
                "",
                "## Automated Checks",
                "",
            ]
        )
        lines.extend(
            f"- {name}: `{'PASS' if passed else 'FAIL'}`"
            for name, passed in result["checks"].items()
        )
        lines.extend(["", "## NVIDIA Responses", ""])
        reviews = telemetry["nvidia_response_reviews"]
        if not reviews:
            lines.append("No real NVIDIA calls were required.")
        for index, review in enumerate(reviews, start=1):
            lines.extend(
                [
                    f"### Response {index}",
                    "",
                    f"- Simulation time: `{review['simulation_time']}`",
                    (
                        "- Candidates: `"
                        + ",".join(review["candidate_ids"])
                        + "`"
                    ),
                    "- Ranking: `" + ",".join(review["ranking"]) + "`",
                    (
                        "- Selected: "
                        f"`{review['selected_policy_id']}`"
                    ),
                    f"- Confidence: `{review['confidence']}`",
                    f"- Reason: {review['reason']}",
                    (
                        "- Fallback: "
                        f"`{review['fallback_used']}`"
                    ),
                    "",
                ]
            )
        manual_review = result.get("manual_review")
        if isinstance(manual_review, dict):
            lines.extend(
                [
                    "## Manual Review",
                    "",
                    (
                        "- Responses reviewed: "
                        f"`{manual_review['responses_reviewed']}`"
                    ),
                    (
                        "- Bounded contract compliance: "
                        f"`{manual_review['bounded_contract_compliance']}`"
                    ),
                    (
                        "- Selection safety: "
                        f"`{manual_review['selection_safety']}`"
                    ),
                    (
                        "- Semantic precision: "
                        f"`{manual_review['semantic_precision']}`"
                    ),
                    (
                        "- Deterministic-ranking agreement: "
                        f"`{manual_review['deterministic_agreement']}`"
                    ),
                    "",
                ]
            )
            lines.extend(
                f"- {finding}"
                for finding in manual_review.get("findings", [])
            )
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    try:
        result = run()
    except Exception as exc:
        result = {
            "status": "fail",
            "manual_review_status": "not_started",
            "provider": "nvidia_nim",
            "model": MODEL,
            "failure_type": type(exc).__name__,
            "reason": str(exc),
        }
    write_results(result)
    print(
        f"[NVIDIA One-Day EnergyPlus] status={result['status']} "
        f"manual_review={result.get('manual_review_status', 'not_started')}"
    )
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
