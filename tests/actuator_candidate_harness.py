"""Reusable EnergyPlus actuator A/B validation harness.

This module is intentionally independent from controller decision logic. It
applies a fixed actuator command and records physical EnergyPlus outputs so an
actuator is never accepted based on handle resolution or readback alone.
"""

from __future__ import annotations

import csv
import json
import math
import os
import re
import shutil
import sys
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class CallbackTiming(str, Enum):
    """Runtime API calling points supported by the validation harness."""

    BEGIN_ZONE_BEFORE_INIT_HEAT_BALANCE = "begin_zone_before_init_heat_balance"
    BEGIN_SYSTEM_BEFORE_PREDICTOR = "begin_system_before_predictor"
    AFTER_PREDICTOR_BEFORE_HVAC_MANAGERS = (
        "after_predictor_before_hvac_managers"
    )
    AFTER_PREDICTOR_AFTER_HVAC_MANAGERS = "after_predictor_after_hvac_managers"
    INSIDE_SYSTEM_ITERATION_LOOP = "inside_system_iteration_loop"


@dataclass(frozen=True)
class ActuatorCandidate:
    """Exact EnergyPlus API actuator plus its aggressive A/B commands."""

    candidate_id: str
    component_type: str
    control_type: str
    actuator_key: str
    units: str
    related_idf_object: str
    expected_physical_effect: str
    override_risk: str
    low_value: float
    high_value: float
    callback_timing: CallbackTiming


@dataclass(frozen=True)
class OutputSpec:
    """Output variable sampled after each non-warmup zone timestep."""

    output_id: str
    name: str
    key: str
    units: str
    physical: bool = True


OUTPUTS = (
    OutputSpec(
        "zone_mean_air_temperature",
        "Zone Mean Air Temperature",
        "Main Zone",
        "C",
    ),
    OutputSpec(
        "zone_operative_temperature",
        "Zone Operative Temperature",
        "Main Zone",
        "C",
    ),
    OutputSpec(
        "zone_thermostat_cooling_setpoint",
        "Zone Thermostat Cooling Setpoint Temperature",
        "Main Zone",
        "C",
        physical=False,
    ),
    OutputSpec(
        "zone_air_sensible_cooling_rate",
        "Zone Air System Sensible Cooling Rate",
        "Main Zone",
        "W",
    ),
    OutputSpec(
        "zone_predicted_cooling_load",
        "Zone Predicted Sensible Load to Cooling Setpoint Heat Transfer Rate",
        "Main Zone",
        "W",
    ),
    OutputSpec(
        "cooling_coil_total_rate",
        "Cooling Coil Total Cooling Rate",
        "Main Cooling Coil 1",
        "W",
    ),
    OutputSpec(
        "cooling_coil_sensible_rate",
        "Cooling Coil Sensible Cooling Rate",
        "Main Cooling Coil 1",
        "W",
    ),
    OutputSpec(
        "cooling_coil_electricity_rate",
        "Cooling Coil Electricity Rate",
        "Main Cooling Coil 1",
        "W",
    ),
    OutputSpec(
        "facility_hvac_electricity_rate",
        "Facility Total HVAC Electricity Demand Rate",
        "Whole Building",
        "W",
    ),
    OutputSpec(
        "facility_electricity_rate",
        "Facility Total Electricity Demand Rate",
        "Whole Building",
        "W",
    ),
    OutputSpec(
        "zone_cooling_setpoint_not_met_time",
        "Zone Cooling Setpoint Not Met Time",
        "Main Zone",
        "hr",
    ),
    OutputSpec(
        "supply_outlet_temperature",
        "System Node Temperature",
        "Supply Outlet Node",
        "C",
    ),
    OutputSpec(
        "supply_outlet_setpoint_temperature",
        "System Node Setpoint Temperature",
        "Supply Outlet Node",
        "C",
        physical=False,
    ),
    OutputSpec(
        "cooling_coil_outlet_temperature",
        "System Node Temperature",
        "Main Cooling Coil 1 Outlet Node",
        "C",
    ),
    OutputSpec(
        "cooling_coil_outlet_setpoint_temperature",
        "System Node Setpoint Temperature",
        "Main Cooling Coil 1 Outlet Node",
        "C",
        physical=False,
    ),
)


def run_ab_test(
    *,
    energyplus_root: Path,
    idf_path: Path,
    epw_path: Path,
    output_root: Path,
    candidate: ActuatorCandidate,
) -> dict[str, Any]:
    """Run low/high cases and compare commanded and physical behavior."""

    low = run_case(
        energyplus_root=energyplus_root,
        idf_path=idf_path,
        epw_path=epw_path,
        output_dir=output_root / "low",
        candidate=candidate,
        command_value=candidate.low_value,
    )
    high = run_case(
        energyplus_root=energyplus_root,
        idf_path=idf_path,
        epw_path=epw_path,
        output_dir=output_root / "high",
        candidate=candidate,
        command_value=candidate.high_value,
    )
    comparison = compare_cases(candidate, low, high)
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "ab_result.json").write_text(
        json.dumps(comparison, indent=2),
        encoding="utf-8",
    )
    return comparison


def run_case(
    *,
    energyplus_root: Path,
    idf_path: Path,
    epw_path: Path,
    output_dir: Path,
    candidate: ActuatorCandidate,
    command_value: float,
) -> dict[str, Any]:
    """Run one fixed-command EnergyPlus case and capture timestep outputs."""

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    if str(energyplus_root) not in sys.path:
        sys.path.insert(0, str(energyplus_root))
    if os.name == "nt":
        os.add_dll_directory(str(energyplus_root))

    from pyenergyplus.api import EnergyPlusAPI  # type: ignore[import-not-found]

    api = EnergyPlusAPI()
    sim_state = api.state_manager.new_state()
    actuator_handle = -1
    actuator_resolution_attempted = False
    write_count = 0
    write_readbacks: list[float] = []
    variable_handles: dict[str, int] = {}
    variable_resolution_attempted = False
    samples: list[dict[str, float | str | None]] = []
    timing_rows: list[dict[str, float | str | None]] = []

    for output in OUTPUTS:
        api.exchange.request_variable(sim_state, output.name, output.key)

    def timestamp(state: Any) -> str:
        return (
            f"{api.exchange.year(state):04d}-"
            f"{api.exchange.month(state):02d}-"
            f"{api.exchange.day_of_month(state):02d} "
            f"{api.exchange.current_time(state):.4f}h"
        )

    def resolve_actuator(state: Any) -> bool:
        nonlocal actuator_handle, actuator_resolution_attempted
        if actuator_resolution_attempted:
            return actuator_handle != -1
        if not api.exchange.api_data_fully_ready(state):
            return False
        actuator_handle = api.exchange.get_actuator_handle(
            state,
            candidate.component_type,
            candidate.control_type,
            candidate.actuator_key,
        )
        actuator_resolution_attempted = True
        return actuator_handle != -1

    def resolve_variables(state: Any) -> bool:
        nonlocal variable_resolution_attempted
        if variable_resolution_attempted:
            return True
        if not api.exchange.api_data_fully_ready(state):
            return False
        for output in OUTPUTS:
            variable_handles[output.output_id] = api.exchange.get_variable_handle(
                state,
                output.name,
                output.key,
            )
        variable_resolution_attempted = True
        return True

    def write_callback(state: Any) -> None:
        nonlocal write_count
        if not resolve_actuator(state):
            return
        api.exchange.set_actuator_value(state, actuator_handle, command_value)
        readback = api.exchange.get_actuator_value(state, actuator_handle)
        write_count += 1
        if len(write_readbacks) < 20:
            write_readbacks.append(readback)
        if not api.exchange.warmup_flag(state):
            timing_rows.append(
                {
                    "timestamp": timestamp(state),
                    "callback": candidate.callback_timing.value,
                    "written_value": command_value,
                    "actuator_readback": readback,
                    "zone_temperature": read_output(
                        api,
                        state,
                        variable_handles,
                        "zone_mean_air_temperature",
                    ),
                    "thermostat_cooling_setpoint": read_output(
                        api,
                        state,
                        variable_handles,
                        "zone_thermostat_cooling_setpoint",
                    ),
                    "supply_outlet_temperature": read_output(
                        api,
                        state,
                        variable_handles,
                        "supply_outlet_temperature",
                    ),
                    "supply_outlet_setpoint": read_output(
                        api,
                        state,
                        variable_handles,
                        "supply_outlet_setpoint_temperature",
                    ),
                }
            )

    def sample_callback(state: Any) -> None:
        if not resolve_variables(state):
            return
        if api.exchange.warmup_flag(state):
            return
        row: dict[str, float | str | None] = {"timestamp": timestamp(state)}
        for output in OUTPUTS:
            row[output.output_id] = read_output(
                api,
                state,
                variable_handles,
                output.output_id,
            )
        samples.append(row)

    _register_write_callback(api, sim_state, candidate.callback_timing, write_callback)
    api.runtime.callback_end_zone_timestep_after_zone_reporting(
        sim_state,
        sample_callback,
    )
    api.runtime.set_console_output_status(sim_state, False)

    exit_code: int | None = None
    try:
        exit_code = api.runtime.run_energyplus(
            sim_state,
            [
                "-d",
                str(output_dir),
                "-w",
                str(epw_path),
                str(idf_path),
            ],
        )
    finally:
        api.state_manager.delete_state(sim_state)

    error_text = (output_dir / "eplusout.err").read_text(
        encoding="utf-8",
        errors="ignore",
    )
    warning_count, severe_count = parse_error_counts(error_text)
    _write_rows(output_dir / "physical_timeseries.csv", samples)
    _write_rows(output_dir / "timing_diagnostic.csv", timing_rows)

    result = {
        "candidate": _candidate_dict(candidate),
        "command_value": command_value,
        "exit_code": exit_code,
        "warning_count": warning_count,
        "severe_count": severe_count,
        "actuator_handle": actuator_handle,
        "actuator_resolution_attempted": actuator_resolution_attempted,
        "write_count": write_count,
        "first_write_readbacks": write_readbacks,
        "sample_count": len(samples),
        "variable_handles": variable_handles,
        "output_summaries": summarize_outputs(samples),
    }
    (output_dir / "case_result.json").write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )
    return result


def compare_cases(
    candidate: ActuatorCandidate,
    low: dict[str, Any],
    high: dict[str, Any],
) -> dict[str, Any]:
    """Apply explicit noise and direction criteria to one A/B pair."""

    comparisons: dict[str, dict[str, Any]] = {}
    sensible_effects: list[str] = []
    for output in OUTPUTS:
        item = compare_output(
            output,
            low["output_summaries"][output.output_id],
            high["output_summaries"][output.output_id],
        )
        comparisons[output.output_id] = item
        if output.physical and item["physically_sensible"]:
            sensible_effects.append(output.output_id)

    commands_written = (
        low["actuator_handle"] != -1
        and high["actuator_handle"] != -1
        and low["write_count"] > 0
        and high["write_count"] > 0
        and abs(low["command_value"] - high["command_value"]) > 1e-9
    )
    simulations_clean = (
        low["exit_code"] == 0
        and high["exit_code"] == 0
        and low["severe_count"] == 0
        and high["severe_count"] == 0
    )
    passed = commands_written and simulations_clean and bool(sensible_effects)
    return {
        "candidate": _candidate_dict(candidate),
        "low_case": low,
        "high_case": high,
        "commands_written": commands_written,
        "simulations_clean": simulations_clean,
        "sensible_physical_effects": sensible_effects,
        "output_comparisons": comparisons,
        "pass": passed,
    }


def compare_output(
    output: OutputSpec,
    low: dict[str, Any],
    high: dict[str, Any],
) -> dict[str, Any]:
    if not low["available"] or not high["available"]:
        return {
            "available": False,
            "units": output.units,
            "exceeds_noise": False,
            "physically_sensible": False,
        }

    mean_delta = high["mean"] - low["mean"]
    aggregate_delta = high["sum"] - low["sum"]
    max_timestep_delta = max_abs_paired_delta(low["values"], high["values"])
    scale = max(abs(low["mean"]), abs(high["mean"]), 1.0)
    relative_mean_delta = abs(mean_delta) / scale

    if output.units == "C":
        exceeds_noise = (
            abs(mean_delta) > 0.1 or max_timestep_delta > 0.1
        )
    elif output.units == "W":
        exceeds_noise = (
            relative_mean_delta > 0.01 or max_timestep_delta > max(100.0, scale * 0.01)
        )
    elif output.units == "hr":
        exceeds_noise = abs(aggregate_delta) > 0.01
    else:
        exceeds_noise = abs(mean_delta) > 1e-6

    physically_sensible = exceeds_noise and sensible_direction(
        output.output_id,
        low["mean"],
        high["mean"],
    )
    return {
        "available": True,
        "units": output.units,
        "low_mean": low["mean"],
        "high_mean": high["mean"],
        "mean_delta_high_minus_low": mean_delta,
        "low_sum": low["sum"],
        "high_sum": high["sum"],
        "aggregate_delta_high_minus_low": aggregate_delta,
        "max_timestep_absolute_difference": max_timestep_delta,
        "relative_mean_difference": relative_mean_delta,
        "exceeds_noise": exceeds_noise,
        "physically_sensible": physically_sensible,
    }


def sensible_direction(output_id: str, low_mean: float, high_mean: float) -> bool:
    """Expected direction when the low command is a lower temperature target."""

    if output_id in {
        "zone_mean_air_temperature",
        "zone_operative_temperature",
        "supply_outlet_temperature",
        "cooling_coil_outlet_temperature",
    }:
        return low_mean < high_mean
    if output_id == "zone_predicted_cooling_load":
        return abs(low_mean) > abs(high_mean)
    if output_id in {
        "zone_air_sensible_cooling_rate",
        "cooling_coil_total_rate",
        "cooling_coil_sensible_rate",
        "cooling_coil_electricity_rate",
        "facility_hvac_electricity_rate",
        "facility_electricity_rate",
    }:
        return low_mean > high_mean
    if output_id == "zone_cooling_setpoint_not_met_time":
        return low_mean > high_mean
    return False


def summarize_outputs(
    samples: list[dict[str, float | str | None]],
) -> dict[str, dict[str, Any]]:
    summaries: dict[str, dict[str, Any]] = {}
    for output in OUTPUTS:
        values = [
            float(row[output.output_id])
            for row in samples
            if isinstance(row.get(output.output_id), (int, float))
            and math.isfinite(float(row[output.output_id]))
        ]
        summaries[output.output_id] = {
            "available": bool(values),
            "units": output.units,
            "count": len(values),
            "mean": sum(values) / len(values) if values else None,
            "sum": sum(values) if values else None,
            "minimum": min(values) if values else None,
            "maximum": max(values) if values else None,
            "values": values,
        }
    return summaries


def read_output(
    api: Any,
    state: Any,
    handles: dict[str, int],
    output_id: str,
) -> float | None:
    handle = handles.get(output_id, -1)
    if handle == -1:
        return None
    return api.exchange.get_variable_value(state, handle)


def max_abs_paired_delta(low: list[float], high: list[float]) -> float:
    return max(
        (abs(high_value - low_value) for low_value, high_value in zip(low, high)),
        default=0.0,
    )


def parse_error_counts(error_text: str) -> tuple[int, int]:
    match = re.search(
        r"Completed Successfully--\s*(\d+)\s*Warning;\s*(\d+)\s*Severe Errors",
        error_text,
    )
    if match is None:
        return 0, 0
    return int(match.group(1)), int(match.group(2))


def _register_write_callback(
    api: Any,
    sim_state: Any,
    timing: CallbackTiming,
    callback: Any,
) -> None:
    registrations = {
        CallbackTiming.BEGIN_ZONE_BEFORE_INIT_HEAT_BALANCE:
            api.runtime.callback_begin_zone_timestep_before_init_heat_balance,
        CallbackTiming.BEGIN_SYSTEM_BEFORE_PREDICTOR:
            api.runtime.callback_begin_system_timestep_before_predictor,
        CallbackTiming.AFTER_PREDICTOR_BEFORE_HVAC_MANAGERS:
            api.runtime.callback_after_predictor_before_hvac_managers,
        CallbackTiming.AFTER_PREDICTOR_AFTER_HVAC_MANAGERS:
            api.runtime.callback_after_predictor_after_hvac_managers,
        CallbackTiming.INSIDE_SYSTEM_ITERATION_LOOP:
            api.runtime.callback_inside_system_iteration_loop,
    }
    registrations[timing](sim_state, callback)


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _candidate_dict(candidate: ActuatorCandidate) -> dict[str, Any]:
    data = asdict(candidate)
    data["callback_timing"] = candidate.callback_timing.value
    return data
