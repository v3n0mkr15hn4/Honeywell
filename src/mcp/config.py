"""Environment-driven configuration for the EnergyPlus MCP integration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from pathlib import PurePosixPath
from urllib.parse import urlparse

from dotenv import load_dotenv


class MCPConfigurationError(ValueError):
    """Raised when MCP is enabled with incomplete or unsafe configuration."""


@dataclass(frozen=True)
class EnergyPlusMCPConfig:
    """Validated client and workspace configuration.

    The bearer token is intentionally excluded from ``repr`` so accidental
    logging of this object cannot disclose it.
    """

    enabled: bool
    url: str
    token: str = field(repr=False)
    timeout_seconds: float = 180.0
    workspace_root: Path = Path("simulation_workspace")
    server_workspace_root: str | None = None
    expected_version: str = "26.1.0"
    simulation_timeout_seconds: float = 600.0

    def __init__(
        self,
        enabled: bool,
        url: str,
        token: str,
        timeout_seconds: float = 180.0,
        workspace_root: Path | str = Path("simulation_workspace"),
        server_workspace_root: str | None = None,
        expected_version: str = "26.1.0",
        simulation_timeout_seconds: float = 600.0,
    ) -> None:
        object.__setattr__(self, "enabled", enabled)
        object.__setattr__(self, "url", url)
        object.__setattr__(self, "token", token)
        object.__setattr__(self, "timeout_seconds", timeout_seconds)
        object.__setattr__(self, "workspace_root", Path(workspace_root))
        object.__setattr__(self, "server_workspace_root", server_workspace_root)
        object.__setattr__(self, "expected_version", expected_version)
        object.__setattr__(
            self, "simulation_timeout_seconds", simulation_timeout_seconds
        )
        self.validate()

    def __repr__(self) -> str:
        return (
            "EnergyPlusMCPConfig("
            f"enabled={self.enabled!r}, url={self.url!r}, token='<redacted>', "
            f"timeout_seconds={self.timeout_seconds!r}, "
            f"workspace_root={str(self.workspace_root)!r}, "
            f"server_workspace_root={self.server_workspace_root!r}, "
            f"expected_version={self.expected_version!r}, "
            f"simulation_timeout_seconds={self.simulation_timeout_seconds!r})"
        )

    @classmethod
    def from_env(cls, env_file: Path | str | None = ".env") -> "EnergyPlusMCPConfig":
        if env_file:
            load_dotenv(dotenv_path=env_file, override=False)

        enabled = os.getenv("ENERGYPLUS_MCP_ENABLED", "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        root = os.getenv("ENERGYPLUS_MCP_WORKSPACE_ROOT", "simulation_workspace")
        return cls(
            enabled=enabled,
            url=os.getenv("ENERGYPLUS_MCP_URL", "http://127.0.0.1:8000/mcp"),
            token=os.getenv("ENERGYPLUS_MCP_TOKEN", ""),
            timeout_seconds=float(os.getenv("ENERGYPLUS_MCP_TIMEOUT_S", "180")),
            workspace_root=Path(root).expanduser(),
            server_workspace_root=os.getenv(
                "ENERGYPLUS_MCP_SERVER_WORKSPACE_ROOT"
            ),
            expected_version=os.getenv(
                "ENERGYPLUS_MCP_EXPECTED_VERSION", "26.1.0"
            ).strip(),
            simulation_timeout_seconds=float(
                os.getenv("ENERGYPLUS_SIMULATION_TIMEOUT_S", "600")
            ),
        )

    def validate(self) -> None:
        if not self.enabled:
            return
        parsed = urlparse(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise MCPConfigurationError("ENERGYPLUS_MCP_URL must be an HTTP(S) URL")
        if len(self.token) < 32:
            raise MCPConfigurationError(
                "ENERGYPLUS_MCP_TOKEN must contain at least 32 characters"
            )
        if self.timeout_seconds <= 0 or self.simulation_timeout_seconds <= 0:
            raise MCPConfigurationError("MCP timeouts must be positive")
        if not self.expected_version:
            raise MCPConfigurationError(
                "ENERGYPLUS_MCP_EXPECTED_VERSION must not be empty"
            )

        root = self.workspace_root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        if not root.is_dir():
            raise MCPConfigurationError("MCP workspace root is not a directory")
        object.__setattr__(self, "workspace_root", root)
        if not self.server_workspace_root:
            object.__setattr__(self, "server_workspace_root", str(root))

    def server_run_root(self, run_id: str) -> str:
        root = str(self.server_workspace_root)
        if root.startswith("/"):
            return str(PurePosixPath(root) / "runs" / run_id)
        return str(Path(root) / "runs" / run_id)
