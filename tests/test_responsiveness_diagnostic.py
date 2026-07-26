from __future__ import annotations

import unittest

from qwen3_1_7b_responsiveness_diagnostic import (
    _fabricates_unavailable_data,
    _reason_directions,
    _state_reference_present,
    diagnostic_cases,
)


class ResponsivenessDiagnosticTests(unittest.TestCase):
    def test_fixed_five_case_corpus_covers_required_scenarios(self) -> None:
        cases = diagnostic_cases()

        self.assertEqual(
            [case.case_id for case in cases],
            [
                "hot_rising",
                "hot_falling",
                "stable_hold",
                "stable_lower_limit",
                "previous_25",
            ],
        )
        self.assertEqual(cases[3].previous_setpoint_c, 22.0)
        self.assertEqual(cases[4].previous_setpoint_c, 25.0)

    def test_reason_direction_detection_uses_actuator_semantics(self) -> None:
        self.assertEqual(
            _reason_directions(
                "The zone is rising, so lower the supply-air target to "
                "strengthen cooling."
            ),
            {"lower"},
        )
        self.assertEqual(
            _reason_directions(
                "Power is stable, so raise the supply-air target to reduce cooling."
            ),
            {"higher"},
        )
        self.assertEqual(
            _reason_directions(
                "The zone trend is stable, so hold the previous setpoint."
            ),
            {"hold"},
        )
        self.assertEqual(
            _reason_directions(
                "No meaningful change is justified, so the prior setpoint "
                "is maintained."
            ),
            {"hold"},
        )

    def test_contradictory_reason_has_multiple_direction_signals(self) -> None:
        self.assertEqual(
            _reason_directions(
                "Lower the supply target but reduce cooling by raising it."
            ),
            {"lower", "higher"},
        )

    def test_state_reference_requires_actual_state_language(self) -> None:
        case = diagnostic_cases()[0]

        self.assertTrue(
            _state_reference_present(
                "Zone temperature is hot and rising.",
                case,
            )
        )
        self.assertFalse(
            _state_reference_present(
                "Use stronger cooling.",
                case,
            )
        )

    def test_unavailable_occupancy_and_pmv_claims_are_flagged(self) -> None:
        self.assertTrue(
            _fabricates_unavailable_data(
                "The building is occupied.",
                occupancy=None,
                pmv=None,
            )
        )
        self.assertTrue(
            _fabricates_unavailable_data(
                "PMV is too high.",
                occupancy=None,
                pmv=None,
            )
        )
        self.assertFalse(
            _fabricates_unavailable_data(
                "Occupancy and PMV are unavailable.",
                occupancy=None,
                pmv=None,
            )
        )


if __name__ == "__main__":
    unittest.main()
