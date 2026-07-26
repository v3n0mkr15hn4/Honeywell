from __future__ import annotations

import contextlib
import csv
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from energyplus.config import ControllerType, EnergyPlusConfig
from energyplus.runner import run_simulation
from llm.client import MockResponseMode


VARIABLES = [
    "Zone Mean Air Temperature",
    "Zone Operative Temperature",
    "Facility Total Electricity Demand Rate",
    "Facility Total HVAC Electricity Demand Rate",
    "Cooling Coil Electricity Rate",
    "Cooling Coil Total Cooling Rate",
    "Cooling Coil Sensible Cooling Rate",
    "Zone Thermostat Control Type",
    "Zone Cooling Setpoint Not Met Time",
    "Cooling Return Air Setpoint Schedule:Schedule Value",
]


@dataclass(frozen=True)
class ABRun:
    name: str
    cooling_setpoint: float
    mode: MockResponseMode


RUNS = [
    ABRun("cooling_22", 22.0, MockResponseMode.COOLING_22),
    ABRun("cooling_30", 30.0, MockResponseMode.COOLING_30),
]


def main() -> int:
    base_output = ROOT / "sampleSimulation" / "physical_ab_runs"
    base_output.mkdir(parents=True, exist_ok=True)

    run_results = {}
    for run in RUNS:
        print(f"[Physical A/B] Running {run.name}...")
        run_results[run.name] = run_case(base_output, run)

    comparison = compare_runs(run_results["cooling_22"], run_results["cooling_30"])
    report_dir = ROOT / "test_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "actuator_physical_validation_results.json"
    report_path = report_dir / "actuator_physical_validation_report.md"
    json_path.write_text(json.dumps(comparison, indent=2), encoding="utf-8")
    report_path.write_text(build_report(comparison), encoding="utf-8")
    print(f"[Physical A/B] JSON results: {json_path}")
    print(f"[Physical A/B] Report: {report_path}")
    return 0 if comparison["physical_effect_detected"] else 1


def run_case(base_output: Path, run: ABRun) -> dict[str, object]:
    run_dir = base_output / run.name
    run_dir.mkdir(parents=True, exist_ok=True)
    config = EnergyPlusConfig(
        output_dir=run_dir,
        control_log_path=run_dir / "control_log.csv",
        summary_report_path=run_dir / "control_summary.txt",
        controller_type=ControllerType.LLM,
        mock_llm_mode=run.mode,
    )
    console_log = run_dir / "console.log"
    with console_log.open("w", encoding="utf-8") as log_file:
        with contextlib.redirect_stdout(log_file):
            exit_code = run_simulation(config)

    csv_rows = read_csv_rows(config.control_log_path)
    eso = parse_eso(run_dir / "eplusout.eso")
    warnings, severe_errors = parse_error_counts((run_dir / "eplusout.err").read_text())

    return {
        "name": run.name,
        "cooling_setpoint": run.cooling_setpoint,
        "mode": run.mode.value,
        "exit_code": exit_code,
        "warnings": warnings,
        "severe_errors": severe_errors,
        "run_dir": str(run_dir),
        "csv_path": str(config.control_log_path),
        "summary_path": str(config.summary_report_path),
        "console_log_path": str(console_log),
        "applied_console_values": parse_applied_values(console_log),
        "first_csv_rows": csv_rows[:6],
        "csv_row_count": len(csv_rows),
        "eso": eso,
    }


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def parse_eso(path: Path) -> dict[str, object]:
    dictionary: dict[int, dict[str, str]] = {}
    data: dict[int, list[float]] = {}
    in_dictionary = True

    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line == "End of Data Dictionary":
            in_dictionary = False
            continue
        if in_dictionary:
            parsed = parse_dictionary_line(line)
            if parsed:
                dictionary[parsed["id"]] = parsed
            continue

        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 2:
            continue
        try:
            record_id = int(parts[0])
            value = float(parts[1])
        except ValueError:
            continue
        data.setdefault(record_id, []).append(value)

    selected: dict[str, dict[str, object]] = {}
    for target in VARIABLES:
        variable = find_variable(dictionary, target)
        if variable is None:
            selected[target] = {"available": False}
            continue

        values = data.get(variable["id"], [])
        selected[target] = {
            "available": True,
            "id": variable["id"],
            "key": variable["key"],
            "name": variable["name"],
            "units": variable["units"],
            "count": len(values),
            "min": safe_min(values),
            "max": safe_max(values),
            "mean": safe_mean(values),
            "sum": safe_sum(values),
            "first_values": values[:6],
        }

    return selected


def parse_dictionary_line(line: str) -> dict[str, object] | None:
    match = re.match(r"^(\d+),\d+,([^,]+),(.+?)\s*\[([^\]]*)\]", line)
    if not match:
        return None
    return {
        "id": int(match.group(1)),
        "key": match.group(2).strip(),
        "name": match.group(3).strip(),
        "units": match.group(4).strip(),
    }


def find_variable(dictionary: dict[int, dict[str, str]], target: str) -> dict[str, str] | None:
    if ":" in target:
        key, name = target.split(":", 1)
        for variable in dictionary.values():
            if variable["key"] == key.upper() and variable["name"] == name:
                return variable
        return None

    for variable in dictionary.values():
        if variable["name"] == target:
            return variable
    return None


def parse_applied_values(console_log: Path) -> list[float]:
    values: list[float] = []
    pattern = re.compile(r"Writing Cooling Return Air Setpoint Schedule = ([0-9.]+) C")
    for line in console_log.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = pattern.search(line)
        if match:
            values.append(float(match.group(1)))
    return values


def compare_runs(run_a: dict[str, object], run_b: dict[str, object]) -> dict[str, object]:
    variables_a: dict[str, dict[str, object]] = run_a["eso"]  # type: ignore[assignment]
    variables_b: dict[str, dict[str, object]] = run_b["eso"]  # type: ignore[assignment]
    variable_comparisons = {}
    physical_effect_detected = False

    for variable_name in VARIABLES:
        a = variables_a[variable_name]
        b = variables_b[variable_name]
        comparison = compare_variable(a, b)
        variable_comparisons[variable_name] = comparison
        if variable_name != "Cooling Return Air Setpoint Schedule:Schedule Value":
            physical_effect_detected = physical_effect_detected or bool(
                comparison.get("different", False)
            )

    setpoint_a_values = run_a["applied_console_values"]
    setpoint_b_values = run_b["applied_console_values"]
    setpoints_written = bool(setpoint_a_values) and bool(setpoint_b_values)
    different_setpoints_written = (
        setpoints_written
        and abs(setpoint_a_values[0] - setpoint_b_values[0]) > 1e-9
    )

    return {
        "run_a": strip_large_fields(run_a),
        "run_b": strip_large_fields(run_b),
        "setpoints_written": setpoints_written,
        "different_setpoints_written": different_setpoints_written,
        "variable_comparisons": variable_comparisons,
        "physical_effect_detected": physical_effect_detected,
        "pass": different_setpoints_written and physical_effect_detected,
    }


def compare_variable(a: dict[str, object], b: dict[str, object]) -> dict[str, object]:
    if not a.get("available") or not b.get("available"):
        return {"available": False, "different": False}

    a_values = a.get("first_values", [])
    b_values = b.get("first_values", [])
    mean_delta = numeric_delta(a.get("mean"), b.get("mean"))
    max_delta = numeric_delta(a.get("max"), b.get("max"))
    sum_delta = numeric_delta(a.get("sum"), b.get("sum"))
    first_delta = first_differences(a_values, b_values)
    max_abs_first_delta = max((abs(delta) for delta in first_delta), default=0.0)

    different = any(
        abs(value) > 1e-6
        for value in [mean_delta, max_delta, sum_delta, max_abs_first_delta]
        if value is not None
    )

    return {
        "available": True,
        "units": a.get("units"),
        "a_mean": a.get("mean"),
        "b_mean": b.get("mean"),
        "mean_delta_b_minus_a": mean_delta,
        "a_sum": a.get("sum"),
        "b_sum": b.get("sum"),
        "sum_delta_b_minus_a": sum_delta,
        "a_max": a.get("max"),
        "b_max": b.get("max"),
        "max_delta_b_minus_a": max_delta,
        "a_first_values": a_values,
        "b_first_values": b_values,
        "first_deltas_b_minus_a": first_delta,
        "different": different,
    }


def strip_large_fields(run: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in run.items()
        if key not in {"eso"}
    }


def build_report(result: dict[str, object]) -> str:
    lines = [
        "# Actuator Physical Validation Report",
        "",
        "## Configuration",
        "",
        "- Run A: heating 18.0 C, cooling 22.0 C",
        "- Run B: heating 18.0 C, cooling 30.0 C",
        "- Same IDF, weather file, run period, timestep, initial conditions, schedules, and Runtime API callbacks.",
        "",
        "## Commands Executed",
        "",
        "- `$env:PYTHONPATH='src'; python tests\\physical_ab_validation.py`",
        "",
        "## Applied Actuator Values",
        "",
        f"- Run A first console-applied cooling values: {result['run_a']['applied_console_values'][:6]}",
        f"- Run B first console-applied cooling values: {result['run_b']['applied_console_values'][:6]}",
        f"- Different setpoints written: {result['different_setpoints_written']}",
        "",
        "## Output Variables And Aggregate Differences",
        "",
        "| Variable | Units | A Mean | B Mean | B-A Mean | Different |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]

    comparisons: dict[str, dict[str, object]] = result["variable_comparisons"]  # type: ignore[assignment]
    for name, comparison in comparisons.items():
        if not comparison.get("available"):
            lines.append(f"| {name} | unavailable | | | | False |")
            continue
        lines.append(
            f"| {name} | {comparison.get('units')} | "
            f"{format_number(comparison.get('a_mean'))} | "
            f"{format_number(comparison.get('b_mean'))} | "
            f"{format_number(comparison.get('mean_delta_b_minus_a'))} | "
            f"{comparison.get('different')} |"
        )

    lines.extend(
        [
            "",
            "## Sample Rows",
            "",
            "Run A first CSV rows:",
            "",
            "```json",
            json.dumps(result["run_a"]["first_csv_rows"][:3], indent=2),
            "```",
            "",
            "Run B first CSV rows:",
            "",
            "```json",
            json.dumps(result["run_b"]["first_csv_rows"][:3], indent=2),
            "```",
            "",
            "## Investigation Notes",
            "",
            "- The IDF references `Cooling Return Air Setpoint Schedule` through `ThermostatSetpoint:DualSetpoint`; the schedule name itself is not obviously wrong.",
            "- The CSV confirms `Zone Thermostat Cooling Setpoint Temperature` changes from 22 C to 30 C after the first timestep.",
            "- The ESO confirms `COOLING RETURN AIR SETPOINT SCHEDULE, Schedule Value` changes by about 8 C between runs.",
            "- The EDD lists a more direct actuator: `MAIN ZONE, Zone Temperature Control, Cooling Setpoint, [C]`.",
            "- The air loop is controlled by `SetpointManager:Warmest` with a 10 C to 25 C supply outlet setpoint range, which may dominate the CRAC behavior.",
            "- The tested schedule actuator is therefore not proven to be the physically effective control point for this model.",
            "",
            "## Final Conclusion",
            "",
        ]
    )

    if result["pass"]:
        lines.append(
            "PASS: Different cooling setpoints were written and at least one physical EnergyPlus output changed."
        )
    else:
        lines.append(
            "FAIL: The A/B test did not prove a physical EnergyPlus response. Do not proceed to Ollama performance comparisons."
        )

    return "\n".join(lines) + "\n"


def parse_error_counts(err_text: str) -> tuple[int, int]:
    match = re.search(
        r"Completed Successfully--\s*(\d+)\s*Warning;\s*(\d+)\s*Severe Errors",
        err_text,
    )
    if match is None:
        return (0, 0)
    return int(match.group(1)), int(match.group(2))


def first_differences(a_values: object, b_values: object) -> list[float]:
    if not isinstance(a_values, list) or not isinstance(b_values, list):
        return []
    return [
        float(b) - float(a)
        for a, b in zip(a_values, b_values)
        if is_finite(a) and is_finite(b)
    ]


def numeric_delta(a: object, b: object) -> float | None:
    if not is_finite(a) or not is_finite(b):
        return None
    return float(b) - float(a)


def safe_mean(values: list[float]) -> float | None:
    finite_values = [value for value in values if math.isfinite(value)]
    if not finite_values:
        return None
    return sum(finite_values) / len(finite_values)


def safe_sum(values: list[float]) -> float | None:
    finite_values = [value for value in values if math.isfinite(value)]
    if not finite_values:
        return None
    return sum(finite_values)


def safe_min(values: list[float]) -> float | None:
    finite_values = [value for value in values if math.isfinite(value)]
    if not finite_values:
        return None
    return min(finite_values)


def safe_max(values: list[float]) -> float | None:
    finite_values = [value for value in values if math.isfinite(value)]
    if not finite_values:
        return None
    return max(finite_values)


def is_finite(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


def format_number(value: object) -> str:
    if not is_finite(value):
        return ""
    return f"{float(value):.6f}"


if __name__ == "__main__":
    raise SystemExit(main())
