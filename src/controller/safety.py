"""Safety validation for the physical supply-air node setpoint."""

from __future__ import annotations

from dataclasses import dataclass, replace

from controller.action import ControlAction


@dataclass(frozen=True)
class ValidationResult:
    """Validated action and a human-readable correction status."""

    action: ControlAction
    status: str
    corrected: bool

    @property
    def result(self) -> str:
        """Compatibility alias for earlier pipeline/report consumers."""

        return self.status


class SafetyValidator:
    """Enforce proven node limits and rate limits without throwing."""

    def __init__(
        self,
        minimum_supply_air_setpoint_c: float = 22.0,
        maximum_supply_air_setpoint_c: float = 25.0,
        maximum_change_per_decision_c: float = 1.0,
    ) -> None:
        self.minimum_supply_air_setpoint_c = minimum_supply_air_setpoint_c
        self.maximum_supply_air_setpoint_c = maximum_supply_air_setpoint_c
        self.maximum_change_per_decision_c = maximum_change_per_decision_c

    def validate(
        self,
        action: ControlAction,
        previous_action: ControlAction | None = None,
    ) -> ValidationResult:
        """Clamp and rate-limit a numeric action, returning corrections."""

        messages: list[str] = []
        setpoint = self._clamp(
            action.supply_air_temperature_setpoint,
            self.minimum_supply_air_setpoint_c,
            self.maximum_supply_air_setpoint_c,
            messages,
        )

        if previous_action is not None:
            setpoint = self._limit_step_change(
                setpoint,
                previous_action.supply_air_temperature_setpoint,
                messages,
            )

        validated_action = replace(
            action,
            supply_air_temperature_setpoint=setpoint,
        )
        status = "; ".join(messages) if messages else "valid"
        return ValidationResult(
            action=validated_action,
            status=status,
            corrected=bool(messages),
        )

    def _limit_step_change(
        self,
        requested: float,
        previous: float,
        messages: list[str],
    ) -> float:
        lower = previous - self.maximum_change_per_decision_c
        upper = previous + self.maximum_change_per_decision_c
        limited = min(max(requested, lower), upper)
        if limited != requested:
            messages.append(
                "supply-air temperature setpoint change limited to "
                f"{self.maximum_change_per_decision_c:.1f} C per decision "
                f"from {previous:.1f} C to {limited:.1f} C"
            )
        return limited

    @staticmethod
    def _clamp(
        value: float,
        lower: float,
        upper: float,
        messages: list[str],
    ) -> float:
        clamped = min(max(value, lower), upper)
        if clamped != value:
            messages.append(
                "supply-air temperature setpoint clamped from "
                f"{value:.1f} C to {clamped:.1f} C "
                f"within [{lower:.1f}, {upper:.1f}] C"
            )
        return clamped
