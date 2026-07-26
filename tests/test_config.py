from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from energyplus.config import ControllerType, EnergyPlusConfig, LLMProvider
from controller.llm_policy_ranker import LLMPolicyRanker
from energyplus.runner import _build_supervisor, run_simulation


class EnergyPlusConfigTests(unittest.TestCase):
    def test_hourly_cadence_is_the_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = EnergyPlusConfig()

        self.assertEqual(config.llm_decision_interval_timesteps, 6)
        self.assertEqual(config.llm_provider, LLMProvider.MOCK)
        self.assertEqual(config.supervisor_interval_hours, 3.0)

    def test_real_boundary_can_be_selected_with_environment(self) -> None:
        with patch.dict(
            os.environ,
            {
                "CONTROLLER_TYPE": "llm",
                "LLM_PROVIDER": "ollama",
                "OLLAMA_MODEL": "installed:test",
            },
            clear=True,
        ):
            config = EnergyPlusConfig()

        self.assertEqual(config.controller_type, ControllerType.LLM)
        self.assertEqual(config.llm_provider, LLMProvider.OLLAMA)
        self.assertEqual(config.ollama_model, "installed:test")

    def test_direct_llm_runtime_mode_is_retired(self) -> None:
        config = EnergyPlusConfig(controller_type=ControllerType.LLM)
        with self.assertRaisesRegex(SystemExit, "Direct LLM actuator control"):
            run_simulation(config)

    def test_hybrid_runtime_builds_candidate_ranker(self) -> None:
        config = EnergyPlusConfig(
            controller_type=ControllerType.HYBRID_SUPERVISORY,
        )
        self.assertIsInstance(_build_supervisor(config), LLMPolicyRanker)

    def test_supervisor_interval_is_bounded_to_three_through_six_hours(
        self,
    ) -> None:
        for value in (2.9, 6.1):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    EnergyPlusConfig(supervisor_interval_hours=value)


if __name__ == "__main__":
    unittest.main()
