"""Safe, read-only loading for controller CSV and sibling run reports."""

from __future__ import annotations

import csv
import io
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]

NUMERIC_COLUMNS = (
    "timestep",
    "indoor_temp_c",
    "outdoor_temp_c",
    "facility_power_kw",
    "hvac_power_kw",
    "cooling_coil_power_kw",
    "requested_supply_air_setpoint_c",
    "validated_supply_air_setpoint_c",
    "applied_supply_air_setpoint_c",
    "measured_node_setpoint_c",
    "measured_supply_air_temperature_c",
    "zone_thermostat_cooling_setpoint_c",
    "heating_thermostat_setpoint_c",
    "target_zone_temperature_c",
    "candidate_count",
    "llm_confidence",
    "supervisor_response_time_s",
    "llm_retry_count",
)


@dataclass(frozen=True)
class RunMetadata:
    """Read-only status derived from files next to the telemetry CSV."""

    metrics: dict[str, str] = field(default_factory=dict)
    warning_count: int | None = None
    severe_error_count: int | None = None
    energyplus_exit_code: int | None = None
    expected_timesteps: int | None = None
    completed: bool = False
    modified_age_seconds: float | None = None


def discover_default_telemetry() -> Path:
    """Return configured telemetry or the newest sensible project CSV."""

    configured = os.getenv("ENERGYPLUS_TELEMETRY_CSV", "").strip()
    if configured:
        return Path(configured).expanduser()

    candidates = list(
        (WORKSPACE_ROOT / "test_reports").glob(
            "nvidia_nim_one_day_output_*/control_log.csv"
        )
    )
    fallback = (
        WORKSPACE_ROOT
        / "sampleSimulation"
        / "api_demo_output"
        / "control_log.csv"
    )
    if fallback.exists():
        candidates.append(fallback)
    if not candidates:
        return fallback
    return max(candidates, key=lambda item: item.stat().st_mtime)


def load_telemetry(path: str | Path, retries: int = 2) -> pd.DataFrame:
    """Read a consistent byte snapshot and tolerate a partial trailing row."""

    source = Path(path).expanduser()
    if not source.is_file():
        return pd.DataFrame()

    attempts = max(1, retries + 1)
    for attempt in range(attempts):
        try:
            before = source.stat()
            payload = source.read_bytes()
            after = source.stat()
            text = _remove_incomplete_tail(
                payload.decode("utf-8-sig", errors="replace")
            )
            if not text.strip():
                return pd.DataFrame()
            frame = pd.read_csv(
                io.StringIO(text),
                dtype=str,
                on_bad_lines="skip",
                engine="python",
            )
            frame = _normalize(frame)
            if (
                before.st_size == after.st_size
                and before.st_mtime_ns == after.st_mtime_ns
            ):
                return frame
        except (OSError, pd.errors.ParserError, UnicodeError):
            if attempt == attempts - 1:
                return pd.DataFrame()
        time.sleep(0.05)
    return frame if "frame" in locals() else pd.DataFrame()


def load_run_metadata(telemetry_path: str | Path) -> RunMetadata:
    """Read the controller summary and EnergyPlus error file, if present."""

    telemetry = Path(telemetry_path).expanduser()
    directory = telemetry.parent
    metrics = _read_key_value_file(directory / "control_summary.txt")
    warning_count, severe_count, completed = _read_error_counts(
        directory / "eplusout.err"
    )
    exit_code = _optional_int(metrics.get("EnergyPlus Exit Code"))
    expected = _optional_int(os.getenv("DASHBOARD_EXPECTED_TIMESTEPS"))
    if expected is None:
        expected = _optional_int(metrics.get("Total Control Timesteps"))
    age = None
    try:
        age = max(0.0, time.time() - telemetry.stat().st_mtime)
    except OSError:
        pass
    return RunMetadata(
        metrics=metrics,
        warning_count=warning_count,
        severe_error_count=severe_count,
        energyplus_exit_code=exit_code,
        expected_timesteps=expected,
        completed=completed or exit_code is not None,
        modified_age_seconds=age,
    )


def simulation_status(
    frame: pd.DataFrame,
    metadata: RunMetadata,
    stale_after_seconds: float = 30.0,
) -> str:
    """Classify status without sending commands to the simulation."""

    if frame.empty:
        return "Waiting for telemetry"
    if (
        (metadata.energyplus_exit_code is not None
         and metadata.energyplus_exit_code != 0)
        or (metadata.severe_error_count or 0) > 0
    ):
        return "Failed"
    if metadata.completed and (
        metadata.expected_timesteps is None
        or len(frame) >= metadata.expected_timesteps
    ):
        return "Complete"
    if (
        metadata.modified_age_seconds is not None
        and metadata.modified_age_seconds > stale_after_seconds
    ):
        return "Stale"
    return "Running"


def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
    frame.columns = [str(column).strip() for column in frame.columns]
    frame = frame.dropna(how="all").copy()
    for column in NUMERIC_COLUMNS:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if "simulation_time" in frame.columns:
        frame["simulated_hour"] = pd.to_numeric(
            frame["simulation_time"]
            .astype("string")
            .str.extract(r"(\d+(?:\.\d+)?)\s*h", expand=False),
            errors="coerce",
        )
    if "timestep" in frame.columns:
        frame = frame.sort_values(
            by="timestep",
            kind="stable",
            na_position="last",
        )
    return frame.reset_index(drop=True)


def _remove_incomplete_tail(text: str) -> str:
    if not text or text.endswith(("\n", "\r")):
        return text
    lines = text.splitlines(keepends=True)
    if len(lines) < 2:
        return text
    try:
        header = next(csv.reader([lines[0]]))
        tail = next(csv.reader([lines[-1]]))
    except (csv.Error, StopIteration):
        return "".join(lines[:-1])
    return text if len(tail) == len(header) else "".join(lines[:-1])


def _read_key_value_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    result: dict[str, str] = {}
    try:
        for line in path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines():
            if ": " in line:
                key, value = line.split(": ", 1)
                result[key.strip()] = value.strip()
    except OSError:
        return {}
    return result


def _read_error_counts(path: Path) -> tuple[int | None, int | None, bool]:
    if not path.is_file():
        return None, None, False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, None, False
    matches = re.findall(
        r"EnergyPlus Completed.*?(\d+)\s+Warning.*?(\d+)\s+Severe",
        text,
        flags=re.IGNORECASE,
    )
    if matches:
        warnings, severe = matches[-1]
        return int(warnings), int(severe), True
    warnings = len(re.findall(r"\*\*\s*Warning\s*\*\*", text))
    severe = len(re.findall(r"\*\*\s*Severe\s*\*\*", text))
    return warnings, severe, False


def _optional_int(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None
