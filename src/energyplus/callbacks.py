"""Runtime API callback functions for the closed-loop controller."""

from __future__ import annotations

from typing import Any

from controller.pipeline import ControlPipeline


class EnergyPlusCallbacks:
    """Small adapter between EnergyPlus callbacks and the control pipeline."""

    def __init__(self, api: Any, pipeline: ControlPipeline) -> None:
        self.api = api
        self.pipeline = pipeline

    def begin_zone_timestep_callback(self, sim_state: Any) -> None:
        """Apply the previously computed control action."""

        if self.api.exchange.warmup_flag(sim_state):
            return

        self.pipeline.begin_zone_timestep(sim_state)

    def end_zone_timestep_callback(self, sim_state: Any) -> None:
        """Read sensors and compute the action for the next timestep."""

        self.pipeline.end_zone_timestep(sim_state)

    def after_predictor_after_hvac_managers_callback(
        self,
        sim_state: Any,
    ) -> None:
        """Apply the proven DX-coil node override after setpoint managers."""

        if self.api.exchange.warmup_flag(sim_state):
            return

        self.pipeline.after_predictor_after_hvac_managers(sim_state)
