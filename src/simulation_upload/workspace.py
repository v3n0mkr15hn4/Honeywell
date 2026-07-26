"""Per-run filesystem isolation and secret-free manifests."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .package_validator import PackageValidationResult


_RUN_ID_RE = re.compile(r"^[0-9a-f]{32}$")


@dataclass(frozen=True)
class RunWorkspace:
    run_id: str
    root: Path
    input_dir: Path
    working_dir: Path
    output_dir: Path
    logs_dir: Path
    metadata_dir: Path

    def resolve_inside(self, path: Path | str) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        resolved = candidate.resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError:
            raise ValueError("Path escapes the assigned run workspace") from None
        return resolved

    @property
    def manifest_path(self) -> Path:
        return self.metadata_dir / "run_manifest.json"

    def relative(self, path: Path | str) -> str:
        return self.resolve_inside(path).relative_to(self.root).as_posix()


class RunWorkspaceManager:
    def __init__(self, workspace_root: Path | str) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.runs_root = self.workspace_root / "runs"
        self.runs_root.mkdir(parents=True, exist_ok=True)

    def create(self) -> RunWorkspace:
        run_id = uuid.uuid4().hex
        root = (self.runs_root / run_id).resolve()
        root.relative_to(self.runs_root)
        directories = {
            name: root / name
            for name in ("input", "working", "output", "logs", "metadata")
        }
        for directory in directories.values():
            directory.mkdir(parents=True, exist_ok=False)
        return RunWorkspace(
            run_id=run_id,
            root=root,
            input_dir=directories["input"],
            working_dir=directories["working"],
            output_dir=directories["output"],
            logs_dir=directories["logs"],
            metadata_dir=directories["metadata"],
        )

    def get(self, run_id: str) -> RunWorkspace:
        if not _RUN_ID_RE.fullmatch(run_id):
            raise ValueError("Invalid run ID")
        root = (self.runs_root / run_id).resolve()
        root.relative_to(self.runs_root)
        if not root.is_dir():
            raise FileNotFoundError(f"Run does not exist: {run_id}")
        return RunWorkspace(
            run_id=run_id,
            root=root,
            input_dir=root / "input",
            working_dir=root / "working",
            output_dir=root / "output",
            logs_dir=root / "logs",
            metadata_dir=root / "metadata",
        )

    def stage_validated_package(
        self,
        workspace: RunWorkspace,
        validation: PackageValidationResult,
        *,
        mcp_server_version: str | None = None,
    ) -> dict[str, Any]:
        if not validation.valid:
            raise ValueError("Only a valid, version-compatible package may be staged")

        file_records: list[dict[str, Any]] = []
        for item in validation.files:
            target = workspace.resolve_inside(workspace.input_dir / item.relative_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(item.content)
            file_records.append(
                {
                    "filename": item.relative_path,
                    "size_bytes": len(item.content),
                    "sha256": hashlib.sha256(item.content).hexdigest(),
                }
            )

        manifest: dict[str, Any] = {
            "run_id": workspace.run_id,
            "upload_timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "files": file_records,
            "selected_idf": validation.idf_path,
            "selected_epw": validation.epw_path,
            "support_files": validation.support_files,
            "detected_energyplus_version": validation.detected_version,
            "version_status": validation.version_status,
            "mcp_server_version": mcp_server_version,
            "selected_run_period": None,
            "simulation_mode": "Standard EnergyPlus",
            "simulation_status": "uploaded",
            "tool_calls": [],
            "result_paths": [],
            "error_categories": [],
        }
        self.write_manifest(workspace, manifest)
        return manifest

    @staticmethod
    def write_manifest(
        workspace: RunWorkspace, manifest: dict[str, Any]
    ) -> None:
        safe_manifest = dict(manifest)
        forbidden = {"token", "api_key", "authorization", "headers"}
        if any(key.lower() in forbidden for key in safe_manifest):
            raise ValueError("Manifest contains a forbidden secret-bearing field")
        workspace.manifest_path.write_text(
            json.dumps(safe_manifest, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    @staticmethod
    def read_manifest(workspace: RunWorkspace) -> dict[str, Any]:
        return json.loads(workspace.manifest_path.read_text(encoding="utf-8"))

    def list_runs(self) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        for manifest_path in self.runs_root.glob("*/metadata/run_manifest.json"):
            try:
                runs.append(json.loads(manifest_path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return sorted(
            runs, key=lambda item: item.get("upload_timestamp_utc", ""), reverse=True
        )
