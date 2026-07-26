from __future__ import annotations

import argparse
import contextlib
import csv
import json
import math
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from energyplus.config import (  # noqa: E402
    ActuatorControlMode,
    ControllerType,
    EnergyPlusConfig,
)
from energyplus.runner import run_simulation  # noqa: E402
from llm.client import MockResponseMode  # noqa: E402


DECISION_INTERVAL = 6
EXPECTED_TIMESTEPS = 9216
EXPECTED_LLM_CALLS = EXPECTED_TIMESTEPS // DECISION_INTERVAL
EXPECTED_LLM_DECISIONS = EXPECTED_LLM_CALLS + 1  # startup rule action
EXPECTED_REUSED_ACTIONS = EXPECTED_TIMESTEPS - EXPECTED_LLM_DECISIONS
# Three initial failed calls trigger cooldown. Because the consecutive-failure
# count resets only after success, each failed retry starts another cooldown.
EXPECTED_FAILURE_CALLS = 3 + math.ceil((EXPECTED_LLM_CALLS - 6) / 4)
EXPECTED_COOLDOWN_ACTIVATIONS = EXPECTED_FAILURE_CALLS - 2


@dataclass(frozen=True)
class Scenario:
    name: str
    controller_type: ControllerType
    mock_mode: MockResponseMode = MockResponseMode.VALID


SCENARIOS = [
    Scenario("rule", ControllerType.RULE),
    Scenario("llm_valid", ControllerType.LLM, MockResponseMode.VALID),
    Scenario("llm_unsafe_low", ControllerType.LLM, MockResponseMode.UNSAFE_LOW),
    Scenario("llm_unsafe_high", ControllerType.LLM, MockResponseMode.UNSAFE_HIGH),
    Scenario(
        "llm_malformed_json",
        ControllerType.LLM,
        MockResponseMode.MALFORMED_JSON,
    ),
    Scenario(
        "llm_missing_field",
        ControllerType.LLM,
        MockResponseMode.MISSING_FIELD,
    ),
    Scenario(
        "llm_wrong_type",
        ControllerType.LLM,
        MockResponseMode.WRONG_TYPE,
    ),
    Scenario(
        "llm_wrong_field",
        ControllerType.LLM,
        MockResponseMode.WRONG_FIELD,
    ),
    Scenario(
        "llm_empty_response",
        ControllerType.LLM,
        MockResponseMode.EMPTY_RESPONSE,
    ),
    Scenario("llm_exception", ControllerType.LLM, MockResponseMode.EXCEPTION),
    Scenario("llm_timeout", ControllerType.LLM, MockResponseMode.TIMEOUT),
    Scenario(
        "llm_alternating",
        ControllerType.LLM,
        MockResponseMode.ALTERNATING,
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--aggregate-only", action="store_true")
    parser.add_argument(
        "--scenario",
        action="append",
        choices=[scenario.name for scenario in SCENARIOS],
    )
    args = parser.parse_args()

    base_output = ROOT / "sampleSimulation" / "semantic_validation_runs"
    base_output.mkdir(parents=True, exist_ok=True)
    if args.aggregate_only:
        return aggregate_existing_results(base_output)

    selected_names = set(args.scenario or [])
    scenarios = (
        [item for item in SCENARIOS if item.name in selected_names]
        if selected_names
        else SCENARIOS
    )
    results = []
    for scenario in scenarios:
        run_dir = base_output / scenario.name
        _prepare_run_directory(base_output, run_dir)
        config = EnergyPlusConfig(
            output_dir=run_dir,
            control_log_path=run_dir / "control_log.csv",
            summary_report_path=run_dir / "control_summary.txt",
            controller_type=scenario.controller_type,
            mock_llm_mode=scenario.mock_mode,
            actuator_control_mode=ActuatorControlMode.SUPPLY_NODE_SETPOINT,
            llm_decision_interval_timesteps=DECISION_INTERVAL,
        )
        console_log = run_dir / "console.log"
        print(f"[Integration] Running {scenario.name}...")
        with console_log.open("w", encoding="utf-8") as log_file:
            with contextlib.redirect_stdout(log_file):
                exit_code = run_simulation(config)

        result = collect_result(scenario, run_dir, exit_code, console_log)
        results.append(result)
        print(
            f"[Integration] {scenario.name}: exit={exit_code}, "
            f"severe={result['severe_errors']}, rows={result['csv_rows']}, "
            f"calls={result.get('Total LLM Requests', 'n/a')}, "
            f"fallbacks={result.get('Total RuleController Fallbacks', 'n/a')}"
        )

    return write_reports(results)


def _prepare_run_directory(base_output: Path, run_dir: Path) -> None:
    if run_dir.exists():
        resolved_run_dir = run_dir.resolve()
        if (
            resolved_run_dir.parent != base_output.resolve()
            or resolved_run_dir == base_output.resolve()
        ):
            raise RuntimeError(f"Refusing to clean unexpected path: {run_dir}")
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)


def aggregate_existing_results(base_output: Path) -> int:
    results = []
    for scenario in SCENARIOS:
        run_dir = base_output / scenario.name
        required_paths = [
            run_dir / "eplusout.end",
            run_dir / "eplusout.err",
            run_dir / "control_log.csv",
            run_dir / "control_summary.txt",
            run_dir / "console.log",
        ]
        missing = [str(path) for path in required_paths if not path.exists()]
        if missing:
            raise RuntimeError(
                f"Cannot aggregate incomplete scenario {scenario.name}: {missing}"
            )
        summary = parse_summary(run_dir / "control_summary.txt")
        results.append(
            collect_result(
                scenario,
                run_dir,
                int(summary.get("EnergyPlus Exit Code", "-1")),
                run_dir / "console.log",
            )
        )
    return write_reports(results)


def write_reports(results: list[dict[str, object]]) -> int:
    report_dir = ROOT / "test_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "semantic_mock_validation_results.json"
    markdown_path = report_dir / "semantic_mock_validation_report.md"
    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    markdown_path.write_text(build_markdown_report(results), encoding="utf-8")
    print(f"[Integration] JSON results: {json_path}")
    print(f"[Integration] Report: {markdown_path}")
    return 0 if all(result["passed"] for result in results) else 1


def collect_result(
    scenario: Scenario,
    run_dir: Path,
    exit_code: int,
    console_log: Path,
) -> dict[str, object]:
    err_text = (run_dir / "eplusout.err").read_text(
        encoding="utf-8",
        errors="ignore",
    )
    warnings, severe_errors = parse_error_counts(err_text)
    summary = parse_summary(run_dir / "control_summary.txt")
    csv_path = run_dir / "control_log.csv"
    csv_inspection = inspect_csv(csv_path)

    result: dict[str, object] = {
        "name": scenario.name,
        "controller_type": scenario.controller_type.value,
        "mock_mode": scenario.mock_mode.value,
        "exit_code": exit_code,
        "warnings": warnings,
        "severe_errors": severe_errors,
        "actuator_control_mode": ActuatorControlMode.SUPPLY_NODE_SETPOINT.value,
        "decision_interval_timesteps": DECISION_INTERVAL,
        "actual_timestep_minutes": 10,
        "actual_llm_interval_minutes": 60,
        "summary_report_path": str(run_dir / "control_summary.txt"),
        "csv_path": str(csv_path),
        "console_log_path": str(console_log),
    }
    result.update(summary)
    result.update(csv_inspection)
    result["passed"] = evaluate_pass(result)
    return result


def parse_error_counts(err_text: str) -> tuple[int, int]:
    match = re.search(
        r"Completed Successfully--\s*(\d+)\s*Warning;\s*(\d+)\s*Severe Errors",
        err_text,
    )
    if match is None:
        return 0, 0
    return int(match.group(1)), int(match.group(2))


def parse_summary(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if ": " in line:
            key, value = line.split(": ", 1)
            values[key] = value
    return values


def inspect_csv(path: Path) -> dict[str, object]:
    with path.open(newline="", encoding="utf-8") as file:
        raw_rows = list(csv.reader(file))
    header_width_ok = bool(raw_rows) and all(
        len(row) == len(raw_rows[0]) for row in raw_rows
    )
    with path.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))

    required_columns = {
        "requested_supply_air_setpoint_c",
        "validated_supply_air_setpoint_c",
        "applied_supply_air_setpoint_c",
        "measured_node_setpoint_c",
        "measured_supply_air_temperature_c",
        "llm_call_due",
        "llm_call_made",
        "action_reused",
        "decision_interval_timesteps",
        "timesteps_since_last_llm_call",
    }
    actual_columns = set(raw_rows[0]) if raw_rows else set()
    semantic_columns_present = required_columns <= actual_columns
    ambiguous_legacy_columns_absent = not {
        "cooling_setpoint",
        "cooling_setpoint_c",
        "measured_cooling_setpoint_c",
    } & actual_columns

    node_samples = 0
    applied_node_matches = 0
    prior_validated_timing_matches = 0
    llm_due_rows = 0
    llm_call_rows = 0
    reused_rows = 0
    first_llm_row: dict[str, str] | None = None
    for index, row in enumerate(rows):
        if row.get("llm_call_due") == "True":
            llm_due_rows += 1
            if first_llm_row is None:
                first_llm_row = row
        if row.get("llm_call_made") == "True":
            llm_call_rows += 1
        if row.get("action_reused") == "True":
            reused_rows += 1

        measured = row.get("measured_node_setpoint_c", "")
        applied = row.get("applied_supply_air_setpoint_c", "")
        if measured:
            node_samples += 1
        if measured and applied and abs(float(measured) - float(applied)) <= 0.01:
            applied_node_matches += 1
        if index > 0 and applied:
            prior_validated = rows[index - 1].get(
                "validated_supply_air_setpoint_c",
                "",
            )
            if (
                prior_validated
                and abs(float(applied) - float(prior_validated)) <= 0.01
            ):
                prior_validated_timing_matches += 1

    first_row = rows[0] if rows else {}
    return {
        "csv_rows": len(raw_rows),
        "csv_header_width_ok": header_width_ok,
        "semantic_columns_present": semantic_columns_present,
        "ambiguous_legacy_columns_absent": ambiguous_legacy_columns_absent,
        "node_setpoint_samples": node_samples,
        "applied_node_matches": applied_node_matches,
        "prior_validated_timing_matches": prior_validated_timing_matches,
        "llm_due_rows": llm_due_rows,
        "llm_call_rows": llm_call_rows,
        "reused_rows": reused_rows,
        "startup_decision_source": first_row.get("decision_source", ""),
        "first_llm_strategy": (
            first_llm_row.get("strategy", "") if first_llm_row else ""
        ),
        "first_llm_requested_setpoint": (
            first_llm_row.get("requested_supply_air_setpoint_c", "")
            if first_llm_row
            else ""
        ),
        "first_llm_validated_setpoint": (
            first_llm_row.get("validated_supply_air_setpoint_c", "")
            if first_llm_row
            else ""
        ),
        "first_llm_safety_corrected": (
            first_llm_row.get("safety_corrected", "")
            if first_llm_row
            else ""
        ),
        "first_llm_fallback_used": (
            first_llm_row.get("fallback_used", "")
            if first_llm_row
            else ""
        ),
    }


def evaluate_pass(result: dict[str, object]) -> bool:
    basic_checks = [
        result["exit_code"] == 0,
        result["severe_errors"] == 0,
        int(result["csv_rows"]) == EXPECTED_TIMESTEPS + 1,
        bool(result["csv_header_width_ok"]),
        bool(result["semantic_columns_present"]),
        bool(result["ambiguous_legacy_columns_absent"]),
        int(result["node_setpoint_samples"]) == EXPECTED_TIMESTEPS,
        int(result["applied_node_matches"]) >= EXPECTED_TIMESTEPS - 1,
        int(result["prior_validated_timing_matches"]) == EXPECTED_TIMESTEPS - 1,
        result["startup_decision_source"] in {"startup_rule", "rule"},
    ]
    if not all(basic_checks):
        return False

    decisions = _summary_int(result, "Total Controller Decisions")
    control_timesteps = _summary_int(result, "Total Control Timesteps")
    reused = _summary_int(result, "Total Reused Actions")
    safety = _summary_int(result, "Total Safety Corrections")
    llm_requests = _summary_int(result, "Total LLM Requests")
    llm_failures = _summary_int(result, "Total LLM Failures")
    fallbacks = _summary_int(result, "Total RuleController Fallbacks")
    changes = _summary_int(result, "Total Supply-Air Setpoint Changes")
    cooldowns = _summary_int(result, "Total LLM Cooldown Activations")
    name = str(result["name"])

    if control_timesteps != EXPECTED_TIMESTEPS:
        return False
    if name == "rule":
        return (
            decisions == EXPECTED_TIMESTEPS
            and reused == 0
            and llm_requests == 0
            and llm_failures == 0
            and fallbacks == 0
        )

    cadence_ok = (
        decisions == EXPECTED_LLM_DECISIONS
        and reused == EXPECTED_REUSED_ACTIONS
        and int(result["llm_due_rows"]) == EXPECTED_LLM_CALLS
        and int(result["reused_rows"]) == EXPECTED_REUSED_ACTIONS
    )
    if not cadence_ok:
        return False

    if name == "llm_valid":
        return (
            llm_requests == EXPECTED_LLM_CALLS
            and llm_failures == 0
            and fallbacks == 0
            and result["first_llm_strategy"] == "moderate_cooling"
            and result["first_llm_requested_setpoint"] == "23.000"
            and result["first_llm_safety_corrected"] == "False"
        )
    if name == "llm_unsafe_low":
        return (
            llm_requests == EXPECTED_LLM_CALLS
            and safety == EXPECTED_LLM_CALLS
            and llm_failures == 0
            and fallbacks == 0
            and result["first_llm_requested_setpoint"] == "18.000"
            and result["first_llm_validated_setpoint"] == "22.000"
        )
    if name == "llm_unsafe_high":
        return (
            llm_requests == EXPECTED_LLM_CALLS
            and safety == EXPECTED_LLM_CALLS
            and llm_failures == 0
            and fallbacks == 0
            and result["first_llm_requested_setpoint"] == "30.000"
            and result["first_llm_validated_setpoint"] == "23.000"
        )
    if name == "llm_alternating":
        return (
            llm_requests == EXPECTED_LLM_CALLS
            and llm_failures == 0
            and fallbacks == 0
            and changes > 1
        )

    return (
        llm_requests == EXPECTED_FAILURE_CALLS
        and int(result["llm_call_rows"]) == EXPECTED_FAILURE_CALLS
        and llm_failures == EXPECTED_FAILURE_CALLS
        and fallbacks == EXPECTED_LLM_CALLS
        and cooldowns == EXPECTED_COOLDOWN_ACTIVATIONS
        and result["first_llm_fallback_used"] == "True"
    )


def _summary_int(result: dict[str, object], key: str) -> int:
    return int(str(result.get(key, "0")))


def expected_behavior(name: str) -> str:
    if name == "rule":
        return "Rule baseline decides every timestep with no LLM calls"
    if name == "llm_valid":
        return "Valid supply-air JSON is called every six timesteps"
    if name == "llm_unsafe_low":
        return "18 C is clamped to the 22 C physical minimum"
    if name == "llm_unsafe_high":
        return "30 C is clamped and rate-limited from the prior action"
    if name == "llm_alternating":
        return "Alternating node targets exercise rate and change counting"
    return "Strict parser/client failure invokes validated RuleController fallback"


def build_markdown_report(results: list[dict[str, object]]) -> str:
    lines = [
        "# Semantic Mock Validation Report",
        "",
        "Physical control variable: supply-air temperature setpoint for `MAIN COOLING COIL 1 OUTLET NODE`.",
        "Allowed range: 22.0 C to 25.0 C. Maximum change: 1.0 C per decision.",
        "Configured LLM interval: 6 zone timesteps.",
        "Actual IDF timestep: 10 minutes, so the interval is one simulated hour.",
        "",
        "| Scenario | Expected | Calls | Reused | Safety | Failures | Fallbacks | Pass |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for result in results:
        lines.append(
            f"| {result['name']} | {expected_behavior(str(result['name']))} | "
            f"{result.get('Total LLM Requests', 'n/a')} | "
            f"{result.get('Total Reused Actions', 'n/a')} | "
            f"{result.get('Total Safety Corrections', 'n/a')} | "
            f"{result.get('Total LLM Failures', 'n/a')} | "
            f"{result.get('Total RuleController Fallbacks', 'n/a')} | "
            f"{result['passed']} |"
        )
    lines.extend(
        [
            "",
            "Every scenario also requires exit code 0, zero severe errors, "
            "9,216 sensor rows, the semantic telemetry schema, measured/applied "
            "node agreement, and the one-zone-timestep action delay.",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
