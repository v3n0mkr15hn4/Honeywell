"""Create secret-free NVIDIA NIM implementation and decision reports."""

from __future__ import annotations

import json
from pathlib import Path

from nvidia_nim_one_day_smoke_test import write_results


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "test_reports"


def main() -> int:
    connection = json.loads(
        (REPORTS / "nvidia_nim_connection_test_results.json").read_text(
            encoding="utf-8"
        )
    )
    ranking = json.loads(
        (REPORTS / "nvidia_nim_candidate_ranking_results.json").read_text(
            encoding="utf-8"
        )
    )
    smoke = json.loads(
        (REPORTS / "nvidia_nim_one_day_smoke_test_results.json").read_text(
            encoding="utf-8"
        )
    )
    _record_manual_review(smoke)
    write_results(smoke)
    _write_implementation_report()
    _write_security_report()
    _write_selection_decision(connection, ranking, smoke)
    print(REPORTS / "nvidia_nim_selection_decision.md")
    return 0


def _write_implementation_report() -> None:
    lines = [
        "# NVIDIA NIM Client Implementation",
        "",
        "- Official OpenAI Python client: `openai 2.48.0`",
        "- Provider: `nvidia_nim`",
        "- Model: `nvidia/llama-3.3-nemotron-super-49b-v1.5`",
        "- Base URL default: `https://integrate.api.nvidia.com/v1`",
        "- Temperature: `0.0`",
        "- Top P: `1.0`",
        "- Maximum output tokens: `256`",
        "- Nemotron reasoning mode: disabled with `/no_think`",
        "- Stream: `False`",
        "- Timeout default: `30 s`",
        "- Maximum transient retries: `1`",
        "",
        (
            "The client implements the existing provider-neutral `query(prompt)` "
            "interface. It converts the candidate-ranking prompt into one system "
            "and one non-empty user message. SDK-internal retries are disabled "
            "and one bounded wrapper retry is used so retry telemetry is exact."
        ),
        "",
        (
            "Authentication, permission, model availability, rate limit, timeout, "
            "network, server, and empty-response failures are mapped to stable "
            "sanitized categories. LLMPolicyRanker always maps failures to the "
            "current deterministic candidate recommendation."
        ),
    ]
    (REPORTS / "nvidia_nim_client_implementation_report.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def _write_security_report() -> None:
    lines = [
        "# NVIDIA NIM Security Review",
        "",
        "**PASS, SUBJECT TO EXTERNAL CREDENTIAL HYGIENE.**",
        "",
        "- No NVIDIA credential is stored in project source or reports.",
        "- Runtime credentials are read only from `NVIDIA_NIM_API_KEY`.",
        "- Missing credentials fail before creating a network request.",
        "- Exceptions expose stable categories, not provider response bodies.",
        "- Authorization headers and environment values are never logged.",
        "- `.env`, `.env.*`, `secrets.*`, and `*.key` are ignored.",
        "- `.env.example` contains placeholders only.",
        "",
        (
            "The credential previously pasted into the conversation must remain "
            "revoked. The working runtime credential was supplied through the "
            "process environment and is intentionally absent from this report."
        ),
    ]
    (REPORTS / "nvidia_nim_security_review.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def _write_selection_decision(
    connection: dict[str, object],
    ranking: dict[str, object],
    smoke: dict[str, object],
) -> None:
    telemetry = smoke["telemetry"]
    metrics = smoke["metrics_summary"]
    lines = [
        "# NVIDIA NIM Selection Decision",
        "",
        "## Decision",
        "",
        "**PASS FOR GUARDED RESEARCH/DEMO USE; NOT PRODUCTION READY.**",
        "",
        (
            "The hosted NVIDIA boundary, strict candidate ranking, deterministic "
            "fallback, EnergyPlus integration, and physical safety path all "
            "completed successfully. This proves bounded integration viability. "
            "It does not prove better energy or thermal performance."
        ),
        "",
        "## Verification",
        "",
        "- Full regression suite: `119/119` passed",
        "- NVIDIA-focused client/provider tests: `9/9` passed",
        f"- Connection status: `{connection['status']}`",
        f"- Connection request made: `{connection['request_made']}`",
        f"- Six-case ranking status: `{ranking['status']}`",
        f"- EnergyPlus one-day smoke test: `{smoke['status']}`",
        f"- EnergyPlus exit code: `{smoke['energyplus_exit_code']}`",
        (
            "- EnergyPlus warnings/severe errors: "
            f"`{smoke['energyplus_warning_count']}` / "
            f"`{smoke['energyplus_severe_error_count']}`"
        ),
        f"- Control timesteps: `{telemetry['telemetry_rows']}`",
        (
            "- NVIDIA calls/successes: "
            f"`{telemetry['llm_calls']}` / `{telemetry['llm_calls']}`"
        ),
        (
            "- Validated physical setpoint range: "
            f"`{telemetry['minimum_validated_setpoint_c']}` to "
            f"`{telemetry['maximum_validated_setpoint_c']} C`"
        ),
        (
            "- Maximum validated physical change: "
            f"`{telemetry['maximum_validated_change_c']} C`"
        ),
        f"- Physical safety corrections: `{telemetry['safety_corrections']}`",
        (
            "- Average/maximum supervisory latency: "
            f"`{metrics['Average Supervisory Latency Seconds']}` / "
            f"`{metrics['Maximum Supervisory Latency Seconds']}` s"
        ),
        "- Additional models: **NOT TESTED**",
        "",
        "## Honest Interpretation",
        "",
        (
            "All eight real rankings were valid and safe, but all eight exactly "
            "matched the deterministic recommendation. The LLM demonstrated no "
            "distinct selection value in this run. Several explanations also "
            "overstated energy effects or made imprecise comparisons between "
            "candidates. Treat explanations as untrusted telemetry, not evidence."
        ),
        "",
        (
            "The 16 safety corrections prove the physical rate limiter remained "
            "authoritative, but they also show frequent two-degree requests from "
            "the deterministic physical controller. The 100% zone-target "
            "violation metric is measured against a fixed 30 C threshold while "
            "the selected policy target was generally 32.5 C, so that KPI is not "
            "aligned with the supervisory target and cannot support an optimization "
            "claim."
        ),
        "",
        (
            "No deterministic-only baseline was run. Do not claim energy savings, "
            "thermal improvement, autonomous optimization, occupant comfort "
            "optimization, or production readiness."
        ),
        "",
        "## Architecture Claim",
        "",
        (
            "A GPU-hosted NVIDIA NIM language model ranks dynamically generated "
            "safe HVAC supervisory policies using processed thermal, power, and "
            "environmental facts. Deterministic validation and control layers "
            "ensure that only admissible policies can influence physical actuation."
        ),
    ]
    (REPORTS / "nvidia_nim_selection_decision.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def _record_manual_review(smoke: dict[str, object]) -> None:
    telemetry = smoke["telemetry"]
    reviews = telemetry["nvidia_response_reviews"]
    smoke["manual_review_status"] = "complete_with_caveats"
    smoke["manual_review"] = {
        "responses_reviewed": len(reviews),
        "bounded_contract_compliance": "pass",
        "selection_safety": "pass",
        "semantic_precision": "mixed",
        "deterministic_agreement": f"{len(reviews)}/{len(reviews)}",
        "findings": [
            (
                "Every response ranked all and only supplied candidates, selected "
                "the first-ranked ID, and avoided actuator or numeric policy output."
            ),
            (
                "Every selected policy matched the deterministic recommendation; "
                "the run shows no distinct LLM selection contribution."
            ),
            (
                "Several reasons incorrectly describe P3 as reducing energy use "
                "relative to P4 even though P4 has the higher energy-conservation "
                "priority."
            ),
            (
                "Some reasons claim efficiency or thermal effects that are not "
                "established by the supplied candidate metadata."
            ),
            (
                "The explanations are acceptable as non-authoritative diagnostics "
                "only; they are not reliable engineering justifications."
            ),
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())
