from __future__ import annotations

import unittest
from types import SimpleNamespace

from src.agent.energyplus_agent import NvidiaNIMEnergyPlusModel


class _FakeCompletions:
    def __init__(self) -> None:
        self.arguments = None

    def create(self, **kwargs):
        self.arguments = kwargs
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                function=SimpleNamespace(
                                    name="validate_idf",
                                    arguments='{"idf_path":"model.idf"}',
                                )
                            )
                        ],
                    )
                )
            ]
        )


class NvidiaEnergyPlusAgentModelTests(unittest.TestCase):
    def test_request_uses_native_function_tools(self) -> None:
        completions = _FakeCompletions()
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=completions)
        )
        model = NvidiaNIMEnergyPlusModel(
            api_key="test-key",
            client=client,
        )

        result = model.complete(
            [
                {"role": "system", "content": "Return JSON."},
                {"role": "user", "content": "{}"},
            ],
            [
                {
                    "name": "validate_idf",
                    "description": "Validate an IDF.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"idf_path": {"type": "string"}},
                        "required": ["idf_path"],
                    },
                }
            ],
        )

        self.assertIn('"action": "call_tool"', result)
        self.assertEqual(
            completions.arguments["tools"][0]["function"]["name"],
            "validate_idf",
        )
        self.assertEqual(
            completions.arguments["tools"][-1]["function"]["name"],
            "finish_task",
        )
        self.assertNotIn("response_format", completions.arguments)
        self.assertEqual(completions.arguments["tool_choice"], "required")
        self.assertFalse(completions.arguments["parallel_tool_calls"])
        self.assertFalse(completions.arguments["stream"])
        self.assertEqual(completions.arguments["temperature"], 0)


if __name__ == "__main__":
    unittest.main()
