"""Configuration for the local EnergyPlus simulation."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from llm.client import MockResponseMode
from llm.candidate_ranker_mock_client import CandidateRankerMockMode
from llm.supervisor_mock_client import SupervisorMockMode


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]


class ControllerType(str, Enum):
    """Available decision makers for the control pipeline."""

    RULE = "rule"
    LLM = "llm"
    HYBRID_SUPERVISORY = "hybrid_supervisory"


class LLMProvider(str, Enum):
    """Available implementations of the provider-neutral LLM client."""

    MOCK = "mock"
    OLLAMA = "ollama"
    NVIDIA_NIM = "nvidia_nim"


class ActuatorControlMode(str, Enum):
    """EnergyPlus actuator path used to apply cooling commands."""

    SCHEDULE = "schedule"
    ZONE_SETPOINT = "zone_setpoint"
    SUPPLY_NODE_SETPOINT = "supply_node_setpoint"


@dataclass(frozen=True)
class EnergyPlusConfig:
    """Filesystem paths needed to launch EnergyPlus."""

    energyplus_root: Path = Path(r"C:\EnergyPlusV26-1-0")
    idf_path: Path = WORKSPACE_ROOT / "1ZoneDataCenterCRAC_wApproachTemp.idf"
    epw_path: Path = WORKSPACE_ROOT / "USA_CA_San.Francisco.Intl.AP.724940_TMY3.epw"
    output_dir: Path = WORKSPACE_ROOT / "sampleSimulation" / "api_demo_output"
    control_log_path: Path = output_dir / "control_log.csv"
    summary_report_path: Path = output_dir / "control_summary.txt"
    controller_type: ControllerType = field(
        default_factory=lambda: _env_enum(
            "CONTROLLER_TYPE",
            ControllerType,
            ControllerType.RULE,
        )
    )
    llm_provider: LLMProvider = field(
        default_factory=lambda: _env_enum(
            "LLM_PROVIDER",
            LLMProvider,
            LLMProvider.MOCK,
        )
    )
    mock_llm_mode: MockResponseMode = MockResponseMode.VALID
    mock_supervisor_mode: SupervisorMockMode = (
        SupervisorMockMode.VALID_BALANCED
    )
    mock_candidate_ranker_mode: CandidateRankerMockMode = (
        CandidateRankerMockMode.VALID_TOP_DETERMINISTIC
    )
    supervisor_enabled: bool = field(
        default_factory=lambda: _env_bool("SUPERVISOR_ENABLED", True)
    )
    ollama_base_url: str = field(
        default_factory=lambda: os.getenv(
            "OLLAMA_BASE_URL",
            "http://localhost:11434",
        )
    )
    ollama_model: str = field(
        default_factory=lambda: os.getenv("OLLAMA_MODEL", "qwen3:1.7b")
    )
    ollama_connect_timeout_s: float = field(
        default_factory=lambda: _env_float("OLLAMA_CONNECT_TIMEOUT_S", 3.0)
    )
    ollama_response_timeout_s: float = field(
        default_factory=lambda: _env_float("OLLAMA_RESPONSE_TIMEOUT_S", 20.0)
    )
    llm_temperature: float = field(
        default_factory=lambda: _env_float("LLM_TEMPERATURE", 0.0)
    )
    ollama_stream: bool = field(
        default_factory=lambda: _env_bool("OLLAMA_STREAM", False)
    )
    ollama_json_mode: bool = field(
        default_factory=lambda: _env_bool("OLLAMA_JSON_MODE", True)
    )
    ollama_keep_alive: str = field(
        default_factory=lambda: os.getenv("OLLAMA_KEEP_ALIVE", "5m")
    )
    ollama_max_output_tokens: int = field(
        default_factory=lambda: _env_int("OLLAMA_MAX_OUTPUT_TOKENS", 128)
    )
    nvidia_nim_base_url: str = field(
        default_factory=lambda: os.getenv(
            "NVIDIA_NIM_BASE_URL",
            "https://integrate.api.nvidia.com/v1",
        )
    )
    nvidia_nim_model: str = field(
        default_factory=lambda: os.getenv(
            "NVIDIA_NIM_MODEL",
            "nvidia/llama-3.3-nemotron-super-49b-v1.5",
        )
    )
    nvidia_nim_timeout_s: float = field(
        default_factory=lambda: _env_float("NVIDIA_NIM_TIMEOUT_S", 30.0)
    )
    nvidia_nim_max_retries: int = field(
        default_factory=lambda: _env_int("NVIDIA_NIM_MAX_RETRIES", 1)
    )
    nvidia_nim_max_tokens: int = field(
        default_factory=lambda: _env_int("NVIDIA_NIM_MAX_TOKENS", 256)
    )
    nvidia_nim_temperature: float = field(
        default_factory=lambda: _env_float("NVIDIA_NIM_TEMPERATURE", 0.0)
    )
    nvidia_nim_top_p: float = field(
        default_factory=lambda: _env_float("NVIDIA_NIM_TOP_P", 1.0)
    )
    llm_decision_interval_timesteps: int = field(
        default_factory=lambda: _env_int("LLM_DECISION_INTERVAL_TIMESTEPS", 6)
    )
    maximum_consecutive_llm_failures: int = field(
        default_factory=lambda: _env_int(
            "MAXIMUM_CONSECUTIVE_LLM_FAILURES",
            3,
        )
    )
    llm_failure_cooldown_intervals: int = field(
        default_factory=lambda: _env_int(
            "LLM_FAILURE_COOLDOWN_INTERVALS",
            3,
        )
    )
    supervisor_interval_hours: float = field(
        default_factory=lambda: _env_float("SUPERVISOR_INTERVAL_HOURS", 3.0)
    )
    supervisor_policy_grace_period_hours: float = field(
        default_factory=lambda: _env_float(
            "SUPERVISOR_POLICY_GRACE_PERIOD_HOURS",
            2.0,
        )
    )
    maximum_consecutive_supervisor_failures: int = field(
        default_factory=lambda: _env_int(
            "MAXIMUM_CONSECUTIVE_SUPERVISOR_FAILURES",
            3,
        )
    )
    supervisor_failure_cooldown_intervals: int = field(
        default_factory=lambda: _env_int(
            "SUPERVISOR_FAILURE_COOLDOWN_INTERVALS",
            3,
        )
    )
    minimum_policy_target_zone_temperature_c: float = 30.0
    maximum_policy_target_zone_temperature_c: float = 34.0
    minimum_policy_action_hold_intervals: int = 1
    maximum_policy_action_hold_intervals: int = 6
    minimum_policy_duration_hours: int = 4
    maximum_policy_duration_hours: int = 12
    legacy_heating_setpoint_c: float = 18.0
    actuator_control_mode: ActuatorControlMode = (
        ActuatorControlMode.SUPPLY_NODE_SETPOINT
    )

    def __post_init__(self) -> None:
        if not 3.0 <= self.supervisor_interval_hours <= 6.0:
            raise ValueError(
                "supervisor_interval_hours must be between 3 and 6"
            )
        if self.supervisor_policy_grace_period_hours < 0:
            raise ValueError(
                "supervisor_policy_grace_period_hours must be non-negative"
            )
        if self.nvidia_nim_max_retries not in (0, 1):
            raise ValueError("nvidia_nim_max_retries must be 0 or 1")


ZONE_NAME = "Main Zone"

SCHEDULE_COOLING_ACTUATOR = (
    "Schedule:Compact",
    "Schedule Value",
    "Cooling Return Air Setpoint Schedule",
)
SCHEDULE_HEATING_ACTUATOR = (
    "Schedule:Compact",
    "Schedule Value",
    "Heating Setpoint Schedule",
)
ZONE_COOLING_ACTUATOR = (
    "Zone Temperature Control",
    "Cooling Setpoint",
    "MAIN ZONE",
)
ZONE_HEATING_ACTUATOR = (
    "Zone Temperature Control",
    "Heating Setpoint",
    "MAIN ZONE",
)
SUPPLY_NODE_COOLING_ACTUATOR = (
    "System Node Setpoint",
    "Temperature Setpoint",
    "MAIN COOLING COIL 1 OUTLET NODE",
)

# The selected node is constrained to the range proven by the physical A/B test.
SUPPLY_NODE_MIN_SETPOINT_C = 22.0
SUPPLY_NODE_MAX_SETPOINT_C = 25.0


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _env_float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_enum(name: str, enum_type: type[Enum], default: Enum):
    raw = os.getenv(name)
    if raw is None:
        return default
    return enum_type(raw.strip().lower())
