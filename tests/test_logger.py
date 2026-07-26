from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from controller.action import ControlAction
from controller.supervisor_policy import default_supervisor_policy
from telemetry.logger import ControlLogger
from test_support import make_state


class ControlLoggerTests(unittest.TestCase):
    def test_requested_validated_applied_and_measured_values_are_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "control_log.csv"
            logger = ControlLogger(path)
            try:
                logger.write(
                    building_state=make_state(
                        supply_air_temperature_setpoint=22.8,
                        measured_supply_air_temperature=23.2,
                    ),
                    requested_action=ControlAction(
                        18.0,
                        "strategy, with comma",
                        'reason with "quote"',
                    ),
                    validated_action=ControlAction(
                        22.0,
                        "strategy, with comma",
                        'reason with "quote"',
                    ),
                    applied_action=ControlAction(23.0, "previous", "previous"),
                    validation_result="clamped to 22.0 C",
                    controller_type="LLMController",
                    llm_response_time_seconds=0.01,
                    fallback_used=False,
                    safety_corrected=True,
                    llm_call_due=True,
                    llm_call_made=True,
                    action_reused=False,
                    decision_interval_timesteps=6,
                    timesteps_since_last_llm_call=0,
                    decision_source="llm",
                    consecutive_llm_failures=2,
                    cooldown_active=True,
                    cooldown_intervals_remaining=3,
                    fallback_reason="transport timeout",
                )
            finally:
                logger.close()

            with path.open(newline="", encoding="utf-8") as file:
                rows = list(csv.reader(file))
            self.assertEqual(len(rows[0]), len(rows[1]))

            with path.open(newline="", encoding="utf-8") as file:
                row = list(csv.DictReader(file))[0]

            self.assertEqual(row["requested_supply_air_setpoint_c"], "18.000")
            self.assertEqual(row["validated_supply_air_setpoint_c"], "22.000")
            self.assertEqual(row["applied_supply_air_setpoint_c"], "23.000")
            self.assertEqual(row["measured_node_setpoint_c"], "22.800")
            self.assertEqual(row["measured_supply_air_temperature_c"], "23.200")
            self.assertEqual(row["legacy_cooling_setpoint_alias_c"], "22.000")
            self.assertEqual(row["llm_call_due"], "True")
            self.assertEqual(row["llm_call_made"], "True")
            self.assertEqual(row["decision_interval_timesteps"], "6")
            self.assertEqual(row["consecutive_llm_failures"], "2")
            self.assertEqual(row["cooldown_active"], "True")
            self.assertEqual(row["fallback_reason"], "transport timeout")
            self.assertEqual(row["strategy"], "strategy, with comma")

    def test_supervisory_policy_is_logged_separately_from_physical_action(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "control_log.csv"
            logger = ControlLogger(path)
            try:
                logger.write(
                    building_state=make_state(),
                    requested_action=ControlAction(22.0, "physical", "rule"),
                    validated_action=ControlAction(22.0, "physical", "rule"),
                    applied_action=None,
                    validation_result="valid",
                    supervisor_enabled=True,
                    supervisor_provider="mock",
                    supervisor_model="valid_balanced",
                    supervisor_call_due=True,
                    supervisor_called=True,
                    supervisor_policy=default_supervisor_policy(),
                    policy_validation_status="valid",
                )
            finally:
                logger.close()

            with path.open(newline="", encoding="utf-8") as file:
                row = list(csv.DictReader(file))[0]
            self.assertEqual(row["requested_supply_air_setpoint_c"], "22.000")
            self.assertEqual(row["thermal_priority"], "high")
            self.assertEqual(row["target_zone_temperature_c"], "32.000")
            self.assertEqual(row["policy_strategy"], "balanced_default")
            self.assertNotIn(
                "supply_air_temperature_setpoint",
                {
                    "thermal_priority",
                    "energy_priority",
                    "controller_aggressiveness",
                    "target_zone_temperature_c",
                },
            )

    def test_candidate_selection_telemetry_is_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "control_log.csv"
            logger = ControlLogger(path)
            try:
                logger.write(
                    building_state=make_state(),
                    requested_action=ControlAction(22.0, "physical", "rule"),
                    validated_action=ControlAction(22.0, "physical", "rule"),
                    applied_action=None,
                    validation_result="valid",
                    candidate_metadata={
                        "candidate_generation_reason": "hot_and_rising",
                        "candidate_count": 3,
                        "candidate_ids": ["P1", "P2", "P3"],
                        "deterministic_recommendation_id": "P2",
                        "llm_ranker_called": True,
                        "llm_raw_ranking": ["P2", "P1", "P3"],
                        "llm_selected_policy_id": "P2",
                        "llm_confidence": 0.8,
                        "final_selected_policy_id": "P2",
                        "selected_policy_source": "llm_selected",
                        "llm_provider": "nvidia_nim",
                        "llm_model": "nvidia/test-model",
                        "llm_request_started": True,
                        "llm_request_completed": True,
                        "llm_retry_count": 0,
                        "llm_http_status_category": "2xx",
                    },
                )
            finally:
                logger.close()
            with path.open(newline="", encoding="utf-8") as file:
                row = list(csv.DictReader(file))[0]
            self.assertEqual(row["candidate_ids"], '["P1","P2","P3"]')
            self.assertEqual(row["llm_selected_policy_id"], "P2")
            self.assertEqual(row["final_selected_policy_id"], "P2")
            self.assertEqual(row["selected_policy_source"], "llm_selected")
            self.assertEqual(row["llm_provider"], "nvidia_nim")
            self.assertEqual(row["llm_request_completed"], "True")


if __name__ == "__main__":
    unittest.main()
