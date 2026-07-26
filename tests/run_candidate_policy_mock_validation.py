"""Run every deterministic candidate-ranker mock boundary mode."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
for path in (SRC, TESTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from candidate_test_support import ranker_controller_state  # noqa: E402
from controller.llm_policy_ranker import LLMPolicyRanker  # noqa: E402
from controller.policy_validator import PolicyValidator  # noqa: E402
from llm.candidate_ranker_mock_client import (  # noqa: E402
    CandidateRankerMockMode,
    MockCandidateRankerLLMClient,
)
from test_support import make_state  # noqa: E402


VALID_MODES = {
    CandidateRankerMockMode.VALID_TOP_DETERMINISTIC,
    CandidateRankerMockMode.VALID_ALTERNATIVE_HIGH_CONFIDENCE,
    CandidateRankerMockMode.VALID_MEDIUM_CONFIDENCE_TOP_TWO,
}


def run(output_dir: Path) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for mode in CandidateRankerMockMode:
        client = MockCandidateRankerLLMClient(mode)
        result = LLMPolicyRanker(client, PolicyValidator()).recommend(
            make_state(
                zone_temperature=32.0,
                power_kw=125.0,
                hvac_power_kw=23.0,
            ),
            ranker_controller_state(),
            {},
        )
        final_in_set = result.selected_candidate in result.candidate_set.candidates
        safe = not PolicyValidator().validate(result.policy).corrected
        expected_fallback = mode not in VALID_MODES
        passed = (
            final_in_set
            and safe
            and result.fallback_used == expected_fallback
            and not hasattr(result.policy, "supply_air_temperature_setpoint")
        )
        rows.append(
            {
                "mode": mode.value,
                "request_count": client.request_count,
                "fallback_used": result.fallback_used,
                "failure_reason": result.failure_reason,
                "parser_failure": result.parser_failure,
                "timeout": result.timeout,
                "candidate_ids": [
                    item.candidate_id
                    for item in result.candidate_set.candidates
                ],
                "deterministic_recommendation_id": (
                    result.candidate_set.deterministic_recommendation_id
                ),
                "final_selected_policy_id": (
                    result.selected_candidate.candidate_id
                ),
                "selected_policy_source": result.selected_policy_source,
                "final_selection_belongs_to_set": final_in_set,
                "final_policy_safe": safe,
                "passed": passed,
            }
        )
    payload: dict[str, object] = {
        "status": "pass" if all(row["passed"] for row in rows) else "fail",
        "scenario_count": len(rows),
        "passed_count": sum(bool(row["passed"]) for row in rows),
        "all_final_selections_bounded": all(
            row["final_selection_belongs_to_set"] for row in rows
        ),
        "all_final_policies_safe": all(
            row["final_policy_safe"] for row in rows
        ),
        "results": rows,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "candidate_policy_mock_validation_results.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# Candidate Policy Mock Validation",
        "",
        f"**{str(payload['status']).upper()}**",
        "",
        f"- Scenarios: {payload['passed_count']}/{payload['scenario_count']}",
        (
            "- Final selections inside current candidate set: "
            f"`{payload['all_final_selections_bounded']}`"
        ),
        f"- Final policies safe: `{payload['all_final_policies_safe']}`",
        "",
        "| Mode | Fallback | Parser failure | Timeout | Final ID | Pass |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['mode']} | {row['fallback_used']} | "
            f"{row['parser_failure']} | {row['timeout']} | "
            f"{row['final_selected_policy_id']} | {row['passed']} |"
        )
    (output_dir / "candidate_policy_mock_validation_report.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    return payload


def write_component_reports(output_dir: Path) -> None:
    reports = {
        "candidate_policy_architecture_report.md": [
            "# Candidate Policy Architecture",
            "",
            "EnergyPlus history is reduced to deterministic StateSummary facts. "
            "Fixed, validated policy candidates are ranked by the LLM. "
            "PolicyAwareRuleController remains the only ControlAction creator, "
            "and SafetyValidator plus ActuatorWriter retain physical authority.",
            "",
            "The LLM performs bounded multi-objective supervisory policy "
            "selection by ranking dynamically generated safe candidates using "
            "thermal, energy, and environmental state summaries. Deterministic "
            "controllers convert the selected policy into physical commands "
            "and enforce all safety constraints.",
        ],
        "candidate_policy_generator_report.md": [
            "# Candidate Policy Generator",
            "",
            "Nine fixed rule branches were implemented. Severe or insufficient "
            "conditions force one candidate and skip inference. Multi-candidate "
            "sets contain only fixed templates P1-P6, and every option is passed "
            "through PolicyValidator before prompt construction.",
            "",
            "Template policy durations are 4 hours because the existing "
            "PolicyValidator minimum remains 4 hours.",
        ],
        "candidate_ranking_parser_report.md": [
            "# Candidate Ranking Parser",
            "",
            "The parser requires exactly ranking, selected_policy_id, confidence, "
            "and reason. It rejects malformed or wrapped JSON, missing or extra "
            "fields, duplicate IDs, invalid types, empty text, NaN, and Infinity. "
            "Candidate-set membership remains a separate validator concern.",
        ],
        "candidate_selection_validator_report.md": [
            "# Candidate Selection Validator",
            "",
            "The validator requires a complete permutation of the current "
            "candidate IDs and selected_policy_id equal to ranking[0]. High "
            "confidence accepts any valid supplied option; medium confidence is "
            "limited to the deterministic top two; low confidence falls back to "
            "the current deterministic recommendation.",
        ],
    }
    for filename, lines in reports.items():
        (output_dir / filename).write_text(
            "\n".join(lines) + "\n",
            encoding="utf-8",
        )


def main() -> int:
    output_dir = ROOT / "test_reports"
    result = run(output_dir)
    write_component_reports(output_dir)
    print(
        f"[Candidate Mock] {result['passed_count']}/"
        f"{result['scenario_count']} passed"
    )
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
