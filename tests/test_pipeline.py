from __future__ import annotations

import unittest

from controller.llm_controller import LLMController
from controller.pipeline import ControlPipeline
from controller.safety import SafetyValidator
from llm.client import LLMClient, MockLLMClient, MockResponseMode
from test_support import make_state


class FakeSensorReader:
    def __init__(self, states: list[object]) -> None:
        self.states = list(states)

    def read(self, _sim_state: object, _timestep: int):
        if not self.states:
            return None
        return self.states.pop(0)


class FakeActuatorWriter:
    def __init__(self) -> None:
        self.begin_actions = []
        self.post_manager_actions = []

    def apply(self, _sim_state: object, action) -> None:
        self.begin_actions.append(action)

    def apply_after_hvac_managers(self, _sim_state: object, action) -> None:
        self.post_manager_actions.append(action)


class FakeLogger:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    def write(self, **kwargs: object) -> None:
        self.rows.append(kwargs)


class ControlPipelineTests(unittest.TestCase):
    def build_pipeline(
        self,
        mode: MockResponseMode = MockResponseMode.VALID,
        states: int = 12,
        interval: int = 6,
    ):
        client = MockLLMClient(mode)
        writer = FakeActuatorWriter()
        logger = FakeLogger()
        pipeline = ControlPipeline(
            sensor_reader=FakeSensorReader(
                [
                    make_state(timestep=index + 1)
                    for index in range(states)
                ]
            ),
            actuator_writer=writer,
            controller=LLMController(client),
            safety_validator=SafetyValidator(),
            logger=logger,
            llm_decision_interval_timesteps=interval,
        )
        return pipeline, client, writer, logger

    def test_llm_is_called_only_at_configured_intervals(self) -> None:
        pipeline, client, _, logger = self.build_pipeline()

        for _ in range(12):
            pipeline.end_zone_timestep(object())

        self.assertEqual(client.request_count, 2)
        due_rows = [
            row for row in logger.rows if row["llm_call_due"] is True
        ]
        self.assertEqual(len(due_rows), 2)
        self.assertEqual([row["building_state"].timestep for row in due_rows], [6, 12])
        self.assertEqual(
            sum(row["action_reused"] is True for row in logger.rows),
            9,
        )
        self.assertEqual(len(pipeline.state.history), 12)

    def test_startup_rule_action_is_reused_before_first_llm_call(self) -> None:
        pipeline, client, _, logger = self.build_pipeline(states=3)

        for _ in range(3):
            pipeline.end_zone_timestep(object())

        self.assertEqual(client.request_count, 0)
        self.assertEqual(logger.rows[0]["decision_source"], "startup_rule")
        self.assertEqual(logger.rows[1]["decision_source"], "reused")
        self.assertEqual(
            logger.rows[0][
                "validated_action"
            ].supply_air_temperature_setpoint,
            22.0,
        )

    def test_no_llm_call_when_sensor_reader_suppresses_warmup(self) -> None:
        client = MockLLMClient(MockResponseMode.VALID)
        pipeline = ControlPipeline(
            sensor_reader=FakeSensorReader([None]),
            actuator_writer=FakeActuatorWriter(),
            controller=LLMController(client),
            safety_validator=SafetyValidator(),
            logger=FakeLogger(),
            llm_decision_interval_timesteps=1,
        )

        pipeline.end_zone_timestep(object())

        self.assertEqual(client.request_count, 0)
        self.assertEqual(pipeline.state.timestep, 0)

    def test_failure_uses_validated_rule_fallback(self) -> None:
        pipeline, client, _, logger = self.build_pipeline(
            mode=MockResponseMode.EXCEPTION,
            states=2,
            interval=1,
        )

        pipeline.end_zone_timestep(object())
        pipeline.end_zone_timestep(object())

        self.assertEqual(client.request_count, 1)
        self.assertEqual(logger.rows[1]["decision_source"], "rule_fallback")
        self.assertTrue(logger.rows[1]["fallback_used"])
        self.assertEqual(pipeline.state.consecutive_llm_failures, 1)
        self.assertGreaterEqual(
            pipeline.state.previous_action.supply_air_temperature_setpoint,
            22.0,
        )

    def test_three_failures_enter_cooldown_then_resume(self) -> None:
        class FlakyClient(LLMClient):
            def __init__(self) -> None:
                self.request_count = 0

            def query(self, _prompt: str) -> str:
                self.request_count += 1
                if self.request_count <= 3:
                    raise RuntimeError("scripted failure")
                return (
                    '{"supply_air_temperature_setpoint": 23.0, '
                    '"strategy": "recovered", "reason": "Transport recovered."}'
                )

        client = FlakyClient()
        logger = FakeLogger()
        pipeline = ControlPipeline(
            sensor_reader=FakeSensorReader(
                [make_state(timestep=index + 1) for index in range(8)]
            ),
            actuator_writer=FakeActuatorWriter(),
            controller=LLMController(client),
            safety_validator=SafetyValidator(),
            logger=logger,
            llm_decision_interval_timesteps=1,
            maximum_consecutive_llm_failures=3,
            llm_failure_cooldown_intervals=3,
        )

        for _ in range(8):
            pipeline.end_zone_timestep(object())

        self.assertEqual(client.request_count, 4)
        self.assertEqual(
            [row["decision_source"] for row in logger.rows],
            [
                "startup_rule",
                "rule_fallback",
                "rule_fallback",
                "rule_fallback",
                "cooldown_rule",
                "cooldown_rule",
                "cooldown_rule",
                "llm",
            ],
        )
        self.assertEqual(pipeline.state.cooldown_activations, 1)
        self.assertEqual(pipeline.state.cooldown_intervals_remaining, 0)
        self.assertEqual(pipeline.state.consecutive_llm_failures, 0)
        self.assertEqual(logger.rows[4]["llm_call_made"], False)
        self.assertIn("cooldown", logger.rows[4]["fallback_reason"].lower())

    def test_action_is_applied_only_after_end_timestep_decision(self) -> None:
        pipeline, _, writer, _ = self.build_pipeline(states=1)

        pipeline.end_zone_timestep(object())
        self.assertEqual(writer.begin_actions, [])

        pipeline.begin_zone_timestep(object())
        pipeline.after_predictor_after_hvac_managers(object())

        self.assertEqual(
            writer.begin_actions[0].supply_air_temperature_setpoint,
            22.0,
        )
        self.assertEqual(
            writer.post_manager_actions[0].supply_air_temperature_setpoint,
            22.0,
        )


if __name__ == "__main__":
    unittest.main()
