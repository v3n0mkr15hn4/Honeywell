"""EnergyPlus simulation runner."""

from __future__ import annotations

import os
import sys
from typing import Any

from controller.pipeline import ControlPipeline
from controller.llm_controller import LLMController
from controller.candidate_ranking_parser import (
    CANDIDATE_RANKING_RESPONSE_SCHEMA,
)
from controller.llm_policy_ranker import LLMPolicyRanker
from controller.policy_aware_rule_controller import PolicyAwareRuleController
from controller.policy_validator import PolicyLimits, PolicyValidator
from controller.rule_controller import RuleController
from controller.safety import SafetyValidator
from energyplus.actuators import ActuatorWriter
from energyplus.callbacks import EnergyPlusCallbacks
from energyplus.config import (
    ActuatorControlMode,
    ControllerType,
    EnergyPlusConfig,
    LLMProvider,
    SUPPLY_NODE_MAX_SETPOINT_C,
    SUPPLY_NODE_MIN_SETPOINT_C,
)
from energyplus.sensors import SensorReader
from llm.client import MockLLMClient, OllamaLLMClient
from llm.candidate_ranker_mock_client import MockCandidateRankerLLMClient
from llm.nvidia_nim_client import NvidiaNIMClient
from telemetry.logger import ControlLogger
from telemetry.metrics import MetricsTracker


def load_energyplus_api(config: EnergyPlusConfig) -> Any:
    """Prepare Python/DLL paths and import EnergyPlusAPI."""

    if not config.energyplus_root.exists():
        raise SystemExit(f"EnergyPlus install not found: {config.energyplus_root}")

    if str(config.energyplus_root) not in sys.path:
        sys.path.insert(0, str(config.energyplus_root))

    if os.name == "nt":
        os.add_dll_directory(str(config.energyplus_root))

    from pyenergyplus.api import EnergyPlusAPI  # type: ignore[import-not-found]

    return EnergyPlusAPI()


def run_simulation(config: EnergyPlusConfig | None = None) -> int:
    """Create components, register callbacks, run EnergyPlus, and clean up."""

    config = config or EnergyPlusConfig()
    if config.controller_type == ControllerType.LLM:
        raise SystemExit(
            "Direct LLM actuator control is retired. Use "
            "ControllerType.HYBRID_SUPERVISORY for policy-only supervision."
        )
    _validate_paths(config)
    config.output_dir.mkdir(parents=True, exist_ok=True)

    api = load_energyplus_api(config)
    sim_state = api.state_manager.new_state()

    sensor_reader = SensorReader(api, config.actuator_control_mode)
    actuator_writer = ActuatorWriter(
        api,
        config.actuator_control_mode,
        config.legacy_heating_setpoint_c,
    )
    controller = _build_controller(config)
    supervisor = _build_supervisor(config)
    safety_validator = _build_safety_validator(config)
    logger = ControlLogger(config.control_log_path)
    metrics = MetricsTracker()
    pipeline = ControlPipeline(
        sensor_reader=sensor_reader,
        actuator_writer=actuator_writer,
        controller=controller,
        safety_validator=safety_validator,
        logger=logger,
        metrics=metrics,
        llm_decision_interval_timesteps=config.llm_decision_interval_timesteps,
        maximum_consecutive_llm_failures=(
            config.maximum_consecutive_llm_failures
        ),
        llm_failure_cooldown_intervals=(
            config.llm_failure_cooldown_intervals
        ),
        startup_controller=RuleController(),
        supervisor=supervisor,
        supervisor_interval_hours=config.supervisor_interval_hours,
        maximum_consecutive_supervisor_failures=(
            config.maximum_consecutive_supervisor_failures
        ),
        supervisor_failure_cooldown_intervals=(
            config.supervisor_failure_cooldown_intervals
        ),
    )
    callbacks = EnergyPlusCallbacks(api, pipeline)
    exit_code: int | None = None

    try:
        sensor_reader.request_variables(sim_state)

        api.runtime.callback_begin_zone_timestep_before_init_heat_balance(
            sim_state,
            callbacks.begin_zone_timestep_callback,
        )
        api.runtime.callback_after_predictor_after_hvac_managers(
            sim_state,
            callbacks.after_predictor_after_hvac_managers_callback,
        )
        api.runtime.callback_end_zone_timestep_after_zone_reporting(
            sim_state,
            callbacks.end_zone_timestep_callback,
        )

        api.runtime.set_console_output_status(sim_state, False)

        command_line_args = [
            "-d",
            str(config.output_dir),
            "-w",
            str(config.epw_path),
            str(config.idf_path),
        ]

        print("[EnergyPlus] Starting simulation...")
        print(f"[EnergyPlus] IDF: {config.idf_path}")
        print(f"[EnergyPlus] EPW: {config.epw_path}")
        print(f"[EnergyPlus] Output directory: {config.output_dir}")
        print(f"[EnergyPlus] Control log: {config.control_log_path}")
        print(
            f"[EnergyPlus] Actuator mode: {config.actuator_control_mode.value}"
        )
        print(
            "[EnergyPlus] LLM decision interval: "
            f"{config.llm_decision_interval_timesteps} zone timesteps "
            "(one simulated hour at six timesteps/hour)"
        )
        if config.controller_type == ControllerType.LLM:
            print(f"[EnergyPlus] LLM provider: {config.llm_provider.value}")
            if config.llm_provider == LLMProvider.OLLAMA:
                print(f"[EnergyPlus] Ollama model: {config.ollama_model}")
        if config.controller_type == ControllerType.HYBRID_SUPERVISORY:
            print(
                "[EnergyPlus] Supervisory interval: "
                f"{config.supervisor_interval_hours:.1f} simulated hours"
            )
            print(
                f"[EnergyPlus] Supervisor provider: {config.llm_provider.value}"
            )
        print()

        exit_code = api.runtime.run_energyplus(sim_state, command_line_args)
        print()
        print(f"[EnergyPlus] Simulation finished with exit code {exit_code}")
        return exit_code
    finally:
        metrics.finish(exit_code)
        metrics.write_summary(config.summary_report_path)
        logger.close()
        api.state_manager.delete_state(sim_state)


def _validate_paths(config: EnergyPlusConfig) -> None:
    if not config.idf_path.exists():
        raise SystemExit(f"IDF file not found: {config.idf_path}")

    if not config.epw_path.exists():
        raise SystemExit(f"Weather file not found: {config.epw_path}")


def _build_controller(config: EnergyPlusConfig) -> Any:
    """Create the selected controller without changing callback code."""

    if config.controller_type == ControllerType.LLM:
        client = (
            OllamaLLMClient(
                model=config.ollama_model,
                base_url=config.ollama_base_url,
                connect_timeout_s=config.ollama_connect_timeout_s,
                response_timeout_s=config.ollama_response_timeout_s,
                temperature=config.llm_temperature,
                stream=config.ollama_stream,
                json_mode=config.ollama_json_mode,
                keep_alive=config.ollama_keep_alive,
                max_output_tokens=config.ollama_max_output_tokens,
            )
            if config.llm_provider == LLMProvider.OLLAMA
            else MockLLMClient(mock_mode=config.mock_llm_mode)
        )
        return LLMController(
            client=client,
            fallback_controller=RuleController(),
        )
    if config.controller_type == ControllerType.HYBRID_SUPERVISORY:
        return PolicyAwareRuleController()

    return RuleController()


def _build_supervisor(
    config: EnergyPlusConfig,
) -> LLMPolicyRanker | None:
    """Build the bounded candidate-ranking boundary for hybrid mode."""

    if config.controller_type != ControllerType.HYBRID_SUPERVISORY:
        return None
    if not config.supervisor_enabled:
        return None
    limits = PolicyLimits(
        minimum_target_zone_temperature_c=(
            config.minimum_policy_target_zone_temperature_c
        ),
        maximum_target_zone_temperature_c=(
            config.maximum_policy_target_zone_temperature_c
        ),
        minimum_action_hold_intervals=(
            config.minimum_policy_action_hold_intervals
        ),
        maximum_action_hold_intervals=(
            config.maximum_policy_action_hold_intervals
        ),
        minimum_policy_duration_hours=(
            config.minimum_policy_duration_hours
        ),
        maximum_policy_duration_hours=(
            config.maximum_policy_duration_hours
        ),
    )
    validator = PolicyValidator(limits=limits)
    if config.llm_provider == LLMProvider.OLLAMA:
        client = OllamaLLMClient(
            model=config.ollama_model,
            base_url=config.ollama_base_url,
            connect_timeout_s=config.ollama_connect_timeout_s,
            response_timeout_s=config.ollama_response_timeout_s,
            temperature=config.llm_temperature,
            stream=config.ollama_stream,
            json_mode=config.ollama_json_mode,
            keep_alive=config.ollama_keep_alive,
            max_output_tokens=config.ollama_max_output_tokens,
            response_schema=CANDIDATE_RANKING_RESPONSE_SCHEMA,
        )
        model = config.ollama_model
    elif config.llm_provider == LLMProvider.NVIDIA_NIM:
        client = NvidiaNIMClient(
            model=config.nvidia_nim_model,
            base_url=config.nvidia_nim_base_url,
            timeout_s=config.nvidia_nim_timeout_s,
            max_retries=config.nvidia_nim_max_retries,
            max_tokens=config.nvidia_nim_max_tokens,
            temperature=config.nvidia_nim_temperature,
            top_p=config.nvidia_nim_top_p,
        )
        model = config.nvidia_nim_model
    else:
        client = MockCandidateRankerLLMClient(
            config.mock_candidate_ranker_mode
        )
        model = config.mock_candidate_ranker_mode.value
    return LLMPolicyRanker(
        client=client,
        validator=validator,
        provider=config.llm_provider.value,
        model=model,
        policy_grace_period_hours=(
            config.supervisor_policy_grace_period_hours
        ),
    )


def _build_safety_validator(config: EnergyPlusConfig) -> SafetyValidator:
    """Use physical limits appropriate to the selected actuator target."""

    if config.actuator_control_mode == ActuatorControlMode.SUPPLY_NODE_SETPOINT:
        return SafetyValidator(
            minimum_supply_air_setpoint_c=SUPPLY_NODE_MIN_SETPOINT_C,
            maximum_supply_air_setpoint_c=SUPPLY_NODE_MAX_SETPOINT_C,
            maximum_change_per_decision_c=1.0,
        )
    return SafetyValidator()
