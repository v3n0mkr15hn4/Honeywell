"""Deterministic feature extraction for candidate-policy generation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from controller.state import BuildingState
from controller.state_summary import StateSummary
from controller.supervisor_policy import SupervisorPolicy


@dataclass(frozen=True)
class FeatureThresholds:
    stable_change: float = 0.5
    strong_temperature_change_c: float = 2.0
    strong_power_change_w: float = 20_000.0
    strong_outdoor_change_c: float = 5.0
    above_target_c: float = 0.5
    far_above_target_c: float = 2.0
    high_facility_power_w: float = 100_000.0
    high_hvac_power_w: float = 20_000.0
    minimum_history_hours: float = 1.0


class DeterministicFeatureExtractor:
    """Convert measured history into explicit, testable classifications."""

    def __init__(self, thresholds: FeatureThresholds | None = None) -> None:
        self.thresholds = thresholds or FeatureThresholds()

    def extract(
        self,
        current_state: BuildingState,
        history: Sequence[BuildingState],
        current_policy: SupervisorPolicy,
        current_policy_age_hours: float = 0.0,
    ) -> StateSummary:
        retained = self._recent_history(history)
        oldest = retained[0] if retained else None
        history_hours = sum(
            state.timestep_duration_hours or 0.0 for state in retained
        )
        sufficient = bool(oldest) and (
            history_hours >= self.thresholds.minimum_history_hours
            or len(retained) >= 4
        )
        zone_change = self._change(
            current_state.zone_temperature,
            oldest.zone_temperature if oldest else None,
        )
        facility_change_kw = self._change(
            current_state.power_kw,
            oldest.power_kw if oldest else None,
        )
        outdoor_change = self._change(
            current_state.outdoor_temperature,
            oldest.outdoor_temperature if oldest else None,
        )
        facility_w = self._watts(current_state.power_kw)
        hvac_w = self._watts(current_state.hvac_power_kw)
        facility_change_w = (
            facility_change_kw * 1000.0
            if facility_change_kw is not None
            else None
        )
        return StateSummary(
            current_zone_temperature_c=current_state.zone_temperature,
            target_zone_temperature_c=(
                current_policy.target_zone_temperature_c
            ),
            zone_temperature_change_4h_c=zone_change,
            zone_trend=self._classify_change(
                zone_change,
                self.thresholds.strong_temperature_change_c,
            ),
            thermal_state=self._thermal_state(
                current_state.zone_temperature,
                current_policy.target_zone_temperature_c,
            ),
            current_hvac_power_w=hvac_w,
            current_facility_power_w=facility_w,
            facility_power_change_4h_w=facility_change_w,
            power_trend=self._classify_change(
                facility_change_w,
                self.thresholds.strong_power_change_w,
            ),
            outdoor_temperature_change_4h_c=outdoor_change,
            outdoor_trend=self._classify_change(
                outdoor_change,
                self.thresholds.strong_outdoor_change_c,
            ),
            current_policy=current_policy,
            current_policy_age_hours=current_policy_age_hours,
            current_mode=current_policy.strategy,
            history_sufficient=sufficient,
            occupancy_available=self._finite(current_state.occupancy),
            pmv_available=self._finite(current_state.pmv),
            high_power=(
                (facility_w or 0.0)
                >= self.thresholds.high_facility_power_w
                or (hvac_w or 0.0) >= self.thresholds.high_hvac_power_w
            ),
            contradictory_data=False,
        )

    @staticmethod
    def _recent_history(
        history: Sequence[BuildingState],
    ) -> list[BuildingState]:
        retained: list[BuildingState] = []
        hours = 0.0
        for state in reversed(history):
            retained.append(state)
            hours += state.timestep_duration_hours or 0.0
            if hours >= 4.0:
                break
        retained.reverse()
        return retained

    def _thermal_state(self, current: float, target: float) -> str:
        delta = current - target
        if delta > self.thresholds.far_above_target_c:
            return "far_above_target"
        if delta > self.thresholds.above_target_c:
            return "above_target"
        if delta >= -self.thresholds.above_target_c:
            return "near_target"
        return "below_target"

    def _classify_change(
        self,
        change: float | None,
        strong_threshold: float,
    ) -> str:
        if change is None or not math.isfinite(change):
            return "unknown"
        if change >= strong_threshold:
            return "strongly_rising"
        if change > self.thresholds.stable_change:
            return "rising"
        if change <= -strong_threshold:
            return "strongly_falling"
        if change < -self.thresholds.stable_change:
            return "falling"
        return "stable"

    @staticmethod
    def _change(
        current: float | None,
        previous: float | None,
    ) -> float | None:
        if not (
            DeterministicFeatureExtractor._finite(current)
            and DeterministicFeatureExtractor._finite(previous)
        ):
            return None
        return float(current) - float(previous)

    @staticmethod
    def _watts(value_kw: float | None) -> float | None:
        return float(value_kw) * 1000.0 if DeterministicFeatureExtractor._finite(value_kw) else None

    @staticmethod
    def _finite(value: float | None) -> bool:
        return value is not None and math.isfinite(value)
