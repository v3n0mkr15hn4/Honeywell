from __future__ import annotations

import math
import unittest

from controller.action import ControlAction
from telemetry.metrics import MetricsTracker
from test_support import make_state


def record(
    metrics: MetricsTracker,
    *,
    state=None,
    decision_made: bool = True,
    llm_call_made: bool = False,
    action_reused: bool = False,
) -> None:
    metrics.record_timestep(
        building_state=state or make_state(),
        decision_made=decision_made,
        safety_corrected=False,
        llm_call_made=llm_call_made,
        llm_failure=False,
        fallback_used=False,
        action_reused=action_reused,
        controller_type="LLMController",
        llm_response_time_seconds=None,
    )


class MetricsTrackerTests(unittest.TestCase):
    def test_energy_integration_uses_kw_times_timestep_hours(self) -> None:
        metrics = MetricsTracker()
        record(
            metrics,
            state=make_state(power_kw=10.0, timestep_duration_hours=0.25),
        )
        self.assertAlmostEqual(metrics.energy_kwh, 2.5)
        self.assertAlmostEqual(metrics.hvac_energy_kwh, 2.5)
        self.assertAlmostEqual(metrics.cooling_coil_energy_kwh, 1.5)

    def test_temperature_extremes_and_target_rate_are_explicit(self) -> None:
        metrics = MetricsTracker(zone_temperature_target_threshold_c=30.0)
        record(metrics, state=make_state(zone_temperature=29.0))
        record(metrics, state=make_state(zone_temperature=31.0))

        self.assertEqual(metrics.minimum_indoor_temp_c, 29.0)
        self.assertEqual(metrics.maximum_indoor_temp_c, 31.0)
        self.assertEqual(metrics.zone_temperature_target_violations, 1)
        self.assertIn(
            "Zone Temperature Target Violation Rate: 0.500000",
            metrics.build_summary(),
        )

    def test_llm_requests_count_calls_not_reused_timesteps(self) -> None:
        metrics = MetricsTracker()
        record(metrics, decision_made=True, llm_call_made=True)
        record(metrics, decision_made=False, action_reused=True)
        record(metrics, decision_made=False, action_reused=True)

        self.assertEqual(metrics.control_timesteps, 3)
        self.assertEqual(metrics.controller_decisions, 1)
        self.assertEqual(metrics.llm_requests, 1)
        self.assertEqual(metrics.reused_actions, 2)

    def test_invalid_pmv_is_ignored(self) -> None:
        metrics = MetricsTracker()
        record(metrics, state=make_state(occupancy=1, pmv=math.nan))
        record(metrics, state=make_state(occupancy=1, pmv=0.7))
        self.assertEqual(metrics.pmv_sample_count, 1)
        self.assertEqual(metrics.occupied_pmv_violations, 1)

    def test_actuator_changes_compare_physical_node_setpoint(self) -> None:
        metrics = MetricsTracker()
        metrics.record_actuator_application(ControlAction(23.0, "a", "a"))
        metrics.record_actuator_application(ControlAction(23.0, "b", "b"))
        metrics.record_actuator_application(ControlAction(24.0, "c", "c"))
        self.assertEqual(metrics.actuator_changes, 2)

    def test_supervisory_metrics_distinguish_calls_failures_and_reuse(
        self,
    ) -> None:
        metrics = MetricsTracker()
        metrics.record_timestep(
            building_state=make_state(),
            decision_made=True,
            safety_corrected=True,
            llm_call_made=False,
            llm_failure=False,
            fallback_used=False,
            action_reused=False,
            controller_type="PolicyAwareRuleController",
            llm_response_time_seconds=None,
            supervisor_call_due=True,
            supervisor_called=True,
            supervisor_failure=True,
            supervisor_parser_failure=True,
            supervisor_timeout=False,
            supervisor_fallback_used=True,
            supervisor_validation_corrected=False,
            supervisor_policy_changed=False,
            supervisor_policy_reused=True,
            default_policy_used=True,
            supervisor_response_time_s=0.25,
            supervisor_cooldown_active=True,
            supervisor_cooldown_activated=True,
        )
        self.assertEqual(metrics.supervisory_calls, 1)
        self.assertEqual(metrics.successful_supervisory_calls, 0)
        self.assertEqual(metrics.supervisory_parser_failures, 1)
        self.assertEqual(metrics.supervisory_fallbacks, 1)
        self.assertEqual(metrics.policy_reuse_count, 1)
        self.assertEqual(metrics.default_policy_usage_count, 1)
        self.assertEqual(metrics.safety_corrections, 1)
        self.assertEqual(metrics.snapshot()["supervisory_fallbacks"], 1)

    def test_candidate_ranking_metrics_are_separate(self) -> None:
        metrics = MetricsTracker()
        metrics.record_timestep(
            building_state=make_state(),
            decision_made=True,
            safety_corrected=False,
            llm_call_made=False,
            llm_failure=False,
            fallback_used=False,
            action_reused=False,
            controller_type="PolicyAwareRuleController",
            llm_response_time_seconds=None,
            supervisor_call_due=True,
            supervisor_called=True,
            candidate_metadata={
                "forced_single_candidate": False,
                "llm_ranker_called": True,
                "selected_policy_source": "llm_selected",
                "final_selected_policy_id": "P2",
                "llm_confidence": 0.82,
                "ranking_validation_status": "valid candidate ranking",
                "llm_provider": "nvidia_nim",
                "llm_request_completed": True,
            },
        )
        summary = metrics.build_summary()
        self.assertIn("Candidate Supervisory Opportunities: 1", summary)
        self.assertIn("Multi-Candidate LLM Calls: 1", summary)
        self.assertIn("Successful Valid Candidate Rankings: 1", summary)
        self.assertIn("'P2': 1", summary)
        self.assertIn("Total NVIDIA NIM Calls: 1", summary)
        self.assertIn("Successful NVIDIA NIM Calls: 1", summary)


if __name__ == "__main__":
    unittest.main()
