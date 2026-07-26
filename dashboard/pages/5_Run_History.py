"""Sanitized local run history."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.mcp_runtime import load_config, workspace_manager


st.set_page_config(page_title="Run History", page_icon=":material/history:", layout="wide")
st.title("Run History")
config = load_config()
runs = workspace_manager(config).list_runs()
if not runs:
    st.info("No uploaded-model runs have been created.")
    st.stop()

rows = [
    {
        "Run": item.get("run_id", "")[:8],
        "Uploaded UTC": item.get("upload_timestamp_utc"),
        "IDF": item.get("selected_idf"),
        "EPW": item.get("selected_epw"),
        "Version": item.get("detected_energyplus_version"),
        "Mode": item.get("simulation_mode"),
        "Status": item.get("simulation_status"),
        "Tool calls": len(item.get("tool_calls", [])),
    }
    for item in runs
]
st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
