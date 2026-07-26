from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import openai

from llm.nvidia_nim_client import (
    NvidiaNIMClient,
    NvidiaNIMConfigurationError,
    NvidiaNIMTimeoutError,
    NvidiaNIMTransportError,
    SYSTEM_MESSAGE,
)


def completion(content: str | None = '{"ranking":["P1"]}') -> object:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(message=SimpleNamespace(content=content))
        ]
    )


def status_error(error_type: type[Exception], status: int) -> Exception:
    request = httpx.Request("POST", "https://example.invalid")
    response = httpx.Response(status, request=request)
    return error_type(
        "provider response detail must not leak",
        response=response,
        body={},
    )


class NvidiaNIMClientTests(unittest.TestCase):
    def mocked_client(self) -> MagicMock:
        client = MagicMock()
        client.chat.completions.create.return_value = completion()
        return client

    def test_constructor_uses_expected_base_url_and_explicit_key(self) -> None:
        with patch("llm.nvidia_nim_client.OpenAI") as constructor:
            NvidiaNIMClient(
                "nvidia/model",
                api_key="explicit-test-key",
            )
        kwargs = constructor.call_args.kwargs
        self.assertEqual(
            kwargs["base_url"],
            "https://integrate.api.nvidia.com/v1",
        )
        self.assertEqual(kwargs["api_key"], "explicit-test-key")
        self.assertEqual(kwargs["max_retries"], 0)

    def test_environment_key_loading_and_missing_key(self) -> None:
        with patch.dict(
            os.environ,
            {"NVIDIA_NIM_API_KEY": "environment-test-key"},
            clear=True,
        ):
            with patch("llm.nvidia_nim_client.OpenAI") as constructor:
                NvidiaNIMClient("nvidia/model")
            self.assertEqual(
                constructor.call_args.kwargs["api_key"],
                "environment-test-key",
            )
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                NvidiaNIMConfigurationError,
                "NVIDIA_NIM_API_KEY is not configured",
            ):
                NvidiaNIMClient("nvidia/model")

    def test_request_is_compact_deterministic_chat_completion(self) -> None:
        transport = self.mocked_client()
        client = NvidiaNIMClient(
            "nvidia/llama-3.3-nemotron-super-49b-v1.5",
            api_key="test-key",
            openai_client=transport,
        )
        result = client.query("Candidate IDs: P1")
        kwargs = transport.chat.completions.create.call_args.kwargs
        self.assertEqual(
            kwargs["model"],
            "nvidia/llama-3.3-nemotron-super-49b-v1.5",
        )
        self.assertEqual(kwargs["temperature"], 0.0)
        self.assertEqual(kwargs["top_p"], 1.0)
        self.assertEqual(kwargs["max_tokens"], 256)
        self.assertFalse(kwargs["stream"])
        self.assertTrue(SYSTEM_MESSAGE.startswith("/no_think\n"))
        self.assertEqual(kwargs["messages"][0]["content"], SYSTEM_MESSAGE)
        self.assertEqual(kwargs["messages"][1]["content"], "Candidate IDs: P1")
        self.assertEqual(result, '{"ranking":["P1"]}')

    def test_empty_choices_and_missing_content_are_sanitized(self) -> None:
        for bad in (
            SimpleNamespace(choices=[]),
            completion(None),
            completion(""),
        ):
            with self.subTest(bad=bad):
                transport = self.mocked_client()
                transport.chat.completions.create.return_value = bad
                client = NvidiaNIMClient(
                    "nvidia/model",
                    api_key="test-key",
                    openai_client=transport,
                )
                with self.assertRaisesRegex(
                    NvidiaNIMTransportError,
                    "empty",
                ):
                    client.query("prompt")
                self.assertEqual(
                    client.last_failure_category,
                    "empty_response",
                )

    def test_timeout_network_rate_limit_and_server_retry_once(self) -> None:
        request = httpx.Request("POST", "https://example.invalid")
        failures = (
            (openai.APITimeoutError(request=request), NvidiaNIMTimeoutError),
            (
                openai.APIConnectionError(
                    message="secret connection detail",
                    request=request,
                ),
                NvidiaNIMTransportError,
            ),
            (
                status_error(openai.RateLimitError, 429),
                NvidiaNIMTransportError,
            ),
            (
                status_error(openai.InternalServerError, 500),
                NvidiaNIMTransportError,
            ),
        )
        for error, expected in failures:
            with self.subTest(error=type(error).__name__):
                transport = self.mocked_client()
                transport.chat.completions.create.side_effect = [
                    error,
                    error,
                ]
                client = NvidiaNIMClient(
                    "nvidia/model",
                    api_key="test-key",
                    max_retries=1,
                    openai_client=transport,
                )
                with self.assertRaises(expected) as raised:
                    client.query("prompt")
                self.assertEqual(
                    transport.chat.completions.create.call_count,
                    2,
                )
                self.assertEqual(client.last_retry_count, 1)
                self.assertNotIn("secret", str(raised.exception).lower())
                self.assertNotIn("test-key", str(raised.exception))

    def test_authentication_and_permission_are_not_retried(self) -> None:
        for error in (
            status_error(openai.AuthenticationError, 401),
            status_error(openai.PermissionDeniedError, 403),
            status_error(openai.NotFoundError, 404),
        ):
            with self.subTest(error=type(error).__name__):
                transport = self.mocked_client()
                transport.chat.completions.create.side_effect = error
                client = NvidiaNIMClient(
                    "nvidia/model",
                    api_key="credential-test-value",
                    openai_client=transport,
                )
                with self.assertRaises(NvidiaNIMTransportError) as raised:
                    client.query("prompt")
                self.assertEqual(
                    transport.chat.completions.create.call_count,
                    1,
                )
                self.assertEqual(client.last_retry_count, 0)
                self.assertNotIn(
                    "credential-test-value",
                    str(raised.exception),
                )

    def test_empty_user_prompt_is_rejected_before_transport(self) -> None:
        transport = self.mocked_client()
        client = NvidiaNIMClient(
            "nvidia/model",
            api_key="test-key",
            openai_client=transport,
        )
        with self.assertRaises(NvidiaNIMConfigurationError):
            client.query("")
        transport.chat.completions.create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
