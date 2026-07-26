from __future__ import annotations

import unittest

from controller.deterministic_feature_extractor import (
    DeterministicFeatureExtractor,
)
from controller.supervisor_policy import default_supervisor_policy
from test_support import make_state


class DeterministicFeatureExtractorTests(unittest.TestCase):
    def test_extracts_processed_trends_and_availability(self) -> None:
        history = [
            make_state(
                zone_temperature=30.0,
                power_kw=80.0,
                outdoor_temperature=25.0,
                timestep_duration_hours=1.0,
            ),
            make_state(
                zone_temperature=31.0,
                power_kw=90.0,
                outdoor_temperature=30.0,
                timestep_duration_hours=1.0,
            ),
        ]
        current = make_state(
            zone_temperature=33.0,
            power_kw=110.0,
            hvac_power_kw=21.0,
            outdoor_temperature=36.0,
            occupancy=None,
            pmv=None,
        )
        result = DeterministicFeatureExtractor().extract(
            current,
            history,
            default_supervisor_policy(),
            3.0,
        )

        self.assertEqual(result.zone_trend, "strongly_rising")
        self.assertEqual(result.thermal_state, "above_target")
        self.assertEqual(result.power_trend, "strongly_rising")
        self.assertEqual(result.outdoor_trend, "strongly_rising")
        self.assertTrue(result.high_power)
        self.assertFalse(result.occupancy_available)
        self.assertFalse(result.pmv_available)

    def test_insufficient_history_is_explicit(self) -> None:
        result = DeterministicFeatureExtractor().extract(
            make_state(),
            [],
            default_supervisor_policy(),
        )
        self.assertFalse(result.history_sufficient)
        self.assertEqual(result.zone_trend, "unknown")


if __name__ == "__main__":
    unittest.main()
