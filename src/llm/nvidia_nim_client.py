"""OpenAI-compatible NVIDIA NIM transport for candidate ranking."""

from __future__ import annotations

import os
import time
from typing import Any

import openai
from openai import OpenAI

from llm.client import LLMClient, LLMError, LLMTimeoutError


SYSTEM_MESSAGE = (
    "/no_think\n"
    "You are a constrained supervisory policy ranker. "
    "Rank only the supplied candidate IDs. Return exactly the requested "
    "JSON object. Do not create policies, actuator values, or additional "
    "fields. Do not include markdown or hidden reasoning."
)


class NvidiaNIMConfigurationError(LLMError):
    """Raised before transport when required NVIDIA configuration is absent."""

    category = "configuration_error"


class NvidiaNIMTransportError(LLMError):
    """Sanitized NVIDIA failure with a stable non-secret category."""

    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category


class NvidiaNIMTimeoutError(LLMTimeoutError):
    """Typed timeout recognized by the shared deterministic fallback."""

    category = "timeout"


class NvidiaNIMClient(LLMClient):
    """Generate one compact candidate-ranking response through NVIDIA NIM."""

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str = "https://integrate.api.nvidia.com/v1",
        timeout_s: float = 30.0,
        max_retries: int = 1,
        max_tokens: int = 256,
        temperature: float = 0.0,
        top_p: float = 1.0,
        openai_client: Any | None = None,
    ) -> None:
        secret = api_key or os.environ.get("NVIDIA_NIM_API_KEY")
        if not secret or not secret.strip():
            raise NvidiaNIMConfigurationError(
                "NVIDIA_NIM_API_KEY is not configured."
            )
        if max_retries not in (0, 1):
            raise ValueError("NVIDIA NIM max_retries must be 0 or 1")
        if not model.strip():
            raise ValueError("NVIDIA NIM model must not be empty")
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.top_p = top_p
        # Retries are handled below so actual retry count is observable.
        self.client = openai_client or OpenAI(
            base_url=self.base_url,
            api_key=secret,
            timeout=timeout_s,
            max_retries=0,
        )
        self.request_count = 0
        self.last_prompt: str | None = None
        self.last_response_duration_seconds: float | None = None
        self.last_retry_count = 0
        self.last_http_status_category = ""
        self.last_failure_category = ""
        self.last_request_started = False
        self.last_request_completed = False

    def query(self, prompt: str) -> str:
        if not isinstance(prompt, str) or not prompt.strip():
            raise NvidiaNIMConfigurationError(
                "NVIDIA NIM user prompt must not be empty."
            )
        self.request_count += 1
        self.last_prompt = prompt
        self.last_retry_count = 0
        self.last_http_status_category = ""
        self.last_failure_category = ""
        self.last_request_started = True
        self.last_request_completed = False
        started = time.perf_counter()
        try:
            for attempt in range(self.max_retries + 1):
                try:
                    completion = self.client.chat.completions.create(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": SYSTEM_MESSAGE},
                            {"role": "user", "content": prompt},
                        ],
                        temperature=self.temperature,
                        top_p=self.top_p,
                        max_tokens=self.max_tokens,
                        frequency_penalty=0,
                        presence_penalty=0,
                        stream=False,
                    )
                    content = self._extract_content(completion)
                    self.last_http_status_category = "2xx"
                    self.last_request_completed = True
                    return content
                except Exception as exc:
                    category, retryable, status = self._classify(exc)
                    self.last_failure_category = category
                    self.last_http_status_category = status
                    if retryable and attempt < self.max_retries:
                        self.last_retry_count += 1
                        time.sleep(0.2)
                        continue
                    raise self._sanitized_error(category) from None
            raise NvidiaNIMTransportError(
                "transport_error",
                "NVIDIA NIM request failed.",
            )
        finally:
            self.last_response_duration_seconds = (
                time.perf_counter() - started
            )

    @staticmethod
    def _extract_content(completion: Any) -> str:
        choices = getattr(completion, "choices", None)
        if not isinstance(choices, (list, tuple)) or not choices:
            raise NvidiaNIMTransportError(
                "empty_response",
                "NVIDIA NIM returned no completion choices.",
            )
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None)
        if not isinstance(content, str) or not content.strip():
            raise NvidiaNIMTransportError(
                "empty_response",
                "NVIDIA NIM returned empty completion content.",
            )
        return content.strip()

    @staticmethod
    def _classify(exc: Exception) -> tuple[str, bool, str]:
        if isinstance(exc, NvidiaNIMTransportError):
            return exc.category, False, ""
        if isinstance(exc, openai.AuthenticationError):
            return "authentication_error", False, "4xx"
        if isinstance(exc, openai.PermissionDeniedError):
            return "permission_error", False, "4xx"
        if isinstance(exc, openai.NotFoundError):
            return "model_unavailable", False, "4xx"
        if isinstance(exc, openai.RateLimitError):
            return "rate_limit_error", True, "429"
        if isinstance(exc, openai.APITimeoutError):
            return "timeout", True, ""
        if isinstance(exc, openai.APIConnectionError):
            return "transport_error", True, ""
        if isinstance(exc, openai.InternalServerError):
            return "server_error", True, "5xx"
        if isinstance(exc, openai.APIStatusError):
            status = getattr(exc, "status_code", 0)
            if status >= 500:
                return "server_error", True, "5xx"
            return "transport_error", False, "4xx"
        return "transport_error", False, ""

    @staticmethod
    def _sanitized_error(category: str) -> LLMError:
        messages = {
            "authentication_error": "NVIDIA NIM authentication failed.",
            "permission_error": "NVIDIA NIM permission was denied.",
            "model_unavailable": "The configured NVIDIA NIM model is unavailable.",
            "rate_limit_error": "NVIDIA NIM rate limit prevented completion.",
            "transport_error": "NVIDIA NIM network transport failed.",
            "server_error": "NVIDIA NIM server failed to complete the request.",
            "empty_response": "NVIDIA NIM returned an empty response.",
        }
        if category == "timeout":
            return NvidiaNIMTimeoutError("NVIDIA NIM request timed out.")
        return NvidiaNIMTransportError(
            category,
            messages.get(category, "NVIDIA NIM request failed."),
        )
