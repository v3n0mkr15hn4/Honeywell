"""Compact prompt construction for ranking safe policy candidates."""

from __future__ import annotations

from controller.policy_candidate import CandidatePolicySet
from controller.state_summary import StateSummary


def build_candidate_policy_prompt(
    summary: StateSummary,
    candidate_set: CandidatePolicySet,
) -> str:
    """Expose processed facts and immutable candidates, never raw history."""

    candidates = "\n".join(
        (
            f"- {candidate.candidate_id}: mode={candidate.mode}; "
            f"thermal={candidate.thermal_priority.value}; "
            f"energy={candidate.energy_priority.value}; "
            f"aggressiveness={candidate.controller_aggressiveness.value}; "
            f"zone_target_c={candidate.target_zone_temperature_c:.1f}; "
            f"hold_intervals={candidate.minimum_action_hold_intervals}; "
            f"duration_hours={candidate.policy_duration_hours}"
        )
        for candidate in candidate_set.candidates
    )
    candidate_ids = ", ".join(
        candidate.candidate_id for candidate in candidate_set.candidates
    )
    current = summary.current_policy
    return "\n".join(
        [
            "Bounded EnergyPlus Supervisory Candidate Ranking",
            "",
            "Processed facts:",
            (
                f"- current_zone_temperature_c: "
                f"{summary.current_zone_temperature_c:.3f}"
            ),
            (
                f"- target_zone_temperature_c: "
                f"{summary.target_zone_temperature_c:.3f}"
            ),
            f"- thermal_state: {summary.thermal_state}",
            f"- zone_trend: {summary.zone_trend}",
            f"- power_trend: {summary.power_trend}",
            f"- high_power: {str(summary.high_power).lower()}",
            f"- outdoor_trend: {summary.outdoor_trend}",
            (
                f"- current_policy: thermal={current.thermal_priority.value}, "
                f"energy={current.energy_priority.value}, "
                "aggressiveness="
                f"{current.controller_aggressiveness.value}, "
                f"strategy={current.strategy}"
            ),
            (
                f"- current_policy_age_hours: "
                f"{summary.current_policy_age_hours:.3f}"
            ),
            (
                f"- occupancy_available: "
                f"{str(summary.occupancy_available).lower()}"
            ),
            f"- pmv_available: {str(summary.pmv_available).lower()}",
            "",
            "Supplied safe candidates:",
            candidates,
            f"Candidate IDs: {candidate_ids}",
            (
                "Deterministic recommendation ID: "
                f"{candidate_set.deterministic_recommendation_id}"
            ),
            (
                "Deterministic ranking: "
                + ", ".join(candidate_set.deterministic_ranking)
            ),
            "",
            "Instructions:",
            "- Rank only the supplied candidates.",
            "- Include every supplied candidate exactly once.",
            "- Select exactly one supplied candidate ID.",
            "- selected_policy_id must equal the first ranking item.",
            "- Do not create a new policy or candidate.",
            "- Do not modify or return numeric candidate values.",
            "- Do not return physical actuator values or physical setpoints.",
            "- Thermal deterioration takes priority over energy saving.",
            "- Use the supplied thermal, power, and outdoor trade-offs.",
            "- Reason only from supplied processed facts.",
            "- Occupancy and PMV are unavailable when marked false.",
            (
                "Return strict JSON with exactly ranking, "
                "selected_policy_id, confidence, and reason."
            ),
            "- Return JSON only, without markdown or surrounding prose.",
        ]
    )
