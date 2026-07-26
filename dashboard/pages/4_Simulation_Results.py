"""Run-scoped EnergyPlus results, logs, charts, and safe downloads."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from dashboard.mcp_runtime import (
    read_json_inside,
    safe_result_files,
    selected_workspace,
)


st.set_page_config(page_title="Simulation Results", page_icon=":material/analytics:", layout="wide")
st.title("Simulation Results")
workspace = selected_workspace(st.session_state)
if workspace is None:
    st.info("Select or create a simulation run first.")
    st.stop()

manifest = read_json_inside(workspace, "metadata/run_manifest.json") or {}
errors = read_json_inside(workspace, "metadata/error_summary.json") or {}
compatibility = read_json_inside(workspace, "metadata/controller_compatibility.json") or {}
job = read_json_inside(workspace, "metadata/job_status.json") or {}

metrics = st.columns(5)
metrics[0].metric("Status", job.get("status", manifest.get("simulation_status", "unknown")))
metrics[1].metric("Mode", manifest.get("simulation_mode", "Standard EnergyPlus"))
metrics[2].metric("Fatal", errors.get("fatal_errors") and len(errors["fatal_errors"]) or 0)
metrics[3].metric("Severe", errors.get("severe_errors") and len(errors["severe_errors"]) or 0)
metrics[4].metric("Warnings", errors.get("warnings") and len(errors["warnings"]) or 0)

st.subheader("Compatibility")
st.write(
    "Closed-loop compatible"
    if compatibility.get("closed_loop_compatible")
    else "Standard simulation only"
)
if compatibility.get("missing_requirements"):
    st.caption("; ".join(compatibility["missing_requirements"]))

csv_files = sorted(workspace.output_dir.glob("*.csv"))
for csv_path in csv_files[:4]:
    try:
        frame = pd.read_csv(csv_path)
    except Exception:
        continue
    numeric = frame.select_dtypes(include="number")
    candidates = [
        column
        for column in numeric.columns
        if "temperature" in column.lower()
        or "electric" in column.lower()
        or "energy" in column.lower()
        or "power" in column.lower()
    ]
    if candidates:
        st.subheader(csv_path.name)
        st.line_chart(numeric[candidates[:6]])

original_log = workspace.logs_dir / "energyplus_original.err"
if original_log.is_file():
    with st.expander("Original EnergyPlus error log"):
        st.code(original_log.read_text(encoding="utf-8", errors="replace"))

st.caption("AI-generated interpretation - verify against original EnergyPlus log")
agent = read_json_inside(workspace, "metadata/agent_activity.json") or {}
st.write(agent.get("final_summary", "No AI interpretation is available."))

st.subheader("Downloads")
for path in safe_result_files(workspace):
    st.download_button(
        label=path.relative_to(workspace.root).as_posix(),
        data=path.read_bytes(),
        file_name=path.name,
        mime="application/octet-stream",
        key=f"download-{path.relative_to(workspace.root).as_posix()}",
    )
