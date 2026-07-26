"""Real NVIDIA-to-MCP inspection gate. This never launches a simulation."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from src.mcp.config import EnergyPlusMCPConfig
from src.simulation_upload.package_validator import (
    SimulationPackageValidator,
    UploadedFile,
)
from src.simulation_upload.service import run_agent_task
from src.simulation_upload.workspace import RunWorkspaceManager


ROOT = Path(__file__).resolve().parents[1]
RESULTS_PATH = ROOT / "test_reports" / "energyplus_mcp_agent_validation_results.json"
REQUIRED_INSPECTION = {
    "load_idf_model",
    "validate_idf",
    "get_model_summary",
    "check_simulation_settings",
    "get_output_variables",
    "get_output_meters",
    "discover_hvac_loops",
}


async def run_gate() -> int:
    load_dotenv(ROOT / ".env", override=False)
    if not os.getenv("NVIDIA_NIM_API_KEY"):
        print("[NVIDIA MCP Agent] status=fail category=configuration")
        return 2

    config = EnergyPlusMCPConfig.from_env(ROOT / ".env")
    validation = SimulationPackageValidator(
        expected_version=config.expected_version
    ).validate(
        [
            UploadedFile(
                "1ZoneDataCenterCRAC_wApproachTemp.idf",
                (ROOT / "1ZoneDataCenterCRAC_wApproachTemp.idf").read_bytes(),
            ),
            UploadedFile(
                "USA_CA_San.Francisco.Intl.AP.724940_TMY3.epw",
                (
                    ROOT / "USA_CA_San.Francisco.Intl.AP.724940_TMY3.epw"
                ).read_bytes(),
            ),
        ]
    )
    if not validation.valid:
        print("[NVIDIA MCP Agent] status=fail category=local_validation")
        return 3

    manager = RunWorkspaceManager(config.workspace_root)
    workspace = manager.create()
    manager.stage_validated_package(workspace, validation)
    result = await run_agent_task(
        config,
        workspace,
        (
            "Inspect this uploaded model for judge readiness. You must call "
            "load_idf_model, validate_idf, get_model_summary, "
            "check_simulation_settings, get_output_variables, "
            "get_output_meters, and discover_hvac_loops before returning the "
            "final answer. Do not run a simulation and do not modify files."
        ),
        simulation_approved=False,
    )
    successful = {
        activity.tool_requested
        for activity in result.activities
        if activity.accepted and activity.tool_success
    }
    missing = sorted(REQUIRED_INSPECTION - successful)
    passed = (
        result.status in {"ready", "completed"}
        and not missing
        and not result.simulation_launched
    )

    existing = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    existing["protocol"] = "native_function_calling"
    existing["real_nvidia_agent_test"] = {
        "status": "pass" if passed else "fail",
        "run_id": workspace.run_id,
        "successful_tools": sorted(successful),
        "missing_tools": missing,
        "agent_status": result.status,
        "simulation_launched": result.simulation_launched,
        "activity_steps": len(result.activities),
    }
    existing["result"] = (
        "mock_boundary_and_real_nvidia_pass"
        if passed
        else "mock_boundary_pass_real_nvidia_fail"
    )
    RESULTS_PATH.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    print(
        "[NVIDIA MCP Agent] "
        f"status={'pass' if passed else 'fail'} "
        f"steps={len(result.activities)} missing={len(missing)}"
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run_gate()))
