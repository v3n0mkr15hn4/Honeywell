"""LLM-backed controller with automatic rule-based fallback."""

from __future__ import annotations

import time

from controller.action import ControlAction
from controller.controller_state import ControllerState
from controller.output_parser import parse_response
from controller.prompt_builder import build_prompt
from controller.rule_controller import RuleController
from controller.state import BuildingState
from llm.client import LLMClient


class LLMController:
    """Decision maker that queries an LLM and falls back to rules on failure."""

    controller_type = "LLMController"
    uses_controller_state = True
    is_llm_controller = True

    def __init__(
        self,
        client: LLMClient,
        fallback_controller: RuleController | None = None,
    ) -> None:
        self.client = client
        self.fallback_controller = fallback_controller or RuleController()
        self.last_response_time_seconds: float | None = None
        self.last_fallback_used = False
        self.last_failure_reason = ""

    def decide(
        self,
        state: BuildingState,
        controller_state: ControllerState,
    ) -> ControlAction:
        """Return an LLM action, or a RuleController action if anything fails."""

        self.last_response_time_seconds = None
        self.last_fallback_used = False
        self.last_failure_reason = ""

        prompt = build_prompt(state, controller_state)
        start_time = time.perf_counter()

        try:
            response_text = self.client.query(prompt)
            self.last_response_time_seconds = time.perf_counter() - start_time
            return parse_response(response_text)
        except Exception as exc:  # The simulation must never stop on LLM failure.
            self.last_response_time_seconds = time.perf_counter() - start_time
            self.last_fallback_used = True
            self.last_failure_reason = str(exc)
            print(f"[Controller] LLM failed; using RuleController fallback: {exc}")
            return self.fallback_controller.decide(state, controller_state)
