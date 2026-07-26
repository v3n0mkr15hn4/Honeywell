"""One guarded NVIDIA NIM connection test using a real candidate prompt."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "src", ROOT / "tests"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from candidate_test_support import ranker_controller_state  # noqa: E402
from controller.llm_policy_ranker import LLMPolicyRanker  # noqa: E402
from controller.policy_validator import PolicyValidator  # noqa: E402
from llm.nvidia_nim_client import NvidiaNIMClient  # noqa: E402
from test_support import make_state  # noqa: E402


MODEL = "nvidia/llama-3.3-nemotron-super-49b-v1.5"


def run(output_dir: Path) -> dict[str, Any]:
    if not os.environ.get("NVIDIA_NIM_API_KEY", "").strip():
        result = {
            "status": "blocked",
            "provider": "nvidia_nim",
            "model": MODEL,
            "request_made": False,
            "failure_category": "configuration_error",
            "message": (
                "NVIDIA_NIM_API_KEY is not configured. No network request "
                "was made."
            ),
        }
        write(result, output_dir)
        return result
    client = NvidiaNIMClient(MODEL)
    ranker = LLMPolicyRanker(
        client,
        PolicyValidator(),
        provider="nvidia_nim",
        model=MODEL,
    )
    result = ranker.recommend(
        make_state(
            zone_temperature=32.0,
            power_kw=125.0,
            hvac_power_kw=23.0,
        ),
        ranker_controller_state(),
        {},
    )
    payload = {
        "status": (
            "pass"
            if result.parsed_ranking is not None
            and result.selection is not None
            and not result.selection.invalid_ranking_fallback
            else "fail"
        ),
        "provider": "nvidia_nim",
        "model": MODEL,
        "request_made": True,
        "latency_s": result.response_time_s,
        "retry_count": result.llm_retry_count,
        "http_status_category": result.llm_http_status_category,
        "failure_category": result.llm_failure_category,
        "raw_content": result.raw_response,
        "strict_parsing_success": result.parsed_ranking is not None,
        "candidate_ids": [
            item.candidate_id for item in result.candidate_set.candidates
        ],
        "selected_policy_id": (
            result.parsed_ranking.selected_policy_id
            if result.parsed_ranking
            else ""
        ),
        "final_selected_policy_id": result.selected_candidate.candidate_id,
        "fallback_used": result.fallback_used,
        "final_policy_safe": (
            not PolicyValidator().validate(result.policy).corrected
        ),
    }
    write(payload, output_dir)
    return payload


def write(result: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "# NVIDIA NIM Connection Test",
        "",
        f"**{str(result['status']).upper()}**",
        "",
        f"- Provider: `{result['provider']}`",
        f"- Model: `{result['model']}`",
        f"- Request made: `{result['request_made']}`",
        (
            "- Failure category: "
            f"`{result.get('failure_category', '')}`"
        ),
    ]
    if result.get("request_made"):
        lines.extend(
            [
                f"- Latency: {result.get('latency_s', 0):.3f} s",
                f"- Retry count: {result.get('retry_count', 0)}",
                (
                    "- Strict parsing: "
                    f"`{result.get('strict_parsing_success')}`"
                ),
                (
                    "- Final selected candidate: "
                    f"`{result.get('final_selected_policy_id')}`"
                ),
                f"- Fallback: `{result.get('fallback_used')}`",
            ]
        )
    else:
        lines.append(f"- Result: {result.get('message', '')}")
    (output_dir / "nvidia_nim_connection_test_report.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    (output_dir / "nvidia_nim_connection_test_results.json").write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    result = run(ROOT / "test_reports")
    print(
        f"[NVIDIA Connection] status={result['status']} "
        f"request_made={result['request_made']}"
    )
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
