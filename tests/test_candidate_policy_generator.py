from __future__ import annotations

import unittest

from candidate_test_support import energy_policy, make_summary
from controller.candidate_policy_generator import CandidatePolicyGenerator
from controller.policy_validator import PolicyValidator


class CandidatePolicyGeneratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.generator = CandidatePolicyGenerator()

    def assert_case(
        self,
        expected_ids: tuple[str, ...],
        recommendation: str,
        **summary_values: object,
    ) -> None:
        summary = make_summary(**summary_values)
        result = self.generator.generate(summary, summary.current_policy)
        self.assertEqual(
            tuple(item.candidate_id for item in result.candidates),
            expected_ids,
        )
        self.assertEqual(result.deterministic_recommendation_id, recommendation)
        for candidate in result.candidates:
            validation = PolicyValidator().validate(candidate.to_policy())
            self.assertFalse(validation.corrected)

    def test_severe_thermal_deterioration(self) -> None:
        self.assert_case(
            ("P1",),
            "P1",
            thermal_state="far_above_target",
            zone_trend="strongly_rising",
        )

    def test_overheating_under_energy_saving_policy(self) -> None:
        self.assert_case(
            ("P1", "P2"),
            "P1",
            current_policy=energy_policy(),
            thermal_state="above_target",
            zone_trend="rising",
        )

    def test_hot_and_rising(self) -> None:
        self.assert_case(
            ("P1", "P2", "P3"),
            "P2",
            thermal_state="above_target",
            zone_trend="rising",
        )

    def test_hot_but_recovering(self) -> None:
        self.assert_case(
            ("P2", "P3", "P6"),
            "P3",
            thermal_state="above_target",
            zone_trend="falling",
        )

    def test_high_power_while_thermally_acceptable(self) -> None:
        self.assert_case(
            ("P3", "P4", "P5", "P6"),
            "P4",
            high_power=True,
        )

    def test_stable_conditions(self) -> None:
        self.assert_case(("P3", "P4", "P6"), "P6")

    def test_outdoor_load_increase(self) -> None:
        self.assert_case(
            ("P2", "P3", "P6"),
            "P3",
            outdoor_trend="strongly_rising",
            zone_trend="rising",
        )

    def test_insufficient_data_forces_hold(self) -> None:
        self.assert_case(
            ("P6",),
            "P6",
            history_sufficient=False,
        )

    def test_default_case(self) -> None:
        self.assert_case(
            ("P3", "P6"),
            "P6",
            thermal_state="below_target",
            zone_trend="falling",
            power_trend="falling",
        )


if __name__ == "__main__":
    unittest.main()
