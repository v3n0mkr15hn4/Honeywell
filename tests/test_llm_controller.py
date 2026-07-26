from __future__ import annotations

import unittest

from controller.controller_state import ControllerState
from controller.llm_controller import LLMController
from llm.client import MockLLMClient, MockResponseMode
from test_support import make_state


class LLMControllerTests(unittest.TestCase):
    def test_valid_client_response_returns_supply_air_action(self) -> None:
        client = MockLLMClient(MockResponseMode.VALID)
        controller = LLMController(client=client)

        action = controller.decide(make_state(), ControllerState())

        self.assertEqual(action.supply_air_temperature_setpoint, 23.0)
        self.assertEqual(action.strategy, "moderate_cooling")
        self.assertFalse(controller.last_fallback_used)
        self.assertIsNotNone(controller.last_response_time_seconds)
        self.assertIn(
            "MAIN COOLING COIL 1 OUTLET NODE",
            client.last_prompt or "",
        )

    def test_invalid_responses_and_client_failures_invoke_fallback(self) -> None:
        modes = [
            MockResponseMode.MALFORMED_JSON,
            MockResponseMode.MISSING_FIELD,
            MockResponseMode.WRONG_TYPE,
            MockResponseMode.WRONG_FIELD,
            MockResponseMode.EMPTY_RESPONSE,
            MockResponseMode.EXCEPTION,
            MockResponseMode.TIMEOUT,
        ]

        for mode in modes:
            with self.subTest(mode=mode):
                controller = LLMController(client=MockLLMClient(mode))
                action = controller.decide(make_state(), ControllerState())

                self.assertEqual(
                    action.supply_air_temperature_setpoint,
                    22.0,
                )
                self.assertEqual(action.strategy, "increase_cooling")
                self.assertTrue(controller.last_fallback_used)
                self.assertTrue(controller.last_failure_reason)


if __name__ == "__main__":
    unittest.main()
