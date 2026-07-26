from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.agent.controller_compatibility import ControllerCompatibilityAnalyser
from src.simulation_upload.error_analyser import EnergyPlusErrorAnalyser


class ErrorAnalyserTests(unittest.TestCase):
    def test_extracts_energyplus_severity_and_categories(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "eplusout.err"
            path.write_text(
                "** Warning ** Convergence iteration limit reached\n"
                "** Warning ** Convergence iteration limit reached\n"
                "** Severe  ** Object reference not found\n"
                "** Fatal  ** Simulation terminated\n",
                encoding="utf-8",
            )
            result = EnergyPlusErrorAnalyser().analyse(root)
        self.assertEqual(result.fatal_count, 1)
        self.assertEqual(result.severe_count, 1)
        self.assertEqual(result.warning_count, 2)
        self.assertIn("convergence_issue", result.categories)
        self.assertIn("missing_object_reference", result.categories)
        self.assertTrue(result.recurring_warning_groups)

    def test_missing_error_file_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            result = EnergyPlusErrorAnalyser().analyse(root)
        self.assertIn("EnergyPlus .err file", result.missing_expected_files)


class CompatibilityTests(unittest.TestCase):
    def test_arbitrary_model_is_never_promoted_from_names_alone(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            validated = Path(root) / "validated.idf"
            arbitrary = Path(root) / "arbitrary.idf"
            validated.write_text("Version,26.1; Building,A;", encoding="utf-8")
            arbitrary.write_text("Version,26.1; Building,B;", encoding="utf-8")
            analyser = ControllerCompatibilityAnalyser(validated)
            result = analyser.analyse(
                idf_path=arbitrary,
                validation_succeeded=True,
                output_variables_text=(
                    "Zone Mean Air Temperature\n"
                    "Site Outdoor Air Drybulb Temperature"
                ),
                output_meters_text="Electricity:Facility",
                verified_actuator_inventory=[
                    "MAIN COOLING COIL 1 OUTLET NODE"
                ],
            )
        self.assertTrue(result.standard_simulation_compatible)
        self.assertFalse(result.closed_loop_compatible)
        self.assertIsNone(result.confirmed_actuator_target)

    def test_exact_model_still_requires_verified_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            model = Path(root) / "validated.idf"
            model.write_text("Version,26.1;", encoding="utf-8")
            analyser = ControllerCompatibilityAnalyser(model)
            result = analyser.analyse(
                idf_path=model,
                validation_succeeded=True,
                output_variables_text=(
                    "Zone Mean Air Temperature\n"
                    "Site Outdoor Air Drybulb Temperature"
                ),
                output_meters_text="Electricity:Facility",
                verified_actuator_inventory=[],
            )
        self.assertFalse(result.closed_loop_compatible)


if __name__ == "__main__":
    unittest.main()
