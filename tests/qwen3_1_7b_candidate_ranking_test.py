"""Six-case guarded real-model test for bounded candidate ranking."""

from __future__ import annotations

import json
import math
import re
import statistics
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
for path in (SRC, TESTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from candidate_test_support import energy_policy  # noqa: E402
from controller.candidate_ranking_parser import (  # noqa: E402
    CANDIDATE_RANKING_RESPONSE_SCHEMA,
)
from controller.controller_state import ControllerState  # noqa: E402
from controller.llm_policy_ranker import LLMPolicyRanker  # noqa: E402
from controller.policy_validator import PolicyValidator  # noqa: E402
from controller.supervisor_policy import (  # noqa: E402
    SupervisorPolicy,
    default_supervisor_policy,
)
from llm.client import OllamaLLMClient  # noqa: E402
from test_support import make_state  # noqa: E402


@dataclass(frozen=True)
class RankingCase:
    case_id: str
    history_zone_c: tuple[float, float]
    current_zone_c: float
    history_power_kw: tuple[float, float]
    current_power_kw: float
    history_outdoor_c: tuple[float, float]
    current_outdoor_c: float
    current_policy: SupervisorPolicy
    expected_candidate_ids: tuple[str, ...]
    expected_reason_terms: tuple[str, ...]


def cases() -> list[RankingCase]:
    default = default_supervisor_policy()
    return [
        RankingCase(
            "severe_thermal_deterioration",
            (30.0, 31.0),
            35.0,
            (90.0, 96.0),
            105.0,
            (32.0, 34.0),
            37.0,
            default,
            ("P1",),
            ("thermal", "strongly_rising", "far_above_target"),
        ),
        RankingCase(
            "overheating_under_energy_saving",
            (31.0, 32.0),
            34.0,
            (100.0, 110.0),
            120.0,
            (31.0, 33.0),
            35.0,
            energy_policy(),
            ("P1", "P2"),
            ("thermal", "rising", "above_target"),
        ),
        RankingCase(
            "hot_and_rising",
            (32.0, 32.5),
            33.2,
            (85.0, 88.0),
            92.0,
            (30.0, 31.0),
            32.0,
            default,
            ("P1", "P2", "P3"),
            ("thermal", "rising", "above_target"),
        ),
        RankingCase(
            "hot_but_recovering",
            (34.0, 33.5),
            32.8,
            (105.0, 98.0),
            92.0,
            (35.0, 34.0),
            33.0,
            default,
            ("P2", "P3", "P6"),
            ("thermal", "falling", "above_target"),
        ),
        RankingCase(
            "thermally_acceptable_high_power",
            (32.0, 32.0),
            32.0,
            (120.0, 123.0),
            126.0,
            (29.0, 29.0),
            29.0,
            default,
            ("P3", "P4", "P5", "P6"),
            ("power", "near_target", "stable"),
        ),
        RankingCase(
            "stable_conditions",
            (32.0, 32.0),
            32.0,
            (80.0, 80.0),
            80.0,
            (28.0, 28.0),
            28.0,
            default,
            ("P3", "P4", "P6"),
            ("stable", "thermal", "power"),
        ),
    ]


def fixture(
    case: RankingCase,
) -> tuple[Any, ControllerState]:
    state = ControllerState(
        current_supervisor_policy=case.current_policy,
        supervisor_policy_age_hours=3.0,
    )
    for index in range(2):
        state.append_building_state(
            make_state(
                timestep=index + 1,
                zone_temperature=case.history_zone_c[index],
                power_kw=case.history_power_kw[index],
                hvac_power_kw=case.history_power_kw[index] * 0.18,
                outdoor_temperature=case.history_outdoor_c[index],
                timestep_duration_hours=1.0,
            )
        )
    current = make_state(
        timestep=3,
        zone_temperature=case.current_zone_c,
        power_kw=case.current_power_kw,
        hvac_power_kw=case.current_power_kw * 0.18,
        outdoor_temperature=case.current_outdoor_c,
        timestep_duration_hours=1.0,
    )
    return current, state


def run(model: str, base_url: str, output_dir: Path) -> dict[str, Any]:
    model_info = _installed_model(model, base_url)
    loaded_before = _api_models(base_url, "/api/ps")
    if loaded_before:
        raise RuntimeError(
            "Candidate ranking test requires an empty loaded-model state"
        )
    client = OllamaLLMClient(
        model=model,
        base_url=base_url,
        connect_timeout_s=3.0,
        response_timeout_s=20.0,
        temperature=0.0,
        stream=False,
        json_mode=True,
        keep_alive="5m",
        seed=42,
        max_output_tokens=128,
        response_schema=CANDIDATE_RANKING_RESPONSE_SCHEMA,
    )
    ranker = LLMPolicyRanker(
        client,
        PolicyValidator(),
        provider="ollama",
        model=model,
    )
    rows: list[dict[str, Any]] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    partial = output_dir / "candidate_ranking_partial.json"
    for case in cases():
        print(f"[Candidate Ranking] {case.case_id}", flush=True)
        current, controller_state = fixture(case)
        result = ranker.recommend(current, controller_state, {})
        supplied = tuple(
            item.candidate_id for item in result.candidate_set.candidates
        )
        parsed = result.parsed_ranking
        raw = result.raw_response
        ranking_valid = bool(
            parsed
            and len(parsed.ranking) == len(supplied)
            and len(set(parsed.ranking)) == len(supplied)
            and set(parsed.ranking) == set(supplied)
            and parsed.selected_policy_id == parsed.ranking[0]
        )
        ranking_all_only = bool(
            parsed
            and len(parsed.ranking) == len(supplied)
            and len(set(parsed.ranking)) == len(supplied)
            and set(parsed.ranking) == set(supplied)
        )
        unknown_attempt = bool(
            parsed and any(item not in supplied for item in parsed.ranking)
        )
        selected_matches_first = bool(
            parsed and parsed.selected_policy_id == parsed.ranking[0]
        )
        reason = parsed.reason if parsed else ""
        row = {
            "case_id": case.case_id,
            "exact_model_tag": model,
            "summary": asdict(result.state_summary),
            "expected_candidate_ids": list(case.expected_candidate_ids),
            "candidate_ids": list(supplied),
            "candidate_set_correct": supplied == case.expected_candidate_ids,
            "deterministic_recommendation_id": (
                result.candidate_set.deterministic_recommendation_id
            ),
            "forced_single_candidate": result.forced_single_candidate,
            "llm_called": result.llm_called,
            "raw_response": raw,
            "strict_json_success": (
                not result.llm_called or parsed is not None
            ),
            "ranking_membership_valid": (
                not result.llm_called or ranking_valid
            ),
            "ranking_contains_all_and_only_candidates": (
                not result.llm_called or ranking_all_only
            ),
            "unknown_candidate_attempt": unknown_attempt,
            "selected_id_equals_ranking_first": (
                not result.llm_called or selected_matches_first
            ),
            "selected_policy_id": (
                parsed.selected_policy_id if parsed else ""
            ),
            "confidence": parsed.confidence if parsed else None,
            "reason": reason,
            "reason_references_processed_facts": (
                not result.llm_called
                or any(
                    term in reason.lower()
                    for term in case.expected_reason_terms
                )
            ),
            "direct_or_numeric_policy_field_attempt": (
                _forbidden_output(raw)
            ),
            "fabricated_occupancy_or_pmv": _fabricated(reason),
            "fallback_used": result.fallback_used,
            "failure_reason": result.failure_reason,
            "timeout": result.timeout,
            "parser_failure": result.parser_failure,
            "final_selected_policy_id": (
                result.selected_candidate.candidate_id
            ),
            "final_selection_belongs_to_candidate_set": (
                result.selected_candidate in result.candidate_set.candidates
            ),
            "final_policy_safe": (
                not PolicyValidator().validate(result.policy).corrected
            ),
            "response_latency_s": result.response_time_s,
            "transport_metadata": client.last_transport_metadata,
        }
        rows.append(row)
        partial.write_text(
            json.dumps(
                {"status": "running", "results": rows},
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
    actual = [row for row in rows if row["llm_called"]]
    latencies = [float(row["response_latency_s"]) for row in actual]
    criteria = {
        "six_cases_completed": len(rows) == 6,
        "one_forced_case_skipped_llm": (
            rows[0]["forced_single_candidate"]
            and not rows[0]["llm_called"]
        ),
        "candidate_sets_match_fixed_rules": all(
            row["candidate_set_correct"] for row in rows
        ),
        "all_actual_calls_strict_json": all(
            row["strict_json_success"] for row in actual
        ),
        "all_rankings_complete_and_bounded": all(
            row["ranking_membership_valid"] for row in actual
        ),
        "no_forbidden_output_fields": not any(
            row["direct_or_numeric_policy_field_attempt"] for row in actual
        ),
        "no_unknown_candidate_ids": all(
            not row["unknown_candidate_attempt"] for row in actual
        ),
        "selected_id_equals_ranking_first": all(
            row["selected_id_equals_ranking_first"] for row in actual
        ),
        "all_final_selections_bounded": all(
            row["final_selection_belongs_to_candidate_set"] for row in rows
        ),
        "safe_fallback_behavior": all(
            row["final_selection_belongs_to_candidate_set"] for row in rows
        ),
        "no_occupancy_pmv_fabrication": not any(
            row["fabricated_occupancy_or_pmv"] for row in actual
        ),
        "reasons_reference_processed_facts": all(
            row["reason_references_processed_facts"] for row in actual
        ),
        "timeouts_zero": not any(row["timeout"] for row in actual),
        "latency_below_20_seconds": bool(latencies)
        and max(latencies) < 20.0,
        "all_final_policies_safe": all(
            row["final_policy_safe"] for row in rows
        ),
    }
    payload = {
        "status": "pass" if all(criteria.values()) else "fail",
        "eligible_for_one_day_smoke_test": all(criteria.values()),
        "model": model_info,
        "loaded_models_before": loaded_before,
        "case_count": len(rows),
        "actual_llm_calls": len(actual),
        "forced_single_candidate_decisions": sum(
            bool(row["forced_single_candidate"]) for row in rows
        ),
        "average_latency_s": statistics.mean(latencies) if latencies else None,
        "median_latency_s": statistics.median(latencies) if latencies else None,
        "p95_latency_s": _p95(latencies),
        "maximum_latency_s": max(latencies) if latencies else None,
        "acceptance_criteria": criteria,
        "results": rows,
    }
    write_results(payload, output_dir)
    return payload


def write_results(payload: dict[str, Any], output_dir: Path) -> None:
    (output_dir / "qwen3_1_7b_candidate_ranking_results.json").write_text(
        json.dumps(payload, indent=2, default=str),
        encoding="utf-8",
    )
    lines = [
        "# Qwen3 1.7B Candidate Ranking Test",
        "",
        f"**{str(payload['status']).upper()}**",
        "",
        f"- Cases: {payload['case_count']}/6",
        f"- Actual LLM calls: {payload['actual_llm_calls']}",
        (
            "- Forced single-candidate decisions: "
            f"{payload['forced_single_candidate_decisions']}"
        ),
        f"- Median latency: {_seconds(payload['median_latency_s'])}",
        f"- Maximum latency: {_seconds(payload['maximum_latency_s'])}",
        "",
        "| Case | Candidates | LLM | Strict | Ranking valid | Final | Fallback | Latency |",
        "| --- | --- | --- | --- | --- | --- | --- | ---: |",
    ]
    for row in payload["results"]:
        lines.append(
            f"| {row['case_id']} | {','.join(row['candidate_ids'])} | "
            f"{row['llm_called']} | {row['strict_json_success']} | "
            f"{row['ranking_membership_valid']} | "
            f"{row['final_selected_policy_id']} | "
            f"{row['fallback_used']} | "
            f"{_seconds(row['response_latency_s'])} |"
        )
    lines.extend(["", "## Acceptance Criteria", ""])
    for key, passed in payload["acceptance_criteria"].items():
        lines.append(f"- {key}: `{passed}`")
    lines.extend(["", "## Manual Review", ""])
    for row in payload["results"]:
        if not row["llm_called"]:
            critique = (
                "Deterministic emergency rule forced the only safe option; "
                "this is not counted as LLM intelligence."
            )
        elif not row["strict_json_success"]:
            critique = (
                "The request produced no strict ranking; deterministic "
                f"{row['final_selected_policy_id']} was used. Failure: "
                f"{row['failure_reason']}"
            )
        else:
            critique = (
                f"Ranked only {', '.join(row['candidate_ids'])}; selected "
                f"{row['final_selected_policy_id']} with reason: "
                f"{row['reason']}"
            )
        lines.extend([f"### {row['case_id']}", "", critique, ""])
    (output_dir / "qwen3_1_7b_candidate_ranking_report.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def _installed_model(model: str, base_url: str) -> dict[str, Any]:
    with urlopen(f"{base_url.rstrip('/')}/api/tags", timeout=5) as response:
        models = json.load(response).get("models", [])
    found = next(
        (
            item
            for item in models
            if item.get("name") == model or item.get("model") == model
        ),
        None,
    )
    if found is None:
        raise RuntimeError(f"Installed model not found: {model}")
    return found


def _api_models(base_url: str, endpoint: str) -> list[dict[str, Any]]:
    with urlopen(f"{base_url.rstrip('/')}{endpoint}", timeout=5) as response:
        result = json.load(response).get("models", [])
    return result if isinstance(result, list) else []


def _forbidden_output(raw: str) -> bool:
    return bool(
        re.search(
            r'"(?:supply_air_temperature_setpoint|cooling_setpoint|'
            r'heating_setpoint|target_zone_temperature_c|'
            r'minimum_action_hold_intervals|policy_duration_hours|'
            r'thermal_priority|energy_priority|controller_aggressiveness|'
            r'actuator_key|actuator_handle|callback_name)"\s*:',
            raw,
            re.IGNORECASE,
        )
    )


def _fabricated(reason: str) -> bool:
    mentions = re.search(
        r"\b(occupancy|occupied|unoccupied|occupants?|pmv)\b",
        reason,
        re.IGNORECASE,
    )
    qualified = re.search(
        r"\b(unavailable|unknown|not available|not provided|false)\b",
        reason,
        re.IGNORECASE,
    )
    return bool(mentions and not qualified)


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return ordered[index]


def _seconds(value: Any) -> str:
    return "Unavailable" if value is None else f"{float(value):.3f} s"


def main() -> int:
    result = run(
        "qwen3:1.7b",
        "http://127.0.0.1:11434",
        ROOT / "test_reports",
    )
    print(
        f"[Candidate Ranking] status={result['status']} "
        f"eligible={result['eligible_for_one_day_smoke_test']}"
    )
    return 0 if result["eligible_for_one_day_smoke_test"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
