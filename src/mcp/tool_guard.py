"""Deterministic authorization and schema validation for LLM-selected tools."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

from jsonschema import Draft202012Validator


READ_ONLY_TOOLS = frozenset(
    {
        "load_idf_model",
        "validate_idf",
        "get_model_summary",
        "check_simulation_settings",
        "list_zones",
        "get_surfaces",
        "get_materials",
        "inspect_schedules",
        "inspect_people",
        "inspect_lights",
        "inspect_electric_equipment",
        "get_output_variables",
        "get_output_meters",
        "discover_hvac_loops",
        "get_loop_topology",
        "get_server_configuration",
        "create_interactive_plot",
        "visualize_loop_diagram",
    }
)
SIMULATION_TOOLS = frozenset({"run_energyplus_simulation"})
MODIFICATION_TOOLS = frozenset(
    {
        "add_output_variables",
        "add_output_meters",
        "modify_run_period",
        "modify_simulation_control",
    }
)
DEFAULT_AGENT_TOOLS = READ_ONLY_TOOLS | SIMULATION_TOOLS

_PATH_ARGUMENTS = {
    "idf_path",
    "weather_file",
    "output_directory",
    "output_path",
    "source_path",
    "target_path",
}
_SHELL_METACHARACTERS = re.compile(r"[;&|`$<>]")


@dataclass(frozen=True)
class ToolAuthorization:
    accepted: bool
    arguments: dict[str, Any]
    rejection_category: str | None = None
    message: str = ""


class MCPToolGuard:
    def __init__(
        self,
        run_root: Path,
        schemas: dict[str, dict[str, Any]],
        *,
        allow_modifications: bool = False,
        server_run_root: str | None = None,
    ) -> None:
        self.run_root = run_root.resolve()
        self.schemas = schemas
        self.allow_modifications = allow_modifications
        self.server_run_root = server_run_root or str(self.run_root)

    def _host_candidate(self, path_value: str) -> Path:
        if self.server_run_root.startswith("/") and path_value.startswith("/"):
            server_path = PurePosixPath(path_value)
            server_root = PurePosixPath(self.server_run_root)
            try:
                relative = server_path.relative_to(server_root)
            except ValueError:
                raise ValueError("Server path is outside the assigned run") from None
            return self.run_root / Path(relative.as_posix())

        server_root_path = Path(self.server_run_root)
        supplied = Path(path_value)
        if supplied.is_absolute() and server_root_path.is_absolute():
            try:
                relative = supplied.resolve().relative_to(
                    server_root_path.resolve()
                )
                return self.run_root / relative
            except ValueError:
                pass
        if supplied.is_absolute():
            return supplied
        return self.run_root / supplied

    def _within_run(self, path_value: str) -> bool:
        parsed = urlparse(path_value)
        if parsed.scheme.lower() in {"http", "https", "ftp", "file"}:
            return False
        if _SHELL_METACHARACTERS.search(path_value):
            return False
        try:
            candidate = self._host_candidate(path_value)
            candidate.resolve().relative_to(self.run_root)
        except (OSError, ValueError):
            return False
        return True

    def server_path(self, host_path: Path | str) -> str:
        candidate = Path(host_path)
        if not candidate.is_absolute():
            candidate = self.run_root / candidate
        resolved = candidate.resolve()
        try:
            relative = resolved.relative_to(self.run_root)
        except ValueError:
            raise ValueError("Path escapes the assigned run workspace") from None
        if self.server_run_root.startswith("/"):
            return str(
                PurePosixPath(self.server_run_root)
                / PurePosixPath(relative.as_posix())
            )
        return str(Path(self.server_run_root) / relative)

    def authorize(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> ToolAuthorization:
        allowed = set(DEFAULT_AGENT_TOOLS)
        if self.allow_modifications:
            allowed.update(MODIFICATION_TOOLS)
        if tool_name not in allowed:
            return ToolAuthorization(
                False, {}, "tool_not_allowlisted", "Tool is not allowlisted"
            )
        tool = self.schemas.get(tool_name)
        if tool is None:
            return ToolAuthorization(
                False, {}, "unknown_tool", "Tool is absent from server inventory"
            )
        if not isinstance(arguments, dict):
            return ToolAuthorization(
                False, {}, "invalid_arguments", "Arguments must be an object"
            )

        schema = dict(tool.get("input_schema", {}))
        properties = schema.get("properties", {})
        unknown = set(arguments) - set(properties)
        if unknown:
            return ToolAuthorization(
                False,
                {},
                "unknown_argument",
                f"Unknown argument(s): {', '.join(sorted(unknown))}",
            )
        schema["additionalProperties"] = False
        errors = sorted(
            Draft202012Validator(schema).iter_errors(arguments),
            key=lambda item: list(item.path),
        )
        if errors:
            return ToolAuthorization(
                False, {}, "schema_validation", errors[0].message
            )

        normalized = dict(arguments)
        for key, value in arguments.items():
            if key not in _PATH_ARGUMENTS or value is None:
                continue
            if not isinstance(value, str) or not self._within_run(value):
                return ToolAuthorization(
                    False,
                    {},
                    "path_boundary",
                    f"Path argument {key!r} is outside the assigned run",
                )
            candidate = self._host_candidate(value)
            normalized[key] = self.server_path(candidate)

        return ToolAuthorization(True, normalized)
