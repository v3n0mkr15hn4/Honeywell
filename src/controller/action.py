"""Control action produced by a controller."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ControlAction:
    """One physical node-setpoint command plus decision metadata.

    ``supply_air_temperature_setpoint`` is the requested temperature setpoint
    for ``MAIN COOLING COIL 1 OUTLET NODE``. It is not a zone thermostat
    cooling setpoint.
    """

    supply_air_temperature_setpoint: float
    strategy: str
    reason: str

    @property
    def cooling_setpoint(self) -> float:
        """Deprecated read-only alias for pre-migration integrations."""

        return self.supply_air_temperature_setpoint
