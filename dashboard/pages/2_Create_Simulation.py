"""Secure judge upload and explicitly approved EnergyPlus execution page."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import streamlit as st

from dashboard.mcp_runtime import (
    JOB_MANAGER,
    PROJECT_ROOT,
    load_config,
    selected_workspace,
    workspace_manager,
)
from src.simulation_upload.package_validator import (
    SimulationPackageValidator,
    UploadedFile,
)
from src.simulation_upload.service import (
    create_compatibility_report,
    inspect_inventory,
    run_agent_task,
    run_async,
)


st.set_page_config(page_title="Create Simulation", page_icon=":material/upload_file:", layout="wide")
st.title("Create Simulation")
st.info(
    "Uploaded files are executed inside an isolated local simulation workspace. "
    "Only allowlisted EnergyPlus files are accepted."
)

try:
    config = load_config()
except Exception as exc:
    st.error(f"MCP configuration error: {exc}")
    st.stop()

inventory = run_async(inspect_inventory(config))
health_col, tools_col, version_col = st.columns(3)
health_col.metric("MCP service", "Ready" if inventory["health"]["healthy"] else "Unavailable")
tools_col.metric("Official tools", len(inventory["tools"]))
version_col.metric("Expected EnergyPlus", config.expected_version)
if not inventory["compatible"]:
    missing = ", ".join(inventory["missing_required_tools"])
    st.error(f"Simulation creation is disabled. Missing required MCP tools: {missing}")
    st.stop()

idf_file = st.file_uploader("IDF model", type=["idf"])
epw_file = st.file_uploader("EPW weather", type=["epw"])
support_files = st.file_uploader(
    "Supporting files", type=["ddy", "csv", "json", "txt"], accept_multiple_files=True
)
zip_file = st.file_uploader("Or upload one ZIP package", type=["zip"])

if st.button("Validate package", type="primary"):
    uploads: list[UploadedFile] = []
    if zip_file is not None:
        uploads.append(UploadedFile(zip_file.name, zip_file.getvalue()))
    else:
        if idf_file is not None:
            uploads.append(UploadedFile(idf_file.name, idf_file.getvalue()))
        if epw_file is not None:
            uploads.append(UploadedFile(epw_file.name, epw_file.getvalue()))
        uploads.extend(UploadedFile(item.name, item.getvalue()) for item in support_files)

    validation = SimulationPackageValidator(
        expected_version=config.expected_version
    ).validate(uploads)
    st.session_state["mcp_local_validation"] = {
        "valid": validation.valid,
        "errors": validation.errors,
        "warnings": validation.warnings,
        "detected_version": validation.detected_version,
    }
    if validation.valid:
        manager = workspace_manager(config)
        workspace = manager.create()
        server = inventory.get("server") or {}
        manager.stage_validated_package(
            workspace,
            validation,
            mcp_server_version=server.get("application_version")
            or server.get("version"),
        )
        JOB_MANAGER.set_status(workspace, "ready", "Local package validation passed")
        st.session_state["mcp_run_id"] = workspace.run_id
        st.session_state.pop("mcp_agent_result", None)
        st.session_state.pop("mcp_model_validated", None)

validation_view = st.session_state.get("mcp_local_validation")
if validation_view:
    if validation_view["valid"]:
        st.success(
            f"Package accepted. Detected EnergyPlus version: "
            f"{validation_view['detected_version']}"
        )
    else:
        for error in validation_view["errors"]:
            st.error(error)
    for warning in validation_view["warnings"]:
        st.warning(warning)

workspace = selected_workspace(st.session_state)
if workspace is None:
    st.stop()

manifest = workspace_manager(config).read_manifest(workspace)
st.subheader("Model Inspection")
task_options = [
    "Validate my uploaded IDF and inspect its zones, simulation settings, outputs, meters, and HVAC loops.",
    "What zones and HVAC loops are present?",
    "Does this model contain outputs required for temperature and power monitoring?",
    "Check the simulation run period.",
    "Is this model compatible with the closed-loop controller?",
]
selected_task = st.selectbox("Judge task", task_options)
custom_task = st.text_input("Optional custom inspection task")

if st.button("Validate model"):
    st.session_state["mcp_model_validated"] = False
    try:
        result = run_async(
            run_agent_task(
                config,
                workspace,
                custom_task.strip() or selected_task,
                simulation_approved=False,
            )
        )
        st.session_state["mcp_agent_result"] = asdict(result)
        validate_ok = any(
            activity.tool_requested == "validate_idf"
            and activity.tool_success
            for activity in result.activities
        )
        compatibility = create_compatibility_report(
            workspace,
            validation_succeeded=validate_ok,
            tool_results=result.tool_results,
            validated_project_idf=PROJECT_ROOT / "1ZoneDataCenterCRAC_wApproachTemp.idf",
        )
        st.session_state["mcp_compatibility"] = compatibility
        st.session_state["mcp_model_validated"] = validate_ok
    except Exception as exc:
        st.error(f"Agent inspection failed safely: {exc}")

agent_result = st.session_state.get("mcp_agent_result")
if agent_result:
    st.write(agent_result["summary"])
    compatibility = st.session_state.get("mcp_compatibility", {})
    mode = (
        "Closed-loop compatible"
        if compatibility.get("closed_loop_compatible")
        else "Standard EnergyPlus"
    )
    st.metric("Simulation mode", mode)
    if compatibility.get("missing_requirements"):
        st.caption("Closed-loop mapping missing: " + "; ".join(compatibility["missing_requirements"]))

st.subheader("Simulation Approval")
approval_cols = st.columns(3)
approval_cols[0].metric("IDF", Path(manifest["selected_idf"]).name)
approval_cols[1].metric("EPW", Path(manifest["selected_epw"]).name)
approval_cols[2].metric("Time limit", f"{config.simulation_timeout_seconds:.0f} s")
st.caption(
    f"Output: run {workspace.run_id[:8]}/output | "
    f"Version: {config.expected_version} | Modifications: none"
)

already_launched = any(
    item.get("tool") == "run_energyplus_simulation" and item.get("accepted")
    for item in manifest.get("tool_calls", [])
)
ready_for_run = (
    bool(agent_result)
    and bool(st.session_state.get("mcp_model_validated"))
    and not already_launched
)
if st.button(
    "Run Simulation",
    type="primary",
    disabled=not ready_for_run,
):
    def approved_operation() -> dict[str, object]:
        result = run_async(
            run_agent_task(
                config,
                workspace,
                "The judge approved one standard EnergyPlus simulation. "
                "Validate the IDF, run it once with the assigned EPW and output "
                "directory, then report the observable result.",
                simulation_approved=True,
            )
        )
        if not result.simulation_completed:
            raise RuntimeError(
                "The approved agent task ended without a successful "
                "run_energyplus_simulation result."
            )
        return asdict(result)

    try:
        JOB_MANAGER.submit(
            workspace,
            approved_operation,
            timeout_seconds=config.simulation_timeout_seconds,
        )
        st.success("Simulation queued.")
    except RuntimeError as exc:
        st.warning(str(exc))

job = JOB_MANAGER.poll(workspace)
st.status(f"Job status: {job.status}", expanded=job.status in {"running", "failed"})
if job.message:
    st.caption(job.message)
