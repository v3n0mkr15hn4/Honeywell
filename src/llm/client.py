"""Replaceable transport clients for mocked and local LLM responses."""

from __future__ import annotations

import http.client
import json
import socket
import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any
from urllib.parse import urlparse


class LLMError(RuntimeError):
    """Base class for recoverable LLM transport failures."""


class LLMConnectionError(LLMError):
    """Raised when the configured LLM endpoint cannot be reached."""


class LLMTimeoutError(LLMError):
    """Raised when connection or response delivery exceeds its timeout."""


class LLMEmptyResponseError(LLMError):
    """Raised when a successful transport returns no generated text."""


class LLMResponseFormatError(LLMError):
    """Raised when the transport response does not match the Ollama envelope."""


class MockResponseMode(str, Enum):
    """Deterministic mock behaviors for validating the LLM pipeline."""

    VALID = "valid"
    UNSAFE = "unsafe"
    UNSAFE_LOW = "unsafe_low"
    UNSAFE_HIGH = "unsafe_high"
    WRONG_FIELD = "wrong_field"
    MALFORMED_JSON = "malformed_json"
    MISSING_FIELD = "missing_field"
    WRONG_TYPE = "wrong_type"
    EMPTY_RESPONSE = "empty_response"
    EXCEPTION = "exception"
    TIMEOUT = "timeout"
    ALTERNATING = "alternating"
    COOLING_22 = "cooling_22"
    COOLING_30 = "cooling_30"


class LLMClient(ABC):
    """Provider-neutral interface consumed by ``LLMController``."""

    last_response_duration_seconds: float | None = None

    @abstractmethod
    def query(self, prompt: str) -> str:
        """Return only model-generated response text."""


class MockLLMClient(LLMClient):
    """Deterministic test client retained independently of real transports."""

    def __init__(self, mock_mode: MockResponseMode = MockResponseMode.VALID) -> None:
        self.mock_mode = mock_mode
        self.last_prompt: str | None = None
        self.request_count = 0
        self.last_response_duration_seconds: float | None = None

    def query(self, prompt: str) -> str:
        """Return a deterministic response for the configured test mode."""

        self.last_prompt = prompt
        self.request_count += 1
        start_time = time.perf_counter()
        try:
            return self._build_response()
        finally:
            self.last_response_duration_seconds = time.perf_counter() - start_time

    def _build_response(self) -> str:
        if self.mock_mode == MockResponseMode.VALID:
            return (
                '{"supply_air_temperature_setpoint": 23.0, '
                '"strategy": "moderate_cooling", '
                '"reason": "Zone temperature is above target but stable."}'
            )

        if self.mock_mode in {
            MockResponseMode.UNSAFE,
            MockResponseMode.UNSAFE_LOW,
        }:
            return (
                '{"supply_air_temperature_setpoint": 18.0, '
                '"strategy": "maximum_cooling", '
                '"reason": "Deliberately unsafe low output for validator testing."}'
            )

        if self.mock_mode == MockResponseMode.UNSAFE_HIGH:
            return (
                '{"supply_air_temperature_setpoint": 30.0, '
                '"strategy": "reduce_cooling", '
                '"reason": "Deliberately unsafe high output for validator testing."}'
            )

        if self.mock_mode == MockResponseMode.COOLING_22:
            return (
                '{"supply_air_temperature_setpoint": 22.0, '
                '"strategy": "ab_cooling_22", '
                '"reason": "Fixed cold supply-air target for physical A/B testing."}'
            )

        if self.mock_mode == MockResponseMode.COOLING_30:
            return (
                '{"supply_air_temperature_setpoint": 30.0, '
                '"strategy": "ab_cooling_30", '
                '"reason": "Fixed unsafe-high target for validator testing."}'
            )

        if self.mock_mode == MockResponseMode.MALFORMED_JSON:
            return "cooling should be 25"

        if self.mock_mode == MockResponseMode.MISSING_FIELD:
            return (
                '{"strategy": "missing_field_test", '
                '"reason": "Supply-air setpoint is deliberately missing."}'
            )

        if self.mock_mode == MockResponseMode.WRONG_TYPE:
            return (
                '{"supply_air_temperature_setpoint": "cold", '
                '"strategy": "wrong_type_test", '
                '"reason": "Supply-air setpoint deliberately has the wrong type."}'
            )

        if self.mock_mode == MockResponseMode.WRONG_FIELD:
            return (
                '{"cooling_setpoint": 23.0, '
                '"strategy": "legacy_field_test", '
                '"reason": "Testing rejection of the old field."}'
            )

        if self.mock_mode == MockResponseMode.EMPTY_RESPONSE:
            return ""

        if self.mock_mode == MockResponseMode.EXCEPTION:
            raise RuntimeError("Mock LLM unavailable")

        if self.mock_mode == MockResponseMode.TIMEOUT:
            raise TimeoutError("Mock LLM request timed out")

        if self.request_count % 2 == 1:
            return (
                '{"supply_air_temperature_setpoint": 22.0, '
                '"strategy": "alternating_low", '
                '"reason": "Testing actuator change counting."}'
            )

        return (
            '{"supply_air_temperature_setpoint": 25.0, '
            '"strategy": "alternating_high", '
            '"reason": "Testing actuator change counting."}'
        )


class OllamaLLMClient(LLMClient):
    """Non-streaming transport for Ollama's local ``/api/generate`` endpoint."""

    RESPONSE_SCHEMA = {
        "type": "object",
        "properties": {
            "supply_air_temperature_setpoint": {"type": "number"},
            "strategy": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": [
            "supply_air_temperature_setpoint",
            "strategy",
            "reason",
        ],
        "additionalProperties": False,
    }

    def __init__(
        self,
        model: str,
        base_url: str = "http://localhost:11434",
        connect_timeout_s: float = 3.0,
        response_timeout_s: float = 20.0,
        temperature: float = 0.0,
        stream: bool = False,
        json_mode: bool = True,
        keep_alive: str = "5m",
        seed: int = 42,
        max_output_tokens: int = 128,
        response_schema: dict[str, Any] | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError("Ollama model must not be empty")
        if stream:
            raise ValueError("OllamaLLMClient requires non-streaming responses")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.connect_timeout_s = connect_timeout_s
        self.response_timeout_s = response_timeout_s
        self.temperature = temperature
        self.stream = stream
        self.json_mode = json_mode
        self.keep_alive = keep_alive
        self.seed = seed
        self.max_output_tokens = max_output_tokens
        self.response_schema = response_schema or self.RESPONSE_SCHEMA
        self.request_count = 0
        self.last_prompt: str | None = None
        self.last_response_duration_seconds: float | None = None
        self.last_transport_metadata: dict[str, Any] = {}

    def query(self, prompt: str) -> str:
        """Send one deterministic request and return its generated text."""

        self.request_count += 1
        self.last_prompt = prompt
        self.last_transport_metadata = {}
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "options": {
                "temperature": self.temperature,
                "seed": self.seed,
                "num_predict": self.max_output_tokens,
            },
            "keep_alive": self.keep_alive,
        }
        if self.json_mode:
            payload["format"] = self.response_schema

        start_time = time.perf_counter()
        try:
            envelope = self._post_json("/api/generate", payload)
            self._validate_envelope(envelope)
            response_text = envelope["response"]
            if not response_text.strip():
                raise LLMEmptyResponseError(
                    "Ollama returned an empty generated response"
                )
            self.last_transport_metadata = {
                key: envelope.get(key)
                for key in (
                    "model",
                    "done",
                    "done_reason",
                    "total_duration",
                    "load_duration",
                    "prompt_eval_count",
                    "prompt_eval_duration",
                    "eval_count",
                    "eval_duration",
                )
            }
            return response_text
        finally:
            self.last_response_duration_seconds = time.perf_counter() - start_time

    def _post_json(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise LLMConnectionError(
                f"Invalid Ollama base URL: {self.base_url}"
            )

        connection_type = (
            http.client.HTTPSConnection
            if parsed.scheme == "https"
            else http.client.HTTPConnection
        )
        connection = connection_type(
            parsed.hostname,
            parsed.port,
            timeout=self.connect_timeout_s,
        )
        stage = "connect"
        try:
            connection.connect()
            if connection.sock is not None:
                connection.sock.settimeout(self.response_timeout_s)
            stage = "response"
            path_prefix = parsed.path.rstrip("/")
            body = json.dumps(payload).encode("utf-8")
            connection.request(
                "POST",
                f"{path_prefix}{endpoint}",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            response_body = response.read()
        except (socket.timeout, TimeoutError) as exc:
            raise LLMTimeoutError(
                f"Ollama {stage} timed out after "
                f"{self.connect_timeout_s if stage == 'connect' else self.response_timeout_s:.1f}s"
            ) from exc
        except (ConnectionError, OSError, http.client.HTTPException) as exc:
            raise LLMConnectionError(
                f"Could not communicate with Ollama at {self.base_url}: {exc}"
            ) from exc
        finally:
            connection.close()

        if response.status < 200 or response.status >= 300:
            detail = response_body.decode("utf-8", errors="replace").strip()
            raise LLMConnectionError(
                f"Ollama returned HTTP {response.status}: {detail[:300]}"
            )

        try:
            decoded = json.loads(response_body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LLMResponseFormatError(
                "Ollama response envelope is not valid JSON"
            ) from exc
        if not isinstance(decoded, dict):
            raise LLMResponseFormatError(
                "Ollama response envelope must be a JSON object"
            )
        return decoded

    @staticmethod
    def _validate_envelope(envelope: dict[str, Any]) -> None:
        if envelope.get("done") is not True:
            raise LLMResponseFormatError(
                "Ollama response did not report done=true"
            )
        if not isinstance(envelope.get("response"), str):
            raise LLMResponseFormatError(
                "Ollama response is missing the generated response text"
            )
