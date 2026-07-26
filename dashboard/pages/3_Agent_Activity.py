"""Observable tool activity only; hidden model reasoning is never displayed."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.mcp_runtime import read_json_inside, selected_workspace


st.set_page_config(page_title="Agent Activity", page_icon=":material/route:", layout="wide")
st.title("Agent Activity")
workspace = selected_workspace(st.session_state)
if workspace is None:
    st.info("Select or create a simulation run first.")
    st.stop()

activity = read_json_inside(workspace, "metadata/agent_activity.json")
if not isinstance(activity, dict):
    st.info("No agent activity has been recorded for this run.")
    st.stop()

top = st.columns(4)
top[0].metric("Run", workspace.run_id[:8])
top[1].metric("Agent status", activity.get("status", "unknown"))
top[2].metric("Simulation launched", "Yes" if activity.get("simulation_launched") else "No")
top[3].metric("Fallback", "Yes" if activity.get("fallback_used") else "No")

rows = activity.get("activities", [])
if rows:
    display_rows = [
        {
            "Step": row.get("step"),
            "MCP tool": row.get("tool_requested"),
            "Accepted": row.get("accepted"),
            "Reason": row.get("reason"),
            "Duration s": row.get("tool_duration_seconds"),
            "Success": row.get("tool_success"),
            "Result": row.get("result_summary"),
        }
        for row in rows
    ]
    st.dataframe(pd.DataFrame(display_rows), hide_index=True, width="stretch")
else:
    st.info("The agent returned without requesting an MCP tool.")

st.subheader("Final Answer")
st.write(activity.get("final_summary", "No final answer recorded."))
