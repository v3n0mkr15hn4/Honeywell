"""Run the unchanged six candidate cases through NVIDIA NIM."""

from __future__ import annotations

import json
import os
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "src", ROOT / "tests"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from controller.llm_policy_ranker import LLMPolicyRanker  # noqa: E402
from controller.policy_validator import PolicyValidator  # noqa: E402
from llm.nvidia_nim_client import NvidiaNIMClient  # noqa: E402
from qwen3_1_7b_candidate_ranking_test import (  # noqa: E402
    _fabricated,
    _forbidden_output,
    cases,
    fixture,
)


MODEL = "nvidia/llama-3.3-nemotron-super-49b-v1.5"


def run(output_dir: Path) -> dict[str, Any]:
    if not os.environ.get("NVIDIA_NIM_API_KEY", "").strip():
        payload = {
            "status": "blocked",
            "eligible_for_one_day_smoke_test": False,
            "provider": "nvidia_nim",
            "model": MODEL,
            "failure_category": "configuration_error",
            "message": (
                "NVIDIA_NIM_API_KEY is not configured. The six-case gate "
                "was not started."
            ),
            "results": [],
        }
        write(payload, output_dir)
        return payload
    client = NvidiaNIMClient(MODEL)
    ranker = LLMPolicyRanker(
        client,
        PolicyValidator(),
        provider="nvidia_nim",
        model=MODEL,
    )
    rows: list[dict[str, Any]] = []
    for case in cases():
        print(f"[NVIDIA Ranking] {case.case_id}", flush=True)
        current, controller_state = fixture(case)
        decision = ranker.recommend(current, controller_state, {})
        supplied = tuple(
            item.candidate_id for item in decision.candidate_set.candidates
        )
        parsed = decision.parsed_ranking
        all_only = bool(
            parsed
            and len(parsed.ranking) == len(supplied)
            and len(set(parsed.ranking)) == len(supplied)
            and set(parsed.ranking) == set(supplied)
        )
        selected_first = bool(
            parsed and parsed.selected_policy_id == parsed.ranking[0]
        )
        reason = parsed.reason if parsed else ""
        rows.append(
            {
                "case_id": case.case_id,
                "candidate_ids": list(supplied),
                "expected_candidate_ids": list(case.expected_candidate_ids),
                "deterministic_recommendation_id": (
                    decision.candidate_set.deterministic_recommendation_id
                ),
                "forced_single_candidate": (
                    decision.forced_single_candidate
                ),
                "llm_called": decision.llm_called,
                "raw_response": decision.raw_response,
                "strict_json_success": (
                    not decision.llm_called or parsed is not None
                ),
                "complete_ranking_success": (
                    not decision.llm_called or all_only
                ),
                "selected_id_equals_ranking_first": (
                    not decision.llm_called or selected_first
                ),
                "unknown_candidate_attempt": bool(
                    parsed
                    and any(item not in supplied for item in parsed.ranking)
                ),
                "duplicate_candidate_attempt": bool(
                    parsed
                    and len(set(parsed.ranking)) != len(parsed.ranking)
                ),
                "confidence": parsed.confidence if parsed else None,
                "reason": reason,
                "reason_grounded": (
                    not decision.llm_called
                    or any(
                        term in reason.lower()
                        for term in case.expected_reason_terms
                    )
                ),
                "forbidden_field_attempt": _forbidden_output(
                    decision.raw_response
                ),
                "fabricated_occupancy_or_pmv": _fabricated(reason),
                "parser_failure": decision.parser_failure,
                "validation_status": (
                    decision.selection.validation_status
                    if decision.selection
                    else decision.failure_reason
                ),
                "latency_s": decision.response_time_s,
                "retry_count": decision.llm_retry_count,
                "failure_category": decision.llm_failure_category,
                "fallback_used": decision.fallback_used,
                "final_selected_policy_id": (
                    decision.selected_candidate.candidate_id
                ),
                "final_selection_bounded": (
                    decision.selected_candidate
                    in decision.candidate_set.candidates
                ),
                "final_policy_safe": (
                    not PolicyValidator().validate(decision.policy).corrected
                ),
            }
        )
        if decision.llm_failure_category in {
            "authentication_error",
            "permission_error",
            "model_unavailable",
        }:
            break
    actual = [row for row in rows if row["llm_called"]]
    latencies = [float(row["latency_s"]) for row in actual]
    criteria = {
        "six_cases_completed": len(rows) == 6,
        "all_actual_calls_complete": len(actual) == 5,
        "timeouts_zero": not any(
            row["failure_category"] == "timeout" for row in actual
        ),
        "strict_json_100_percent": bool(actual)
        and all(row["strict_json_success"] for row in actual),
        "internally_valid_rankings_100_percent": bool(actual)
        and all(
            row["complete_ranking_success"]
            and row["selected_id_equals_ranking_first"]
            for row in actual
        ),
        "complete_rankings_100_percent": bool(actual)
        and all(row["complete_ranking_success"] for row in actual),
        "selected_first_100_percent": bool(actual)
        and all(row["selected_id_equals_ranking_first"] for row in actual),
        "unknown_ids_zero": not any(
            row["unknown_candidate_attempt"] for row in actual
        ),
        "duplicate_ids_zero": not any(
            row["duplicate_candidate_attempt"] for row in actual
        ),
        "forbidden_fields_zero": not any(
            row["forbidden_field_attempt"] for row in actual
        ),
        "fabrication_zero": not any(
            row["fabricated_occupancy_or_pmv"] for row in actual
        ),
        "reasons_grounded_100_percent": bool(actual)
        and all(row["reason_grounded"] for row in actual),
        "all_final_policies_safe": all(
            row["final_policy_safe"] for row in rows
        ),
        "fallback_reliable": all(
            row["final_selection_bounded"] for row in rows
        ),
        "latency_acceptable": bool(latencies) and max(latencies) < 30.0,
    }
    payload = {
        "status": "pass" if all(criteria.values()) else "fail",
        "eligible_for_one_day_smoke_test": all(criteria.values()),
        "provider": "nvidia_nim",
        "model": MODEL,
        "case_count": len(rows),
        "actual_llm_calls": len(actual),
        "average_latency_s": (
            statistics.mean(latencies) if latencies else None
        ),
        "median_latency_s": (
            statistics.median(latencies) if latencies else None
        ),
        "maximum_latency_s": max(latencies) if latencies else None,
        "acceptance_criteria": criteria,
        "results": rows,
    }
    write(payload, output_dir)
    return payload


def write(payload: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "nvidia_nim_candidate_ranking_results.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# NVIDIA NIM Candidate Ranking Gate",
        "",
        f"**{str(payload['status']).upper()}**",
        "",
        f"- Provider: `{payload['provider']}`",
        f"- Model: `{payload['model']}`",
    ]
    if payload["status"] == "blocked":
        lines.append(f"- Result: {payload['message']}")
    else:
        lines.extend(
            [
                f"- Cases: {payload['case_count']}/6",
                f"- Actual calls: {payload['actual_llm_calls']}",
                (
                    "- Median latency: "
                    f"{payload['median_latency_s']:.3f} s"
                ),
                "",
                "| Case | Candidates | Strict | Complete | Selected first | Final | Fallback |",
                "| --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for row in payload["results"]:
            lines.append(
                f"| {row['case_id']} | {','.join(row['candidate_ids'])} | "
                f"{row['strict_json_success']} | "
                f"{row['complete_ranking_success']} | "
                f"{row['selected_id_equals_ranking_first']} | "
                f"{row['final_selected_policy_id']} | "
                f"{row['fallback_used']} |"
            )
        lines.extend(["", "## Manual Review", ""])
        for row in payload["results"]:
            lines.extend(
                [
                    f"### {row['case_id']}",
                    "",
                    (
                        "Forced deterministic candidate; no LLM call."
                        if not row["llm_called"]
                        else (
                            f"Final `{row['final_selected_policy_id']}`; "
                            f"confidence `{row['confidence']}`; reason: "
                            f"{row['reason']}"
                        )
                    ),
                    "",
                ]
            )
    (output_dir / "nvidia_nim_candidate_ranking_report.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    result = run(ROOT / "test_reports")
    print(f"[NVIDIA Ranking] status={result['status']}")
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
