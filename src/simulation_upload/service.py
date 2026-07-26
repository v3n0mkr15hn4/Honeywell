"""Application service joining uploads, MCP, the bounded agent, and reports."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from src.agent.controller_compatibility import ControllerCompatibilityAnalyser
from src.agent.energyplus_agent import (
    EnergyPlusAgent,
    EnergyPlusAgentResult,
    NvidiaNIMEnergyPlusModel,
)
from src.mcp.config import EnergyPlusMCPConfig
from src.mcp.energyplus_mcp_client import EnergyPlusMCPClient
from src.simulation_upload.error_analyser import EnergyPlusErrorAnalyser
from src.simulation_upload.workspace import RunWorkspace, RunWorkspaceManager


REQUIRED_MCP_TOOLS = frozenset(
    {
        "load_idf_model",
        "validate_idf",
        "get_model_summary",
        "check_simulation_settings",
        "list_zones",
        "inspect_schedules",
        "get_output_variables",
        "get_output_meters",
        "discover_hvac_loops",
        "get_loop_topology",
        "run_energyplus_simulation",
        "create_interactive_plot",
    }
)


def run_async(coro: Any) -> Any:
    """Run one async operation from a synchronous dashboard worker."""
    return asyncio.run(coro)


async def inspect_inventory(
    config: EnergyPlusMCPConfig,
) -> dict[str, Any]:
    client = EnergyPlusMCPClient(config)
    health = await client.health_check()
    if not health.healthy:
        return {
            "compatible": False,
            "health": asdict(health),
            "server": None,
            "tools": [],
            "missing_required_tools": sorted(REQUIRED_MCP_TOOLS),
        }
    try:
        async with client:
            tools = await client.list_tools()
            names = {tool["name"] for tool in tools}
            missing = sorted(REQUIRED_MCP_TOOLS - names)
            server = asdict(client.server_info) if client.server_info else None
            configuration = await client.call_tool("get_server_configuration", {})
            if (
                server is not None
                and not configuration.is_error
                and isinstance(configuration.structured_content, dict)
            ):
                application = configuration.structured_content.get("server", {})
                if isinstance(application, dict):
                    server["application_version"] = application.get("version")
            return {
                "compatible": not missing,
                "health": asdict(health),
                "server": server,
                "tools": tools,
                "missing_required_tools": missing,
            }
    except Exception as exc:
        return {
            "compatible": False,
            "health": asdict(health),
            "server": None,
            "tools": [],
            "missing_required_tools": sorted(REQUIRED_MCP_TOOLS),
            "error": str(exc)[:500],
        }


async def run_agent_task(
    config: EnergyPlusMCPConfig,
    workspace: RunWorkspace,
    task: str,
    *,
    simulation_approved: bool,
    model: Any | None = None,
) -> EnergyPlusAgentResult:
    async with EnergyPlusMCPClient(config) as client:
        agent = EnergyPlusAgent(
            client,
            model or NvidiaNIMEnergyPlusModel(),
            workspace,
            maximum_steps=10,
            allow_modifications=False,
        )
        result = await agent.run(task, simulation_approved=simulation_approved)
    _update_after_agent(config, workspace, result)
    return result


def _update_after_agent(
    config: EnergyPlusMCPConfig,
    workspace: RunWorkspace,
    result: EnergyPlusAgentResult,
) -> None:
    manager = RunWorkspaceManager(config.workspace_root)
    manifest = manager.read_manifest(workspace)
    manifest["tool_calls"].extend(
        {
            "step": item.step,
            "tool": item.tool_requested,
            "accepted": item.accepted,
            "status": (
                "success"
                if item.tool_success
                else item.rejection_category or "failed"
            ),
            "elapsed_seconds": item.tool_duration_seconds,
        }
        for item in result.activities
        if item.tool_requested
    )
    if result.simulation_launched:
        manifest["simulation_status"] = (
            "completed" if result.simulation_completed else "failed"
        )
    elif result.status == "ready":
        manifest["simulation_status"] = "ready"
    manifest["error_categories"] = sorted(
        {
            item.rejection_category
            for item in result.activities
            if item.rejection_category
        }
    )
    manager.write_manifest(workspace, manifest)

    if result.simulation_launched:
        analyser = EnergyPlusErrorAnalyser()
        errors = analyser.analyse(workspace.output_dir)
        (workspace.metadata_dir / "error_summary.json").write_text(
            json.dumps(errors.to_dict(), indent=2),
            encoding="utf-8",
        )
        (workspace.logs_dir / "energyplus_original.err").write_text(
            errors.original_error_log,
            encoding="utf-8",
        )


def create_compatibility_report(
    workspace: RunWorkspace,
    *,
    validation_succeeded: bool,
    tool_results: dict[str, list[str]],
    validated_project_idf: Path | str,
) -> dict[str, Any]:
    analyser = ControllerCompatibilityAnalyser(validated_project_idf)
    result = analyser.analyse(
        idf_path=next(workspace.input_dir.rglob("*.idf")),
        validation_succeeded=validation_succeeded,
        output_variables_text="\n".join(
            tool_results.get("get_output_variables", [])
        ),
        output_meters_text="\n".join(tool_results.get("get_output_meters", [])),
        # MCP model inspection does not verify Runtime API actuator handles.
        verified_actuator_inventory=[],
    )
    output = result.to_dict()
    (workspace.metadata_dir / "controller_compatibility.json").write_text(
        json.dumps(output, indent=2),
        encoding="utf-8",
    )
    return output
