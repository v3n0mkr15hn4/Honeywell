from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from controller.llm_policy_ranker import LLMPolicyRanker
from energyplus.config import ControllerType, EnergyPlusConfig, LLMProvider
from energyplus.runner import _build_supervisor
from llm.candidate_ranker_mock_client import MockCandidateRankerLLMClient
from llm.client import OllamaLLMClient
from llm.nvidia_nim_client import NvidiaNIMClient


class NvidiaProviderSelectionTests(unittest.TestCase):
    def config(self, provider: LLMProvider) -> EnergyPlusConfig:
        return EnergyPlusConfig(
            controller_type=ControllerType.HYBRID_SUPERVISORY,
            llm_provider=provider,
        )

    def test_mock_ollama_and_nvidia_clients_are_selected_explicitly(self) -> None:
        mock_ranker = _build_supervisor(self.config(LLMProvider.MOCK))
        self.assertIsInstance(mock_ranker, LLMPolicyRanker)
        self.assertIsInstance(
            mock_ranker.client,
            MockCandidateRankerLLMClient,
        )

        ollama_ranker = _build_supervisor(self.config(LLMProvider.OLLAMA))
        self.assertIsInstance(ollama_ranker.client, OllamaLLMClient)

        with patch.dict(
            os.environ,
            {"NVIDIA_NIM_API_KEY": "provider-test-key"},
            clear=False,
        ):
            with patch("llm.nvidia_nim_client.OpenAI"):
                nvidia_ranker = _build_supervisor(
                    self.config(LLMProvider.NVIDIA_NIM)
                )
        self.assertIsInstance(nvidia_ranker.client, NvidiaNIMClient)
        self.assertEqual(nvidia_ranker.provider, "nvidia_nim")

    def test_unknown_provider_is_rejected(self) -> None:
        with patch.dict(
            os.environ,
            {"LLM_PROVIDER": "unknown-provider"},
            clear=True,
        ):
            with self.assertRaises(ValueError):
                EnergyPlusConfig()


if __name__ == "__main__":
    unittest.main()
