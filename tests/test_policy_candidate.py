from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError

from candidate_test_support import make_summary
from controller.candidate_policy_generator import CandidatePolicyGenerator
from controller.policy_validator import PolicyValidator


class PolicyCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        summary = make_summary()
        self.candidate = CandidatePolicyGenerator().generate(
            summary,
            summary.current_policy,
        ).candidates[0]

    def test_valid_immutable_actuator_free_candidate(self) -> None:
        with self.assertRaises(FrozenInstanceError):
            self.candidate.strategy = "changed"  # type: ignore[misc]
        for forbidden in (
            "supply_air_temperature_setpoint",
            "cooling_setpoint",
            "heating_setpoint",
            "actuator_key",
            "actuator_handle",
            "callback_name",
        ):
            self.assertFalse(hasattr(self.candidate, forbidden))

    def test_candidate_converts_to_valid_policy(self) -> None:
        result = PolicyValidator().validate(self.candidate.to_policy())
        self.assertFalse(result.corrected)
        self.assertEqual(result.validated_policy, self.candidate.to_policy())


if __name__ == "__main__":
    unittest.main()
