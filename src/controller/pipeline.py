"""Closed-loop orchestration for sensing, deciding, validating, and acting."""

from __future__ import annotations

from typing import Any

from controller.action import ControlAction
from controller.controller_state import ControllerState
from controller.rule_controller import RuleController
from controller.safety import SafetyValidator, ValidationResult
from controller.supervisor_policy import default_supervisor_policy
from controller.supervisory_llm_controller import SupervisoryLLMController
from energyplus.actuators import ActuatorWriter
from energyplus.sensors import SensorReader
from telemetry.logger import ControlLogger
from telemetry.metrics import MetricsTracker


class ControlPipeline:
    """Coordinate callbacks, decision cadence, fallback, safety, and telemetry."""

    def __init__(
        self,
        sensor_reader: SensorReader,
        actuator_writer: ActuatorWriter,
        controller: Any,
        safety_validator: SafetyValidator,
        logger: ControlLogger,
        metrics: MetricsTracker | None = None,
        initial_action: ControlAction | None = None,
        llm_decision_interval_timesteps: int = 6,
        maximum_consecutive_llm_failures: int = 3,
        llm_failure_cooldown_intervals: int = 3,
        startup_controller: RuleController | None = None,
        supervisor: SupervisoryLLMController | None = None,
        supervisor_interval_hours: float = 6.0,
        maximum_consecutive_supervisor_failures: int = 3,
        supervisor_failure_cooldown_intervals: int = 3,
    ) -> None:
        if llm_decision_interval_timesteps < 1:
            raise ValueError("llm_decision_interval_timesteps must be at least 1")
        if maximum_consecutive_llm_failures < 1:
            raise ValueError("maximum_consecutive_llm_failures must be at least 1")
        if llm_failure_cooldown_intervals < 1:
            raise ValueError("llm_failure_cooldown_intervals must be at least 1")
        self.sensor_reader = sensor_reader
        self.actuator_writer = actuator_writer
        self.controller = controller
        self.safety_validator = safety_validator
        self.logger = logger
        self.metrics = metrics
        self.llm_decision_interval_timesteps = llm_decision_interval_timesteps
        self.maximum_consecutive_llm_failures = (
            maximum_consecutive_llm_failures
        )
        self.llm_failure_cooldown_intervals = llm_failure_cooldown_intervals
        self.startup_controller = startup_controller or RuleController()
        self.supervisor = supervisor
        self.supervisor_interval_hours = supervisor_interval_hours
        self.maximum_consecutive_supervisor_failures = (
            maximum_consecutive_supervisor_failures
        )
        self.supervisor_failure_cooldown_intervals = (
            supervisor_failure_cooldown_intervals
        )
        self.state = ControllerState(previous_action=initial_action)

    def begin_zone_timestep(self, sim_state: Any) -> None:
        """Apply the action computed during the previous zone timestep."""

        self.actuator_writer.apply(sim_state, self.state.previous_action)
        if self.metrics is not None:
            self.metrics.record_actuator_application(self.state.previous_action)

    def after_predictor_after_hvac_managers(self, sim_state: Any) -> None:
        """Refresh the proven node override after EnergyPlus managers."""

        self.actuator_writer.apply_after_hvac_managers(
            sim_state,
            self.state.previous_action,
        )

    def end_zone_timestep(self, sim_state: Any) -> None:
        """Read every timestep and decide only when the configured cadence is due."""

        current_timestep = self.state.timestep + 1
        building_state = self.sensor_reader.read(sim_state, current_timestep)
        if building_state is None:
            return
        if (
            self.supervisor is not None
            or getattr(self.controller, "uses_supervisor_policy", False)
        ):
            self._end_hybrid_timestep(building_state, current_timestep)
            return

        applied_action = self.state.previous_action
        is_llm_controller = bool(
            getattr(self.controller, "is_llm_controller", False)
        )
        llm_call_due = False
        llm_call_made = False
        action_reused = False
        fallback_used = False
        fallback_reason = ""
        llm_failure = False
        cooldown_active = self.state.cooldown_active
        cooldown_activated = False
        llm_response_time_seconds: float | None = None
        decision_source = "rule"

        if is_llm_controller and applied_action is None:
            requested_action = self.startup_controller.decide(
                building_state,
                self.state,
            )
            validation = self.safety_validator.validate(requested_action)
            decision_source = "startup_rule"
        elif is_llm_controller and self._llm_call_is_due(current_timestep):
            llm_call_due = True
            self.state.last_llm_decision_timestep = current_timestep
            if self.state.cooldown_active:
                cooldown_active = True
                fallback_used = True
                fallback_reason = (
                    "LLM cooldown active after consecutive failures"
                )
                requested_action = self.startup_controller.decide(
                    building_state,
                    self.state,
                )
                self.state.cooldown_intervals_remaining -= 1
                decision_source = "cooldown_rule"
            else:
                llm_call_made = True
                requested_action = self.controller.decide(
                    building_state,
                    self.state,
                )
                fallback_used = bool(
                    getattr(self.controller, "last_fallback_used", False)
                )
                fallback_reason = str(
                    getattr(self.controller, "last_failure_reason", "")
                )
                llm_failure = fallback_used and bool(fallback_reason)
                llm_response_time_seconds = getattr(
                    self.controller,
                    "last_response_time_seconds",
                    None,
                )
                if llm_failure:
                    self.state.consecutive_llm_failures += 1
                    if (
                        self.state.consecutive_llm_failures
                        >= self.maximum_consecutive_llm_failures
                    ):
                        self.state.cooldown_intervals_remaining = (
                            self.llm_failure_cooldown_intervals
                        )
                        self.state.cooldown_activations += 1
                        cooldown_active = True
                        cooldown_activated = True
                else:
                    self.state.consecutive_llm_failures = 0
                    self.state.last_fallback_reason = ""
                decision_source = "rule_fallback" if fallback_used else "llm"
            validation = self.safety_validator.validate(
                requested_action,
                previous_action=applied_action,
            )
        elif is_llm_controller:
            requested_action = applied_action
            if requested_action is None:
                raise RuntimeError("LLM action reuse requires a previous action")
            validation = ValidationResult(
                action=requested_action,
                status="reused previous validated action",
                corrected=False,
            )
            action_reused = True
            decision_source = "reused"
        else:
            requested_action = self._decide_with_optional_state(
                self.controller,
                building_state,
            )
            validation = self.safety_validator.validate(
                requested_action,
                previous_action=applied_action,
            )

        controller_type = getattr(
            self.controller,
            "controller_type",
            self.controller.__class__.__name__,
        )
        timesteps_since_last_llm_call = self._timesteps_since_last_llm_call(
            current_timestep
        )

        self.state.timestep = current_timestep
        self.state.last_requested_action = requested_action
        self.state.previous_action = validation.action
        self.state.last_strategy = validation.action.strategy
        self.state.previous_validation_status = validation.status
        if fallback_reason:
            self.state.last_fallback_reason = fallback_reason

        self.logger.write(
            building_state=building_state,
            requested_action=requested_action,
            validated_action=validation.action,
            applied_action=applied_action,
            validation_result=validation.status,
            controller_type=controller_type,
            llm_response_time_seconds=llm_response_time_seconds,
            fallback_used=fallback_used,
            safety_corrected=validation.corrected,
            llm_call_due=llm_call_due,
            llm_call_made=llm_call_made,
            action_reused=action_reused,
            decision_interval_timesteps=self.llm_decision_interval_timesteps,
            timesteps_since_last_llm_call=timesteps_since_last_llm_call,
            decision_source=decision_source,
            consecutive_llm_failures=self.state.consecutive_llm_failures,
            cooldown_active=cooldown_active,
            cooldown_intervals_remaining=(
                self.state.cooldown_intervals_remaining
            ),
            fallback_reason=fallback_reason,
        )

        if self.metrics is not None:
            self.metrics.record_timestep(
                building_state=building_state,
                decision_made=not action_reused,
                safety_corrected=validation.corrected,
                llm_call_made=llm_call_made,
                llm_failure=llm_failure,
                fallback_used=fallback_used,
                action_reused=action_reused,
                controller_type=controller_type,
                llm_response_time_seconds=llm_response_time_seconds,
                cooldown_activated=cooldown_activated,
            )

        self.state.append_building_state(building_state)

        print(
            f"{building_state.sim_time} | "
            f"Indoor={building_state.zone_temperature:.3f} C | "
            f"Controller={controller_type} | Source={decision_source} | "
            f"Strategy={validation.action.strategy} | "
            "SupplyAirSetpoint="
            f"{validation.action.supply_air_temperature_setpoint:.1f} C | "
            f"Validation={validation.status}"
        )

    def _end_hybrid_timestep(
        self,
        building_state: Any,
        current_timestep: int,
    ) -> None:
        """Update policy when due, then run deterministic physical control."""

        duration_hours = building_state.timestep_duration_hours or 0.0
        self.state.supervisor_policy_age_hours += duration_hours
        self.state.hours_since_supervisor_call += duration_hours
        current_policy = self.state.current_supervisor_policy
        supervisor_call_due = (
            self.supervisor is not None
            and self.state.hours_since_supervisor_call
            >= min(
                self.supervisor_interval_hours,
                float(current_policy.policy_duration_hours),
            )
            - 1e-9
        )
        supervisor_called = False
        supervisor_fallback_used = False
        supervisor_failure_reason = ""
        supervisor_cooldown_active = (
            self.state.supervisor_cooldown_remaining > 0
        )
        supervisor_cooldown_activated = False
        policy_changed = False
        policy_safety_corrected = False
        parser_failure = False
        timeout = False
        used_default_policy = False
        candidate_metadata: dict[str, Any] = {}
        uses_candidate_ranking = bool(
            self.supervisor is not None
            and getattr(self.supervisor, "uses_candidate_ranking", False)
        )

        if self.supervisor is not None and not uses_candidate_ranking:
            grace = self.supervisor.policy_grace_period_hours
            if (
                self.state.supervisor_policy_age_hours
                > current_policy.policy_duration_hours + grace
                and current_policy != default_supervisor_policy()
            ):
                replacement = default_supervisor_policy()
                self.state.previous_supervisor_policy = current_policy
                self.state.current_supervisor_policy = replacement
                self.state.supervisor_policy_age_hours = 0.0
                self.state.supervisor_policy_created_timestep = current_timestep
                current_policy = replacement
                policy_changed = True
                used_default_policy = True

        if supervisor_call_due:
            self.state.last_supervisor_call_timestep = current_timestep
            self.state.hours_since_supervisor_call = 0.0
            if (
                self.state.supervisor_cooldown_remaining > 0
                and not uses_candidate_ranking
            ):
                self.state.supervisor_cooldown_remaining -= 1
                supervisor_fallback_used = True
                supervisor_failure_reason = (
                    "supervisor cooldown active; validated policy retained"
                )
                self.state.supervisor_validation_status = (
                    "cooldown; previous policy retained"
                )
                if self.supervisor is None:
                    raise RuntimeError(
                        "Supervisor cooldown requires a supervisor"
                    )
                if (
                    self.state.supervisor_policy_age_hours
                    > current_policy.policy_duration_hours + grace
                ):
                    replacement = default_supervisor_policy()
                    policy_changed = replacement != current_policy
                    self.state.previous_supervisor_policy = current_policy
                    self.state.current_supervisor_policy = replacement
                    self.state.supervisor_policy_age_hours = 0.0
                    self.state.supervisor_policy_created_timestep = (
                        current_timestep
                    )
                    used_default_policy = True
            else:
                supervisor_called = True
                metrics_snapshot = (
                    self.metrics.snapshot()
                    if self.metrics is not None
                    else {}
                )
                if self.supervisor is None:
                    raise RuntimeError(
                        "Supervisor call due without a supervisor"
                    )
                result = self.supervisor.recommend(
                    building_state,
                    self.state,
                    metrics_snapshot,
                )
                supervisor_called = bool(
                    getattr(result, "llm_called", True)
                )
                self.state.supervisor_response_time_s = result.response_time_s
                self.state.supervisor_validation_status = (
                    result.validation.validation_status
                )
                supervisor_fallback_used = result.fallback_used
                supervisor_failure_reason = result.failure_reason
                policy_safety_corrected = result.validation.corrected
                parser_failure = result.parser_failure
                timeout = result.timeout
                used_default_policy = result.used_default_policy
                policy_changed = result.policy_changed
                candidate_set = getattr(result, "candidate_set", None)
                parsed_ranking = getattr(result, "parsed_ranking", None)
                selection = getattr(result, "selection", None)
                selected_candidate = getattr(
                    result,
                    "selected_candidate",
                    None,
                )
                if candidate_set is not None:
                    candidate_metadata = {
                        "candidate_generation_reason": (
                            candidate_set.generation_reason
                        ),
                        "candidate_count": len(candidate_set.candidates),
                        "candidate_ids": [
                            item.candidate_id
                            for item in candidate_set.candidates
                        ],
                        "candidate_policy_summaries": [
                            {
                                "candidate_id": item.candidate_id,
                                "mode": item.mode,
                                "thermal_priority": (
                                    item.thermal_priority.value
                                ),
                                "energy_priority": item.energy_priority.value,
                                "aggressiveness": (
                                    item.controller_aggressiveness.value
                                ),
                                "target_zone_temperature_c": (
                                    item.target_zone_temperature_c
                                ),
                            }
                            for item in candidate_set.candidates
                        ],
                        "deterministic_recommendation_id": (
                            candidate_set.deterministic_recommendation_id
                        ),
                        "deterministic_candidate_ranking": list(
                            candidate_set.deterministic_ranking
                        ),
                        "forced_single_candidate": getattr(
                            result,
                            "forced_single_candidate",
                            False,
                        ),
                        "llm_ranker_called": supervisor_called,
                        "llm_raw_ranking": (
                            list(parsed_ranking.ranking)
                            if parsed_ranking
                            else []
                        ),
                        "llm_selected_policy_id": (
                            parsed_ranking.selected_policy_id
                            if parsed_ranking
                            else ""
                        ),
                        "llm_confidence": (
                            parsed_ranking.confidence
                            if parsed_ranking
                            else None
                        ),
                        "llm_reason": (
                            parsed_ranking.reason if parsed_ranking else ""
                        ),
                        "ranking_validation_status": (
                            selection.validation_status
                            if selection
                            else result.failure_reason
                            or "forced single candidate"
                        ),
                        "confidence_gate_status": (
                            selection.confidence_gate_status
                            if selection
                            else "not_applicable"
                        ),
                        "final_selected_policy_id": (
                            selected_candidate.candidate_id
                            if selected_candidate
                            else ""
                        ),
                        "selected_policy_source": getattr(
                            result,
                            "selected_policy_source",
                            "",
                        ),
                        "low_confidence_fallback": bool(
                            selection
                            and selection.low_confidence_fallback
                        ),
                        "invalid_ranking_fallback": bool(
                            selection
                            and selection.invalid_ranking_fallback
                        )
                        or result.parser_failure,
                        "timeout_fallback": result.timeout,
                        "llm_response_time_s": result.response_time_s,
                        "llm_provider": self.supervisor.provider,
                        "llm_model": self.supervisor.model,
                        "llm_request_started": getattr(
                            result,
                            "llm_request_started",
                            supervisor_called,
                        ),
                        "llm_request_completed": getattr(
                            result,
                            "llm_request_completed",
                            supervisor_called and not result.fallback_used,
                        ),
                        "llm_retry_count": getattr(
                            result,
                            "llm_retry_count",
                            0,
                        ),
                        "llm_http_status_category": getattr(
                            result,
                            "llm_http_status_category",
                            "",
                        ),
                        "llm_failure_category": getattr(
                            result,
                            "llm_failure_category",
                            "",
                        ),
                        "deterministic_fallback_used": (
                            result.fallback_used
                        ),
                    }
                if result.fallback_used:
                    self.state.consecutive_supervisor_failures += 1
                    if (
                        not uses_candidate_ranking
                        and
                        self.state.consecutive_supervisor_failures
                        >= self.maximum_consecutive_supervisor_failures
                    ):
                        self.state.supervisor_cooldown_remaining = (
                            self.supervisor_failure_cooldown_intervals
                        )
                        self.state.supervisor_cooldown_activations += 1
                        supervisor_cooldown_active = True
                        supervisor_cooldown_activated = True
                else:
                    self.state.consecutive_supervisor_failures = 0
                if policy_changed:
                    self.state.previous_supervisor_policy = current_policy
                    self.state.current_supervisor_policy = result.policy
                    self.state.policy_change_count += 1
                if (
                    uses_candidate_ranking
                    or not result.fallback_used
                    or result.used_default_policy
                ):
                    self.state.supervisor_policy_age_hours = 0.0
                    self.state.supervisor_policy_created_timestep = (
                        current_timestep
                    )

        self.state.supervisor_fallback_used = supervisor_fallback_used
        self.state.supervisor_failure_reason = supervisor_failure_reason
        policy = self.state.current_supervisor_policy
        applied_action = self.state.previous_action
        requested_action = self.controller.decide(
            building_state,
            self.state,
            policy,
        )
        validation = self.safety_validator.validate(
            requested_action,
            previous_action=applied_action,
        )
        changed = (
            applied_action is None
            or validation.action.supply_air_temperature_setpoint
            != applied_action.supply_air_temperature_setpoint
        )
        self.state.physical_action_hold_intervals_elapsed = (
            0
            if changed
            else self.state.physical_action_hold_intervals_elapsed + 1
        )
        self.state.timestep = current_timestep
        self.state.last_requested_action = requested_action
        self.state.previous_action = validation.action
        self.state.last_strategy = validation.action.strategy
        self.state.previous_validation_status = validation.status

        self.logger.write(
            building_state=building_state,
            requested_action=requested_action,
            validated_action=validation.action,
            applied_action=applied_action,
            validation_result=validation.status,
            controller_type=getattr(
                self.controller,
                "controller_type",
                self.controller.__class__.__name__,
            ),
            fallback_used=False,
            safety_corrected=validation.corrected,
            action_reused=False,
            decision_interval_timesteps=1,
            decision_source="policy_rule",
            supervisor_enabled=self.supervisor is not None,
            supervisor_provider=(
                self.supervisor.provider if self.supervisor else "disabled"
            ),
            supervisor_model=(
                self.supervisor.model if self.supervisor else "none"
            ),
            supervisor_call_due=supervisor_call_due,
            supervisor_called=supervisor_called,
            supervisor_response_time_s=(
                self.state.supervisor_response_time_s
                if supervisor_called
                else None
            ),
            supervisor_fallback_used=supervisor_fallback_used,
            supervisor_failure_reason=supervisor_failure_reason,
            supervisor_cooldown_active=supervisor_cooldown_active,
            supervisor_policy_age_hours=(
                self.state.supervisor_policy_age_hours
            ),
            supervisor_policy_changed=policy_changed,
            supervisor_policy=policy,
            policy_safety_corrected=policy_safety_corrected,
            policy_validation_status=(
                self.state.supervisor_validation_status
            ),
            candidate_metadata=candidate_metadata,
        )
        if self.metrics is not None:
            self.metrics.record_timestep(
                building_state=building_state,
                decision_made=True,
                safety_corrected=validation.corrected,
                llm_call_made=False,
                llm_failure=False,
                fallback_used=False,
                action_reused=False,
                controller_type=getattr(
                    self.controller,
                    "controller_type",
                    self.controller.__class__.__name__,
                ),
                llm_response_time_seconds=None,
                supervisor_call_due=supervisor_call_due,
                supervisor_called=supervisor_called,
                supervisor_failure=supervisor_fallback_used,
                supervisor_parser_failure=parser_failure,
                supervisor_timeout=timeout,
                supervisor_fallback_used=supervisor_fallback_used,
                supervisor_validation_corrected=policy_safety_corrected,
                supervisor_policy_changed=policy_changed,
                supervisor_policy_reused=not policy_changed,
                default_policy_used=used_default_policy,
                supervisor_response_time_s=(
                    self.state.supervisor_response_time_s
                    if supervisor_called
                    else None
                ),
                supervisor_cooldown_active=supervisor_cooldown_active,
                supervisor_cooldown_activated=(
                    supervisor_cooldown_activated
                ),
                candidate_metadata=candidate_metadata,
            )
        self.state.append_building_state(building_state)
        print(
            f"{building_state.sim_time} | "
            f"Indoor={building_state.zone_temperature:.3f} C | "
            "Controller=PolicyAwareRuleController | "
            f"Policy={policy.strategy} | "
            f"Strategy={validation.action.strategy} | "
            "SupplyAirSetpoint="
            f"{validation.action.supply_air_temperature_setpoint:.1f} C | "
            f"Validation={validation.status}"
        )

    def _llm_call_is_due(self, current_timestep: int) -> bool:
        last_call = self.state.last_llm_decision_timestep
        if last_call is None:
            return current_timestep >= self.llm_decision_interval_timesteps
        return (
            current_timestep - last_call
            >= self.llm_decision_interval_timesteps
        )

    def _timesteps_since_last_llm_call(self, current_timestep: int) -> int:
        last_call = self.state.last_llm_decision_timestep
        if last_call is None:
            return current_timestep
        return current_timestep - last_call

    def _decide_with_optional_state(
        self,
        controller: Any,
        building_state: Any,
    ) -> ControlAction:
        if getattr(controller, "uses_controller_state", False):
            return controller.decide(building_state, self.state)
        return controller.decide(building_state)
