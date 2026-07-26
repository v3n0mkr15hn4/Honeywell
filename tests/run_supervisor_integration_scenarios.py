"""Mock-only EnergyPlus validation for hybrid supervisory control."""

from __future__ import annotations

import argparse
import contextlib
import csv
import json
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
    LLMProvider,
)
from energyplus.runner import run_simulation  # noqa: E402
from llm.supervisor_mock_client import (  # noqa: E402
    SupervisorMockMode,
)

EXPECTED_TIMESTEPS = 9216


@dataclass(frozen=True)
class Scenario:
    name: str
    mode: SupervisorMockMode = SupervisorMockMode.VALID_BALANCED
    supervisor_enabled: bool = True
    interval_hours: float = 6.0
    grace_hours: float = 2.0


SCENARIOS = [
    Scenario("default_policy_no_llm", supervisor_enabled=False),
    Scenario("valid_balanced"),
    Scenario(
        "thermal_priority",
        SupervisorMockMode.VALID_THERMAL_PRIORITY,
    ),
    Scenario(
        "energy_priority",
        SupervisorMockMode.VALID_ENERGY_PRIORITY,
    ),
    Scenario(
        "unsafe_policy_corrected",
        SupervisorMockMode.UNSAFE_NUMERIC_VALUES,
    ),
    Scenario("invalid_enum_fallback", SupervisorMockMode.INVALID_ENUM),
    Scenario(
        "direct_actuator_rejected",
        SupervisorMockMode.DIRECT_ACTUATOR_FIELD_ATTEMPT,
    ),
    Scenario("malformed_json_fallback", SupervisorMockMode.MALFORMED_JSON),
    Scenario("timeout_fallback", SupervisorMockMode.TIMEOUT),
    Scenario(
        "expired_policy_fallback",
        SupervisorMockMode.VALID_THEN_EXCEPTION,
        interval_hours=4.0,
        grace_hours=1.0,
    ),
    Scenario(
        "cooldown_behavior",
        SupervisorMockMode.EXCEPTION,
        interval_hours=4.0,
    ),
    Scenario(
        "alternating_policy",
        SupervisorMockMode.ALTERNATING_POLICY,
        interval_hours=4.0,
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scenario",
        action="append",
        choices=[scenario.name for scenario in SCENARIOS],
    )
    parser.add_argument("--aggregate-only", action="store_true")
    args = parser.parse_args()
    base = ROOT / "sampleSimulation" / "hybrid_supervisor_validation"
    base.mkdir(parents=True, exist_ok=True)
    selected_names = set(args.scenario or [])
    selected = [
        scenario
        for scenario in SCENARIOS
        if not selected_names or scenario.name in selected_names
    ]
    if args.aggregate_only:
        results = [
            collect_result(scenario, base / scenario.name)
            for scenario in selected
        ]
        return write_reports(results)

    results = []
    for scenario in selected:
        run_dir = base / scenario.name
        _prepare_directory(base, run_dir)
        config = EnergyPlusConfig(
            output_dir=run_dir,
            control_log_path=run_dir / "control_log.csv",
            summary_report_path=run_dir / "control_summary.txt",
            controller_type=ControllerType.HYBRID_SUPERVISORY,
            llm_provider=LLMProvider.MOCK,
            mock_supervisor_mode=scenario.mode,
            supervisor_enabled=scenario.supervisor_enabled,
            supervisor_interval_hours=scenario.interval_hours,
            supervisor_policy_grace_period_hours=scenario.grace_hours,
            actuator_control_mode=ActuatorControlMode.SUPPLY_NODE_SETPOINT,
        )
        console_path = run_dir / "console.log"
        print(f"[Hybrid Integration] Running {scenario.name}...", flush=True)
        with console_path.open("w", encoding="utf-8") as log:
            with contextlib.redirect_stdout(log):
                exit_code = run_simulation(config)
        result = collect_result(scenario, run_dir, exit_code)
        results.append(result)
        print(
            f"[Hybrid Integration] {scenario.name}: "
            f"exit={result['exit_code']} severe={result['severe_errors']} "
            f"calls={result['supervisory_calls']} "
            f"fallbacks={result['supervisory_fallbacks']} "
            f"pass={result['passed']}",
            flush=True,
        )
    return write_reports(results)


def collect_result(
    scenario: Scenario,
    run_dir: Path,
    exit_code: int | None = None,
) -> dict[str, object]:
    summary = _parse_summary(run_dir / "control_summary.txt")
    if exit_code is None:
        exit_code = int(summary.get("EnergyPlus Exit Code", "-1"))
    err_text = (run_dir / "eplusout.err").read_text(
        encoding="utf-8",
        errors="ignore",
    )
    match = re.search(
        r"Completed Successfully--\s*(\d+)\s*Warning;\s*(\d+)\s*Severe Errors",
        err_text,
    )
    warnings = int(match.group(1)) if match else 0
    severe = int(match.group(2)) if match else 0
    csv_result = _inspect_csv(run_dir / "control_log.csv")
    result: dict[str, object] = {
        "scenario": scenario.name,
        "mock_mode": scenario.mode.value,
        "supervisor_enabled": scenario.supervisor_enabled,
        "supervisor_interval_hours": scenario.interval_hours,
        "exit_code": exit_code,
        "warnings": warnings,
        "severe_errors": severe,
        "control_log": str(run_dir / "control_log.csv"),
        "summary_report": str(run_dir / "control_summary.txt"),
        "console_log": str(run_dir / "console.log"),
        "supervisory_calls": int(summary.get("Total Supervisory Calls", "0")),
        "successful_supervisory_calls": int(
            summary.get("Successful Supervisory Calls", "0")
        ),
        "supervisory_parser_failures": int(
            summary.get("Supervisory Parser Failures", "0")
        ),
        "supervisory_timeouts": int(
            summary.get("Supervisory Timeouts", "0")
        ),
        "supervisory_fallbacks": int(
            summary.get("Supervisory Fallbacks", "0")
        ),
        "policy_validation_corrections": int(
            summary.get("Policy Validation Corrections", "0")
        ),
        "policy_changes": int(summary.get("Policy Changes", "0")),
        "default_policy_usage": int(
            summary.get("Default Policy Usage Count", "0")
        ),
        "cooldown_activations": int(
            summary.get("Supervisor Cooldown Activations", "0")
        ),
        "physical_safety_corrections": int(
            summary.get("Total Safety Corrections", "0")
        ),
        "physical_actuator_changes": int(
            summary.get("Total Supply-Air Setpoint Changes", "0")
        ),
        "control_timesteps": int(
            summary.get("Total Control Timesteps", "0")
        ),
        "controller_decisions": int(
            summary.get("Total Controller Decisions", "0")
        ),
    }
    result.update(csv_result)
    result["passed"] = _passes(scenario, result)
    return result


def _inspect_csv(path: Path) -> dict[str, object]:
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        fields = set(reader.fieldnames or [])
        rows = list(reader)
    required = {
        "requested_supply_air_setpoint_c",
        "validated_supply_air_setpoint_c",
        "applied_supply_air_setpoint_c",
        "measured_node_setpoint_c",
        "supervisor_enabled",
        "supervisor_call_due",
        "supervisor_called",
        "supervisor_fallback_used",
        "thermal_priority",
        "energy_priority",
        "controller_aggressiveness",
        "target_zone_temperature_c",
        "policy_strategy",
        "policy_validation_status",
    }
    requested = [
        float(row["requested_supply_air_setpoint_c"])
        for row in rows
        if row["requested_supply_air_setpoint_c"]
    ]
    validated = [
        float(row["validated_supply_air_setpoint_c"])
        for row in rows
        if row["validated_supply_air_setpoint_c"]
    ]
    applied_matches = 0
    timing_matches = 0
    for index, row in enumerate(rows):
        measured = row["measured_node_setpoint_c"]
        applied = row["applied_supply_air_setpoint_c"]
        if measured and applied and abs(float(measured) - float(applied)) <= 0.01:
            applied_matches += 1
        if index > 0 and applied:
            prior = rows[index - 1]["validated_supply_air_setpoint_c"]
            if prior and abs(float(applied) - float(prior)) <= 0.01:
                timing_matches += 1
    policy_strategies = sorted(
        {row["policy_strategy"] for row in rows if row["policy_strategy"]}
    )
    return {
        "csv_data_rows": len(rows),
        "supervisor_columns_present": required <= fields,
        "physical_requested_inside_range": all(
            22.0 <= value <= 25.0 for value in requested
        ),
        "physical_validated_inside_range": all(
            22.0 <= value <= 25.0 for value in validated
        ),
        "physical_rate_limit_respected": all(
            abs(current - previous) <= 1.0 + 1e-9
            for previous, current in zip(validated, validated[1:])
        ),
        "applied_node_matches": applied_matches,
        "prior_validated_timing_matches": timing_matches,
        "supervisor_called_rows": sum(
            row["supervisor_called"] == "True" for row in rows
        ),
        "supervisor_fallback_rows": sum(
            row["supervisor_fallback_used"] == "True" for row in rows
        ),
        "policy_strategies": policy_strategies,
        "direct_actuator_policy_field_present": (
            "supply_air_temperature_setpoint" in fields
        ),
    }


def _passes(scenario: Scenario, result: dict[str, object]) -> bool:
    base = all(
        [
            result["exit_code"] == 0,
            result["severe_errors"] == 0,
            result["csv_data_rows"] == EXPECTED_TIMESTEPS,
            result["control_timesteps"] == EXPECTED_TIMESTEPS,
            result["controller_decisions"] == EXPECTED_TIMESTEPS,
            bool(result["supervisor_columns_present"]),
            bool(result["physical_requested_inside_range"]),
            bool(result["physical_validated_inside_range"]),
            bool(result["physical_rate_limit_respected"]),
            int(result["applied_node_matches"]) >= EXPECTED_TIMESTEPS - 1,
            int(result["prior_validated_timing_matches"])
            == EXPECTED_TIMESTEPS - 1,
            not bool(result["direct_actuator_policy_field_present"]),
        ]
    )
    if not base:
        return False
    calls = int(result["supervisory_calls"])
    fallbacks = int(result["supervisory_fallbacks"])
    name = scenario.name
    if name == "default_policy_no_llm":
        return calls == 0 and fallbacks == 0
    if calls <= 0:
        return False
    if name in {"valid_balanced", "thermal_priority", "energy_priority"}:
        return (
            int(result["successful_supervisory_calls"]) == calls
            and fallbacks == 0
        )
    if name == "unsafe_policy_corrected":
        return int(result["policy_validation_corrections"]) > 0
    if name in {
        "invalid_enum_fallback",
        "direct_actuator_rejected",
        "malformed_json_fallback",
    }:
        return fallbacks > 0 and int(result["supervisory_parser_failures"]) > 0
    if name == "timeout_fallback":
        return fallbacks > 0 and int(result["supervisory_timeouts"]) > 0
    if name == "expired_policy_fallback":
        return (
            fallbacks > 0
            and int(result["default_policy_usage"]) > 0
            and "temporary_thermal" in result["policy_strategies"]
            and "balanced_default" in result["policy_strategies"]
        )
    if name == "cooldown_behavior":
        return fallbacks > 0 and int(result["cooldown_activations"]) > 0
    if name == "alternating_policy":
        return int(result["policy_changes"]) > 1
    return False


def _parse_summary(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if ": " in line:
            key, value = line.split(": ", 1)
            values[key] = value
    return values


def _prepare_directory(base: Path, run_dir: Path) -> None:
    if run_dir.exists():
        resolved = run_dir.resolve()
        if resolved.parent != base.resolve() or resolved == base.resolve():
            raise RuntimeError(f"Refusing to clean unexpected path: {run_dir}")
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)


def write_reports(results: list[dict[str, object]]) -> int:
    report_dir = ROOT / "test_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "supervisor_mock_validation_results.json"
    report_path = report_dir / "supervisor_mock_validation_report.md"
    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    lines = [
        "# Supervisor Mock Validation Report",
        "",
        (
            "Every physical action was produced by PolicyAwareRuleController "
            "and passed through the unchanged SafetyValidator."
        ),
        "",
        "| Scenario | Calls | Fallbacks | Policy corrections | Physical changes | Exit | Severe | Pass |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for result in results:
        lines.append(
            f"| {result['scenario']} | {result['supervisory_calls']} | "
            f"{result['supervisory_fallbacks']} | "
            f"{result['policy_validation_corrections']} | "
            f"{result['physical_actuator_changes']} | "
            f"{result['exit_code']} | {result['severe_errors']} | "
            f"{result['passed']} |"
        )
    lines.extend(
        [
            "",
            (
                "No real model was called. The supervisory contract contains "
                "no physical actuator setpoint field."
            ),
            "",
        ]
    )
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[Hybrid Integration] Results: {json_path}")
    print(f"[Hybrid Integration] Report: {report_path}")
    return 0 if all(bool(result["passed"]) for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
