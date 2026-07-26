"""Shared runtime objects and safe dashboard data access for MCP pages."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.mcp.config import EnergyPlusMCPConfig  # noqa: E402
from src.simulation_upload.job_manager import SimulationJobManager  # noqa: E402
from src.simulation_upload.workspace import (  # noqa: E402
    RunWorkspace,
    RunWorkspaceManager,
)


JOB_MANAGER = SimulationJobManager()
SAFE_DOWNLOAD_EXTENSIONS = frozenset(
    {".json", ".err", ".csv", ".html", ".htm", ".svg", ".png", ".txt", ".md"}
)


def load_config() -> EnergyPlusMCPConfig:
    return EnergyPlusMCPConfig.from_env(PROJECT_ROOT / ".env")


def workspace_manager(config: EnergyPlusMCPConfig) -> RunWorkspaceManager:
    return RunWorkspaceManager(config.workspace_root)


def selected_workspace(session_state: Any) -> RunWorkspace | None:
    run_id = session_state.get("mcp_run_id")
    if not run_id:
        return None
    try:
        return workspace_manager(load_config()).get(run_id)
    except (ValueError, FileNotFoundError):
        return None


def read_json_inside(
    workspace: RunWorkspace, relative_path: str
) -> dict[str, Any] | list[Any] | None:
    path = workspace.resolve_inside(relative_path)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def safe_result_files(workspace: RunWorkspace) -> list[Path]:
    files: list[Path] = []
    for base in (workspace.output_dir, workspace.logs_dir, workspace.metadata_dir):
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in SAFE_DOWNLOAD_EXTENSIONS:
                continue
            workspace.resolve_inside(path)
            files.append(path)
    return sorted(files)
