from __future__ import annotations

import unittest

from controller.action import ControlAction
from energyplus.actuators import ActuatorWriter
from energyplus.config import ActuatorControlMode


class FakeExchange:
    def __init__(self) -> None:
        self.handle_requests: list[tuple[str, str, str]] = []
        self.handle_values: dict[int, float] = {}
        self.writes: list[tuple[int, float]] = []

    def api_data_fully_ready(self, _state: object) -> bool:
        return True

    def get_actuator_handle(
        self,
        _state: object,
        component_type: str,
        control_type: str,
        key: str,
    ) -> int:
        self.handle_requests.append((component_type, control_type, key))
        return len(self.handle_requests)

    def set_actuator_value(
        self,
        _state: object,
        handle: int,
        value: float,
    ) -> None:
        self.handle_values[handle] = value
        self.writes.append((handle, value))

    def get_actuator_value(self, _state: object, handle: int) -> float:
        return self.handle_values[handle]

    def current_time(self, _state: object) -> float:
        return 1.0


class FakeApi:
    def __init__(self) -> None:
        self.exchange = FakeExchange()


class ActuatorWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.action = ControlAction(
            supply_air_temperature_setpoint=24.0,
            strategy="test",
            reason="test",
        )

    def test_supply_node_mode_uses_post_manager_callback_for_cooling(self) -> None:
        api = FakeApi()
        writer = ActuatorWriter(api, ActuatorControlMode.SUPPLY_NODE_SETPOINT)

        writer.apply(object(), self.action)
        self.assertEqual(api.exchange.writes, [(2, 18.0)])

        writer.apply_after_hvac_managers(object(), self.action)
        self.assertEqual(api.exchange.writes[-1], (1, 24.0))
        self.assertEqual(
            api.exchange.handle_requests[0],
            (
                "System Node Setpoint",
                "Temperature Setpoint",
                "MAIN COOLING COIL 1 OUTLET NODE",
            ),
        )

        writer.apply_after_hvac_managers(object(), self.action)
        self.assertEqual(len(api.exchange.handle_requests), 2)

    def test_schedule_mode_still_writes_both_values_at_begin_zone(self) -> None:
        api = FakeApi()
        writer = ActuatorWriter(api, ActuatorControlMode.SCHEDULE)

        writer.apply(object(), self.action)
        self.assertEqual(api.exchange.writes, [(1, 24.0), (2, 18.0)])

        writer.apply_after_hvac_managers(object(), self.action)
        self.assertEqual(api.exchange.writes, [(1, 24.0), (2, 18.0)])
        self.assertEqual(
            api.exchange.handle_requests[0],
            (
                "Schedule:Compact",
                "Schedule Value",
                "Cooling Return Air Setpoint Schedule",
            ),
        )


if __name__ == "__main__":
    unittest.main()
