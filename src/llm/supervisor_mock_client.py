"""Deterministic mock responses for supervisory-policy validation."""

from __future__ import annotations

import time
from enum import Enum

from llm.client import LLMClient, LLMTimeoutError


class SupervisorMockMode(str, Enum):
    VALID_BALANCED = "valid_balanced"
    VALID_THERMAL_PRIORITY = "valid_thermal_priority"
    VALID_ENERGY_PRIORITY = "valid_energy_priority"
    UNSAFE_NUMERIC_VALUES = "unsafe_numeric_values"
    INVALID_ENUM = "invalid_enum"
    MALFORMED_JSON = "malformed_json"
    MISSING_FIELD = "missing_field"
    WRONG_TYPE = "wrong_type"
    DIRECT_ACTUATOR_FIELD_ATTEMPT = "direct_actuator_field_attempt"
    EMPTY_RESPONSE = "empty_response"
    EXCEPTION = "exception"
    TIMEOUT = "timeout"
    ALTERNATING_POLICY = "alternating_policy"
    VALID_THEN_EXCEPTION = "valid_then_exception"


class MockSupervisorLLMClient(LLMClient):
    """Return fixed policy responses without any model or network dependency."""

    def __init__(
        self,
        mode: SupervisorMockMode = SupervisorMockMode.VALID_BALANCED,
    ) -> None:
        self.mode = mode
        self.request_count = 0
        self.last_prompt: str | None = None
        self.last_response_duration_seconds: float | None = None

    def query(self, prompt: str) -> str:
        self.request_count += 1
        self.last_prompt = prompt
        start = time.perf_counter()
        try:
            return self._response()
        finally:
            self.last_response_duration_seconds = time.perf_counter() - start

    def _response(self) -> str:
        if self.mode == SupervisorMockMode.VALID_BALANCED:
            return _policy_json(
                "high", "medium", "normal", 32.0, 2, 6,
                "balanced_supervision",
                "Zone temperature and power trends support balanced policy.",
            )
        if self.mode == SupervisorMockMode.VALID_THERMAL_PRIORITY:
            return _policy_json(
                "high", "low", "aggressive", 31.0, 1, 4,
                "thermal_recovery",
                "Rising zone temperature requires earlier thermal response.",
            )
        if self.mode == SupervisorMockMode.VALID_ENERGY_PRIORITY:
            return _policy_json(
                "medium", "high", "conservative", 33.0, 4, 8,
                "energy_conservation",
                "Stable zone trend permits reduced cooling intensity.",
            )
        if self.mode == SupervisorMockMode.UNSAFE_NUMERIC_VALUES:
            return _policy_json(
                "high", "medium", "aggressive", 100.0, 99, 99,
                "unsafe_values",
                "Deliberately unsafe policy values for validator testing.",
            )
        if self.mode == SupervisorMockMode.INVALID_ENUM:
            return _policy_json(
                "urgent", "medium", "normal", 32.0, 2, 6,
                "invalid_enum",
                "Deliberately invalid enum for parser fallback testing.",
            )
        if self.mode == SupervisorMockMode.MALFORMED_JSON:
            return "thermal priority should be high"
        if self.mode == SupervisorMockMode.MISSING_FIELD:
            return (
                '{"thermal_priority":"high","energy_priority":"medium",'
                '"controller_aggressiveness":"normal",'
                '"target_zone_temperature_c":32.0,'
                '"minimum_action_hold_intervals":2,'
                '"policy_duration_hours":6,"strategy":"missing_reason"}'
            )
        if self.mode == SupervisorMockMode.WRONG_TYPE:
            return _policy_json(
                "high", "medium", "normal", "hot", 2, 6,
                "wrong_type",
                "Deliberately wrong target type for parser testing.",
            )
        if self.mode == SupervisorMockMode.DIRECT_ACTUATOR_FIELD_ATTEMPT:
            valid = _policy_json(
                "high", "medium", "normal", 32.0, 2, 6,
                "actuator_attempt",
                "Deliberately attempts to add a direct actuator field.",
            )
            return valid[:-1] + ',"supply_air_temperature_setpoint":22.0}'
        if self.mode == SupervisorMockMode.EMPTY_RESPONSE:
            return ""
        if self.mode == SupervisorMockMode.EXCEPTION:
            raise RuntimeError("Mock supervisor unavailable")
        if self.mode == SupervisorMockMode.TIMEOUT:
            raise LLMTimeoutError("Mock supervisor request timed out")
        if self.mode == SupervisorMockMode.VALID_THEN_EXCEPTION:
            if self.request_count == 1:
                return _policy_json(
                    "high", "low", "aggressive", 31.0, 1, 4,
                    "temporary_thermal",
                    "Temporary policy used to validate expiry fallback.",
                )
            raise RuntimeError("Mock supervisor failed after first policy")
        if self.request_count % 2:
            return _policy_json(
                "high", "low", "aggressive", 31.0, 1, 4,
                "alternating_thermal",
                "Alternating mock selects stronger thermal priority.",
            )
        return _policy_json(
            "medium", "high", "conservative", 33.0, 4, 8,
            "alternating_energy",
            "Alternating mock selects stronger energy priority.",
        )


def _policy_json(
    thermal_priority: object,
    energy_priority: object,
    aggressiveness: object,
    target: object,
    hold: object,
    duration: object,
    strategy: object,
    reason: object,
) -> str:
    import json

    return json.dumps(
        {
            "thermal_priority": thermal_priority,
            "energy_priority": energy_priority,
            "controller_aggressiveness": aggressiveness,
            "target_zone_temperature_c": target,
            "minimum_action_hold_intervals": hold,
            "policy_duration_hours": duration,
            "strategy": strategy,
            "reason": reason,
        },
        separators=(",", ":"),
    )
