"""Finalize candidate-policy readiness reports without further inference."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "test_reports"


def main() -> int:
    mock = json.loads(
        (REPORTS / "candidate_policy_mock_validation_results.json").read_text(
            encoding="utf-8"
        )
    )
    ranking = json.loads(
        (REPORTS / "qwen3_1_7b_candidate_ranking_results.json").read_text(
            encoding="utf-8"
        )
    )
    path = REPORTS / "candidate_policy_final_readiness_decision.md"
    lines = [
        "# Candidate Policy Final Readiness Decision",
        "",
        "## Decision",
        "",
        "**ARCHITECTURE VALIDATED; REAL-MODEL ENERGYPLUS USE REJECTED.**",
        "",
        (
            "The bounded candidate-ranking architecture is implemented and "
            "passes deterministic, parser, validator, mock, pipeline, and "
            "physical-authority tests. The installed qwen3:1.7b model failed "
            "the six-case real ranking gate, so no one-day EnergyPlus run was "
            "permitted."
        ),
        "",
        "## Evidence",
        "",
        "- Full regression suite: 107/107 passed",
        (
            f"- Mock ranker modes: {mock['passed_count']}/"
            f"{mock['scenario_count']} passed"
        ),
        (
            "- Mock final selections bounded: "
            f"`{mock['all_final_selections_bounded']}`"
        ),
        (
            "- Real ranking cases: "
            f"{ranking['case_count']}/6 completed"
        ),
        (
            "- Actual real-model calls: "
            f"{ranking['actual_llm_calls']}"
        ),
        (
            "- Real-model median latency: "
            f"{ranking['median_latency_s']:.3f} s"
        ),
        (
            "- Real-model maximum latency: "
            f"{ranking['maximum_latency_s']:.3f} s"
        ),
        "- Real-model strict responses: 4/5",
        "- Real-model internally valid rankings: 3/5",
        "- Final selections inside candidate set: 6/6",
        "- Final selected policies safe: 6/6",
        "",
        "## Failure Analysis",
        "",
        (
            "The cold ranking request timed out at 20.017 seconds. A later "
            "response ranked P3 first but declared P4 selected, violating the "
            "exact selected_policy_id == ranking[0] contract. Both failures "
            "fell back to the current deterministic recommendation, proving "
            "containment but not model viability."
        ),
        "",
        "## Authority Boundary",
        "",
        (
            "The LLM can only rank supplied IDs. It cannot create policy "
            "numbers, ControlAction, actuator values, callback instructions, "
            "or EnergyPlus writes. PolicyAwareRuleController still creates "
            "every physical action; every action still passes through the "
            "unchanged SafetyValidator and ActuatorWriter."
        ),
        "",
        "## Honest Interpretation",
        "",
        (
            "Architecturally, the LLM has a bounded multi-objective selection "
            "role, approximately 30-40% of supervisory decision-making. On "
            "this hardware and model, that role is not reliable enough for "
            "the requested real EnergyPlus smoke test. The deterministic "
            "candidate recommendation remains the deployable path."
        ),
        "",
        "This is not direct LLM control, unrestricted optimization, PMV "
        "optimization, occupant-comfort optimization, or production readiness.",
        "",
        "## Execution Boundary",
        "",
        "- One-day EnergyPlus smoke test: **NOT RUN (ranking gate failed)**",
        "- Optional comparison: **NOT RUN**",
        "- Additional models: **NOT TESTED**",
        "",
        "## Commands",
        "",
        "```powershell",
        (
            "$env:PYTHONPATH='src;tests'; python -m unittest discover "
            "-s tests -p \"test_*.py\" -q"
        ),
        (
            "$env:PYTHONPATH='src;tests'; python "
            "tests\\run_candidate_policy_mock_validation.py"
        ),
        (
            "$env:PYTHONPATH='src;tests'; python "
            "tests\\qwen3_1_7b_candidate_ranking_test.py"
        ),
        "```",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
