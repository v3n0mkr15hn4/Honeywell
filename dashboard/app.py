"""Read-only Streamlit dashboard for EnergyPlus supervisory telemetry."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard.demo_data import build_demo_telemetry
from dashboard.metrics_helpers import (
    boolean_series,
    cumulative_metrics,
    latest_supervisory_row,
    parse_candidate_summaries,
    safe_json_list,
)
from dashboard.telemetry_loader import (
    RunMetadata,
    discover_default_telemetry,
    load_run_metadata,
    load_telemetry,
    simulation_status,
)


REFRESH_OPTIONS = {
    "1 second": 1.0,
    "2 seconds": 2.0,
    "5 seconds": 5.0,
    "Manual": None,
}
WINDOW_OPTIONS = {
    "Full run": None,
    "Last 6 hours": 6.0,
    "Last 12 hours": 12.0,
    "Last 24 hours": 24.0,
}


st.set_page_config(
    page_title="EnergyPlus Supervisory Control",
    page_icon="E",
    layout="wide",
)
st.markdown(
    """
    <style>
      .block-container {padding-top: 1.2rem; padding-bottom: 2rem;}
      h1 {font-size: 1.85rem !important; letter-spacing: 0 !important;}
      h2 {font-size: 1.25rem !important; letter-spacing: 0 !important;}
      div[data-testid="stMetric"] {
        border: 1px solid color-mix(
          in srgb,
          var(--text-color) 22%,
          transparent
        );
        border-top: 3px solid #0f766e;
        border-radius: 6px;
        padding: 0.7rem 0.8rem;
        background: var(--secondary-background-color);
        color: var(--text-color);
      }
      div[data-testid="stMetric"] * {
        color: var(--text-color) !important;
      }
      .flow {
        display: flex;
        align-items: stretch;
        gap: 0.35rem;
        overflow-x: auto;
        padding: 0.25rem 0 0.5rem 0;
      }
      .flow-step {
        min-width: 132px;
        border: 1px solid color-mix(
          in srgb,
          var(--text-color) 22%,
          transparent
        );
        border-top: 3px solid #0f766e;
        border-radius: 6px;
        padding: 0.65rem;
        background: var(--secondary-background-color);
        color: var(--text-color);
        font-size: 0.82rem;
        font-weight: 600;
      }
      .flow-step.llm {border-top-color: #b45309;}
      .flow-step.safety {border-top-color: #15803d;}
      .flow-arrow {
        align-self: center;
        color: var(--text-color);
        opacity: 0.65;
        font-size: 1.1rem;
      }
      .readonly-note {
        border-left: 4px solid #0f766e;
        background: #ecfdf5;
        padding: 0.65rem 0.8rem;
        color: #134e4a;
        margin-bottom: 0.8rem;
      }
    </style>
    """,
    unsafe_allow_html=True,
)


def main() -> None:
    demo_mode = _env_bool("DASHBOARD_DEMO_MODE", False)
    default_path = str(discover_default_telemetry())

    with st.sidebar:
        st.header("View")
        telemetry_path = st.text_input(
            "Telemetry CSV",
            value=default_path,
            disabled=demo_mode,
        )
        refresh_label = st.selectbox(
            "Refresh interval",
            options=list(REFRESH_OPTIONS),
            index=1,
        )
        recent_rows = st.slider(
            "Recent event rows",
            min_value=20,
            max_value=50,
            value=30,
            step=5,
        )
        window_label = st.selectbox(
            "Temperature chart window",
            options=list(WINDOW_OPTIONS),
            index=0,
        )
        show_raw = st.toggle("Show raw telemetry", value=False)
        show_reason = st.toggle("Show model reason", value=True)
        if REFRESH_OPTIONS[refresh_label] is None:
            st.button("Refresh now", icon=":material/refresh:")

    run_every = REFRESH_OPTIONS[refresh_label]

    @st.fragment(run_every=run_every)
    def render() -> None:
        if demo_mode:
            frame = build_demo_telemetry()
            metadata = RunMetadata(
                warning_count=0,
                severe_error_count=0,
                energyplus_exit_code=0,
                expected_timesteps=144,
                completed=True,
                modified_age_seconds=0.0,
            )
        else:
            frame = load_telemetry(telemetry_path)
            metadata = load_run_metadata(telemetry_path)

        _render_header(demo_mode)
        if frame.empty:
            _render_waiting(telemetry_path, metadata)
            _render_control_flow()
            return

        metrics = cumulative_metrics(
            frame,
            warning_count=metadata.warning_count,
            severe_error_count=metadata.severe_error_count,
        )
        reported_changes = _optional_int(
            metadata.metrics.get("Total Supply-Air Setpoint Changes")
        )
        if reported_changes is not None:
            metrics["physical_actuator_changes"] = reported_changes
        status = "Demo data" if demo_mode else simulation_status(
            frame,
            metadata,
        )
        _render_status(frame, metadata, metrics, status)
        _render_current_state(frame)
        _render_charts(frame, WINDOW_OPTIONS[window_label])
        _render_supervisory_decision(frame, show_reason)
        _render_control_flow()
        _render_safety(frame, metadata, metrics)
        _render_event_log(frame, recent_rows)
        _render_summary(metrics)
        if show_raw:
            st.subheader("Raw Telemetry")
            st.dataframe(frame, width="stretch", hide_index=True)
        st.markdown(
            """
            <div class="readonly-note">
            NVIDIA NIM ranks prevalidated supervisory policies. Deterministic
            validation, control logic, and safety limits calculate and apply
            every physical EnergyPlus actuator command.
            </div>
            """,
            unsafe_allow_html=True,
        )

    render()


def _render_header(demo_mode: bool) -> None:
    title, badge = st.columns([5, 1])
    with title:
        st.title("EnergyPlus Supervisory Control")
        st.caption(
            "Read-only telemetry view · System Node Setpoint · "
            "MAIN COOLING COIL 1 OUTLET NODE"
        )
    with badge:
        if demo_mode:
            st.warning("DEMO DATA")
        else:
            st.success("READ ONLY")


def _render_waiting(
    telemetry_path: str,
    metadata: RunMetadata,
) -> None:
    st.info(
        "Waiting for telemetry. The dashboard will retry on the next refresh."
    )
    st.code(telemetry_path, language=None)
    if (metadata.severe_error_count or 0) > 0:
        st.error(
            f"EnergyPlus severe errors detected: "
            f"{metadata.severe_error_count}"
        )


def _render_status(
    frame: pd.DataFrame,
    metadata: RunMetadata,
    metrics: dict[str, Any],
    status: str,
) -> None:
    latest = frame.iloc[-1]
    supervisory = latest_supervisory_row(frame)
    expected = metadata.expected_timesteps
    final_policy = _value(supervisory, "final_selected_policy_id")
    source = _value(supervisory, "selected_policy_source")
    rows = [
        ("Simulation", status),
        ("Current timestep", _format_number(latest.get("timestep"), 0)),
        ("Expected timesteps", expected if expected is not None else "N/A"),
        ("Simulated hour", _format_number(latest.get("simulated_hour"), 2)),
        ("Active policy", _value(latest, "policy_strategy")),
        ("Final policy ID", final_policy),
        ("Policy source", source),
        ("NVIDIA NIM calls", metrics["nvidia_calls"]),
        ("Fallbacks", metrics["deterministic_fallbacks"]),
        (
            "Severe errors",
            metadata.severe_error_count
            if metadata.severe_error_count is not None
            else "N/A",
        ),
    ]
    for offset in range(0, len(rows), 5):
        columns = st.columns(5)
        for column, (label, value) in zip(columns, rows[offset:offset + 5]):
            column.metric(label, value)


def _render_current_state(frame: pd.DataFrame) -> None:
    st.subheader("Current Building State")
    latest = frame.iloc[-1]
    applied = _non_null_values(frame, "applied_supply_air_setpoint_c")
    previous_applied = applied.iloc[-2] if len(applied) > 1 else None
    definitions = [
        ("Zone temperature", "indoor_temp_c", " C"),
        ("Operational target", "target_zone_temperature_c", " C"),
        ("Zone trend", "zone_trend", ""),
        ("Thermal state", "thermal_state", ""),
        ("Outdoor temperature", "outdoor_temp_c", " C"),
        ("Outdoor trend", "outdoor_trend", ""),
        ("HVAC power", "hvac_power_kw", " kW"),
        ("Facility power", "facility_power_kw", " kW"),
        ("Power trend", "power_trend", ""),
        (
            "Applied supply setpoint",
            "applied_supply_air_setpoint_c",
            " C",
        ),
        (
            "Measured supply temperature",
            "measured_supply_air_temperature_c",
            " C",
        ),
    ]
    values: list[tuple[str, object, str]] = []
    unavailable: list[str] = []
    for label, field, unit in definitions:
        value = latest.get(field)
        if field not in frame.columns or not _has_value(value):
            unavailable.append(label)
        else:
            values.append((label, value, unit))
    if previous_applied is not None:
        values.append(("Previous applied setpoint", previous_applied, " C"))
    for offset in range(0, len(values), 4):
        columns = st.columns(4)
        for column, (label, value, unit) in zip(
            columns,
            values[offset:offset + 4],
        ):
            column.metric(label, _display(value, unit))
    if unavailable:
        st.caption(
            "Not available in telemetry: " + ", ".join(unavailable) + "."
        )


def _render_charts(
    frame: pd.DataFrame,
    window_hours: float | None,
) -> None:
    chart_frame = _window(frame, window_hours)
    st.subheader("Operating Trends")
    temperature, setpoint = st.columns(2)
    with temperature:
        st.markdown("**Zone Temperature and Operational Target**")
        _line_chart(
            chart_frame,
            {
                "indoor_temp_c": "Zone temperature",
                "target_zone_temperature_c": "Operational target",
            },
            "Temperature (C)",
        )
        st.caption(
            "The target is an operational thermal target, not a PMV comfort "
            "measure."
        )
    with setpoint:
        st.markdown("**Supply-Air Control**")
        plotted = chart_frame.copy()
        plotted["Allowed minimum"] = 22.0
        plotted["Allowed maximum"] = 25.0
        _line_chart(
            plotted,
            {
                "requested_supply_air_setpoint_c": "Requested",
                "validated_supply_air_setpoint_c": "Validated",
                "applied_supply_air_setpoint_c": "Applied",
                "measured_supply_air_temperature_c": "Measured supply air",
                "Allowed minimum": "Allowed minimum",
                "Allowed maximum": "Allowed maximum",
            },
            "Temperature (C)",
        )
    st.markdown("**Electrical Power**")
    _line_chart(
        chart_frame,
        {
            "hvac_power_kw": "HVAC power",
            "facility_power_kw": "Facility power",
        },
        "Power (kW)",
    )


def _render_supervisory_decision(
    frame: pd.DataFrame,
    show_reason: bool,
) -> None:
    st.subheader("Latest NVIDIA NIM Supervisory Decision")
    row = latest_supervisory_row(frame)
    if row is None:
        st.info("No supervisory opportunity is present in telemetry yet.")
        return

    candidates = safe_json_list(row.get("candidate_ids"))
    ranking = safe_json_list(row.get("llm_raw_ranking"))
    deterministic = _value(row, "deterministic_recommendation_id")
    llm_selected = _value(row, "llm_selected_policy_id")
    final_selected = _value(row, "final_selected_policy_id")
    called = _truth(row.get("llm_ranker_called"))
    fallback = _truth(row.get("deterministic_fallback_used")) or _truth(
        row.get("supervisor_fallback_used")
    )

    first = st.columns(4)
    first[0].metric("NVIDIA called", "Yes" if called else "No")
    first[1].metric("Candidate count", len(candidates))
    first[2].metric("Confidence", _display(row.get("llm_confidence"), ""))
    first[3].metric(
        "Response latency",
        _display(row.get("supervisor_response_time_s"), " s"),
    )
    second = st.columns(4)
    second[0].metric("Deterministic recommendation", deterministic)
    second[1].metric("Raw LLM selection", llm_selected)
    second[2].metric("Final validated selection", final_selected)
    second[3].metric("Fallback", "Yes" if fallback else "No")

    detail_left, detail_right = st.columns(2)
    with detail_left:
        st.markdown("**Ranking and validation**")
        st.write("Candidates:", ", ".join(map(str, candidates)) or "N/A")
        st.write("Raw ranking:", " → ".join(map(str, ranking)) or "N/A")
        st.write(
            "Validation:",
            _value(row, "ranking_validation_status"),
        )
        st.write("Policy source:", _value(row, "selected_policy_source"))
    with detail_right:
        st.markdown("**Fallback status**")
        st.write(
            "Failure category:",
            _value(row, "llm_failure_category"),
        )
        fallback_reason = (
            _value(row, "supervisor_failure_reason")
            if fallback
            else "None"
        )
        st.write("Fallback reason:", fallback_reason)
        st.write(
            "Policy validation:",
            _value(row, "policy_validation_status"),
        )
    if show_reason:
        st.markdown("**Model-generated explanation — advisory only**")
        st.info(_value(row, "llm_reason"))

    _render_candidate_table(row, deterministic, llm_selected, final_selected)


def _render_candidate_table(
    row: pd.Series,
    deterministic: str,
    llm_selected: str,
    final_selected: str,
) -> None:
    st.markdown("**Candidate Policies**")
    candidates = parse_candidate_summaries(
        row.get("candidate_policy_summaries")
    )
    if not candidates:
        raw = row.get("candidate_policy_summaries", "")
        st.caption("Candidate summaries are not available as valid JSON.")
        if raw and not pd.isna(raw):
            st.code(str(raw), language=None)
        return

    records: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = str(candidate.get("candidate_id", ""))
        roles: list[str] = []
        if candidate_id == deterministic:
            roles.append("Deterministic")
        if candidate_id == llm_selected:
            roles.append("LLM")
        if candidate_id == final_selected:
            roles.append("Final")
        records.append(
            {
                "Candidate": candidate_id,
                "Strategy": candidate.get("mode", candidate.get("strategy")),
                "Thermal": candidate.get("thermal_priority"),
                "Energy": candidate.get("energy_priority"),
                "Aggressiveness": candidate.get(
                    "aggressiveness",
                    candidate.get("controller_aggressiveness"),
                ),
                "Target C": candidate.get("target_zone_temperature_c"),
                "Hold intervals": candidate.get(
                    "minimum_action_hold_intervals"
                ),
                "Duration h": candidate.get("policy_duration_hours"),
                "Score": candidate.get("deterministic_score"),
                "Selection role": " · ".join(roles),
            }
        )
    table = pd.DataFrame(records).dropna(axis=1, how="all")
    styled = table.style.apply(_candidate_row_style, axis=1)
    st.dataframe(styled, width="stretch", hide_index=True)


def _render_control_flow() -> None:
    st.subheader("Control Authority")
    labels = [
        ("EnergyPlus sensors", ""),
        ("Processed state", ""),
        ("Safe candidates", ""),
        ("NVIDIA ranking", "llm"),
        ("Strict validation", "safety"),
        ("Rule controller", ""),
        ("Safety validator", "safety"),
        ("EnergyPlus actuator", "safety"),
    ]
    pieces: list[str] = ['<div class="flow">']
    for index, (label, kind) in enumerate(labels):
        if index:
            pieces.append('<div class="flow-arrow">→</div>')
        pieces.append(f'<div class="flow-step {kind}">{label}</div>')
    pieces.append("</div>")
    st.markdown("".join(pieces), unsafe_allow_html=True)
    st.caption(
        "NVIDIA ranks policy IDs only. PolicyAwareRuleController calculates "
        "the physical setpoint; SafetyValidator enforces 22–25 C and a "
        "maximum 1 C change before ActuatorWriter reaches EnergyPlus."
    )


def _render_safety(
    frame: pd.DataFrame,
    metadata: RunMetadata,
    metrics: dict[str, Any],
) -> None:
    st.subheader("Safety and Validation")
    policy_corrections = int(
        boolean_series(frame, "policy_safety_corrected").sum()
    )
    timeout_fallbacks = int(boolean_series(frame, "timeout_fallback").sum())
    direct_rejections = _count_text(
        frame,
        "ranking_validation_status",
        "actuator",
    )
    items = [
        ("Physical range", "22–25 C"),
        ("Maximum change", "1 C"),
        ("Safety corrections", metrics["physical_safety_corrections"]),
        ("Policy corrections", policy_corrections),
        ("Invalid rankings", metrics["invalid_rankings"]),
        ("Timeout fallbacks", timeout_fallbacks),
        ("Deterministic fallbacks", metrics["deterministic_fallbacks"]),
        (
            "Actuator-field rejections",
            direct_rejections if direct_rejections else "N/A",
        ),
        (
            "Warnings",
            metadata.warning_count
            if metadata.warning_count is not None
            else "N/A",
        ),
        (
            "Severe errors",
            metadata.severe_error_count
            if metadata.severe_error_count is not None
            else "N/A",
        ),
    ]
    for offset in range(0, len(items), 5):
        columns = st.columns(5)
        for column, (label, value) in zip(
            columns,
            items[offset:offset + 5],
        ):
            column.metric(label, value)
    corrections = metrics["physical_safety_corrections"]
    if (metadata.severe_error_count or 0) > 0:
        st.error("Error: EnergyPlus reported severe errors.")
    elif corrections:
        st.warning(
            f"Corrected: SafetyValidator modified {corrections} physical "
            "requests. Corrections are safety interventions, not model success."
        )
    elif metrics["deterministic_fallbacks"]:
        st.warning("Fallback: deterministic candidate selection was used.")
    else:
        st.success("Safe: no severe errors or physical safety corrections.")


def _render_event_log(frame: pd.DataFrame, recent_rows: int) -> None:
    st.subheader("Recent Events")
    event_filter = st.segmented_control(
        "Event filter",
        options=[
            "All",
            "LLM calls",
            "Fallbacks",
            "Safety corrections",
            "Policy changes",
        ],
        default="All",
    )
    events = _event_frame(frame)
    if event_filter == "LLM calls":
        events = events.loc[events["LLM call"]]
    elif event_filter == "Fallbacks":
        events = events.loc[events["Fallback"]]
    elif event_filter == "Safety corrections":
        events = events.loc[events["Safety correction"]]
    elif event_filter == "Policy changes":
        events = events.loc[events["Policy change"]]
    st.dataframe(
        events.tail(recent_rows).iloc[::-1],
        width="stretch",
        hide_index=True,
    )


def _render_summary(metrics: dict[str, Any]) -> None:
    st.subheader("Run Summary")
    items = [
        ("Total timesteps", metrics["total_timesteps"]),
        ("NVIDIA calls", metrics["nvidia_calls"]),
        ("Successful NIM calls", metrics["successful_nvidia_calls"]),
        ("Strict rankings", metrics["strict_ranking_successes"]),
        ("Invalid rankings", metrics["invalid_rankings"]),
        ("Deterministic fallbacks", metrics["deterministic_fallbacks"]),
        (
            "Average NIM latency",
            _display(metrics["average_nim_latency_s"], " s"),
        ),
        (
            "Maximum NIM latency",
            _display(metrics["maximum_nim_latency_s"], " s"),
        ),
        ("Policy changes", metrics["policy_changes"]),
        ("Actuator changes", metrics["physical_actuator_changes"]),
        ("Safety corrections", metrics["physical_safety_corrections"]),
        (
            "Minimum zone temp",
            _display(metrics["minimum_zone_temperature_c"], " C"),
        ),
        (
            "Maximum zone temp",
            _display(metrics["maximum_zone_temperature_c"], " C"),
        ),
        (
            "Mean zone temp",
            _display(metrics["mean_zone_temperature_c"], " C"),
        ),
        (
            "Mean HVAC power",
            _display(metrics["mean_hvac_power_kw"], " kW"),
        ),
        (
            "Mean facility power",
            _display(metrics["mean_facility_power_kw"], " kW"),
        ),
        (
            "Operational target violation",
            _percentage(metrics["operational_target_violation_rate"]),
        ),
        (
            "Warnings",
            metrics["warning_count"]
            if metrics["warning_count"] is not None
            else "N/A",
        ),
        (
            "Severe errors",
            metrics["severe_error_count"]
            if metrics["severe_error_count"] is not None
            else "N/A",
        ),
    ]
    for offset in range(0, len(items), 5):
        columns = st.columns(5)
        for column, (label, value) in zip(
            columns,
            items[offset:offset + 5],
        ):
            column.metric(label, value)


def _line_chart(
    frame: pd.DataFrame,
    columns: dict[str, str],
    y_label: str,
) -> None:
    available = [
        column
        for column in columns
        if column in frame.columns and frame[column].notna().any()
    ]
    if "simulated_hour" not in frame.columns or not available:
        st.caption("Not available in telemetry.")
        return
    data = frame[["simulated_hour", *available]].copy()
    data = data.rename(columns=columns).set_index("simulated_hour")
    st.line_chart(
        data,
        x_label="Simulated hour",
        y_label=y_label,
        height=280,
    )


def _window(frame: pd.DataFrame, hours: float | None) -> pd.DataFrame:
    if (
        hours is None
        or "simulated_hour" not in frame.columns
        or frame["simulated_hour"].dropna().empty
    ):
        return frame
    maximum = float(frame["simulated_hour"].max())
    return frame.loc[frame["simulated_hour"] >= maximum - hours]


def _event_frame(frame: pd.DataFrame) -> pd.DataFrame:
    result = pd.DataFrame(index=frame.index)
    result["Simulated time"] = frame.get("simulation_time", "")
    result["LLM call"] = boolean_series(frame, "llm_ranker_called")
    result["Fallback"] = boolean_series(
        frame,
        "deterministic_fallback_used",
    )
    result["Safety correction"] = boolean_series(frame, "safety_corrected")
    result["Policy change"] = boolean_series(
        frame,
        "supervisor_policy_changed",
    )
    result["Event"] = "Control"
    result.loc[result["Safety correction"], "Event"] = "Safety correction"
    result.loc[result["Fallback"], "Event"] = "Fallback"
    result.loc[result["Policy change"], "Event"] = "Policy change"
    result.loc[result["LLM call"], "Event"] = "NVIDIA ranking"
    mappings = {
        "candidate_count": "Candidates",
        "deterministic_recommendation_id": "Deterministic",
        "llm_selected_policy_id": "LLM selected",
        "final_selected_policy_id": "Final policy",
        "selected_policy_source": "Policy source",
        "llm_confidence": "Confidence",
        "supervisor_response_time_s": "Latency s",
        "applied_supply_air_setpoint_c": "Applied setpoint C",
    }
    for source, target in mappings.items():
        result[target] = (
            frame[source].astype("string").fillna("")
            if source in frame.columns
            else ""
        )
    return result[
        [
            "Simulated time",
            "Event",
            "Candidates",
            "Deterministic",
            "LLM selected",
            "Final policy",
            "Policy source",
            "Confidence",
            "Latency s",
            "Fallback",
            "Safety correction",
            "Policy change",
            "Applied setpoint C",
            "LLM call",
        ]
    ]


def _count_text(frame: pd.DataFrame, column: str, text: str) -> int:
    if column not in frame.columns:
        return 0
    return int(
        frame[column]
        .astype("string")
        .str.contains(text, case=False, na=False)
        .sum()
    )


def _candidate_row_style(row: pd.Series) -> list[str]:
    role = str(row.get("Selection role", ""))
    if "Final" in role:
        color = "background-color: #dcfce7; color: #14532d"
    elif "LLM" in role:
        color = "background-color: #fef3c7; color: #78350f"
    elif "Deterministic" in role:
        color = "background-color: #e0f2fe; color: #0c4a6e"
    else:
        color = ""
    return [color] * len(row)


def _non_null_values(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").dropna()


def _value(row: pd.Series | None, key: str) -> str:
    if row is None:
        return "N/A"
    value = row.get(key)
    if value is None or pd.isna(value) or str(value).strip() == "":
        return "N/A"
    return str(value)


def _has_value(value: object) -> bool:
    return not (
        value is None
        or pd.isna(value)
        or str(value).strip() == ""
    )


def _display(value: object, unit: str) -> str:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return "N/A"
    try:
        return f"{float(value):.2f}{unit}"
    except (TypeError, ValueError):
        return f"{value}{unit}"


def _format_number(value: object, decimals: int) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    try:
        return f"{float(value):.{decimals}f}"
    except (TypeError, ValueError):
        return str(value)


def _percentage(value: object) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{float(value) * 100.0:.1f}%"


def _truth(value: object) -> bool:
    return str(value).strip().casefold() in {"true", "1", "yes"}


def _optional_int(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"true", "1", "yes", "on"}


if __name__ == "__main__":
    main()
