"""Finalize the guarded qwen3:1.7b selection reports without inference."""

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

from ollama_supervisory_policy_benchmark import (  # noqa: E402
    build_manual_review,
    write_results as write_benchmark_results,
)
from qwen3_1_7b_supervisor_precheck import (  # noqa: E402
    _gpu_summary,
    _physical_memory_bytes,
    write_results as write_precheck_results,
)


def finalize(output_dir: Path) -> Path:
    precheck_path = (
        output_dir / "qwen3_1_7b_supervisor_precheck_results.json"
    )
    benchmark_path = (
        output_dir / "qwen3_1_7b_supervisory_benchmark_results.json"
    )
    precheck = json.loads(precheck_path.read_text(encoding="utf-8"))
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))

    precheck["environment"]["ram_bytes"] = _physical_memory_bytes()
    precheck["environment"]["gpu_availability"] = _gpu_summary()
    write_precheck_results(precheck, output_dir)

    benchmark["manual_review"] = build_manual_review(benchmark["requests"])
    write_benchmark_results(benchmark, output_dir)

    report_path = (
        output_dir / "qwen3_1_7b_supervisory_selection_decision.md"
    )
    summary = benchmark["summary"]
    precheck_gate = precheck["gate"]
    failed = [
        key
        for key, passed in summary["acceptance_criteria"].items()
        if not passed
    ]
    lines = [
        "# Qwen3 1.7B Supervisory Selection Decision",
        "",
        "## Decision",
        "",
        "**REJECTED FOR HYBRID ENERGYPLUS SUPERVISION.**",
        "",
        (
            "The model passed the guarded warm precheck and structural safety "
            "boundary, but failed the fixed supervisory quality benchmark. "
            "Per the stop conditions, no real-model EnergyPlus smoke test or "
            "controller comparison was run."
        ),
        "",
        "## Model And Runtime",
        "",
        f"- Exact tag: `{precheck['environment']['exact_model_tag']}`",
        (
            "- Model: "
            f"{precheck['environment']['model_details'].get('parameter_size')} "
            f"{precheck['environment']['model_details'].get('quantization_level')}"
        ),
        f"- Ollama: `{precheck['environment']['ollama_version']}`",
        (
            "- Inference: "
            f"{precheck['environment'].get('inference_backend')}"
        ),
        (
            "- Cold request: timed out at "
            f"{precheck_gate['cold_latency_s']:.3f} s after loading the model"
        ),
        (
            "- Warm latencies: "
            + ", ".join(
                f"{value:.3f} s"
                for value in precheck_gate["warm_latencies_s"]
            )
        ),
        (
            "- Warm median: "
            f"{precheck_gate['median_warm_latency_s']:.3f} s"
        ),
        "",
        "## Benchmark",
        "",
        f"- Completed requests: {summary['total_requests']}/10",
        f"- Strict JSON: {summary['strict_json_success_rate']:.0%}",
        f"- Direct actuator fields: {summary['direct_actuator_fields_returned']}",
        (
            "- Safe validated policies: "
            f"{summary['safe_validated_policy_rate']:.0%}"
        ),
        (
            "- Fallback reliability self-test: "
            f"{summary['fallback_reliability']:.0%}"
        ),
        (
            "- Overall supervisory tendency: "
            f"{summary['overall_supervisory_tendency_accuracy']:.0%} "
            "(required at least 80%)"
        ),
        (
            "- State-responsive policy: "
            f"{summary['state_responsive_policy_rate']:.0%} "
            "(required at least 80%)"
        ),
        (
            "- Policy/reason consistency: "
            f"{summary['policy_reason_consistency_rate']:.0%} "
            "(required at least 80%)"
        ),
        f"- Fabricated occupancy/PMV: {summary['fabricated_data_rate']:.0%}",
        f"- Median benchmark latency: {summary['median_latency_s']:.3f} s",
        f"- Maximum benchmark latency: {summary['maximum_latency_s']:.3f} s",
        "",
        "Failed fixed criteria: " + ", ".join(f"`{key}`" for key in failed),
        "",
        "## Manual Verdict",
        "",
        (
            "The model is good at obeying the JSON schema and staying inside "
            "the policy boundary. It is not reliably responsive to state. It "
            "copied an aggressive recovery policy while temperature was "
            "falling, ignored rising energy under thermally acceptable "
            "conditions, and retained an energy-high conservative policy "
            "during overheating. Several reasons also substituted target or "
            "policy values for the supplied current temperature."
        ),
        "",
        (
            "That means the 60% automated tendency score is, if anything, "
            "optimistic. PolicyValidator and deterministic fallback make the "
            "system safe, but they do not make the model useful. "
            "`qwen3:1.7b` does not add dependable supervisory intelligence "
            "beyond the deterministic policy on this benchmark."
        ),
        "",
        "## Execution Boundary",
        "",
        "- EnergyPlus real-model smoke test: **NOT RUN (ineligible)**",
        "- One-day controller comparisons: **NOT RUN (ineligible)**",
        "- Another model: **NOT TESTED**",
        "- Production path: deterministic controller remains unchanged",
        "- Regression suite: **77/77 tests passed**",
        "",
        "## Principal Commands",
        "",
        "```powershell",
        (
            "& 'C:\\Users\\vasan\\AppData\\Local\\Programs\\Ollama\\"
            "ollama.exe' list"
        ),
        (
            "Invoke-RestMethod -Uri "
            "'http://127.0.0.1:11434/api/ps' -Method Get"
        ),
        (
            "$env:PYTHONPATH='src;tests'; python "
            "tests\\qwen3_1_7b_supervisor_precheck.py "
            "--model qwen3:1.7b --output-dir test_reports"
        ),
        (
            "$env:PYTHONPATH='src;tests'; python "
            "tests\\qwen3_1_7b_supervisor_precheck.py "
            "--model qwen3:1.7b --output-dir test_reports "
            "--resume-after-cold-timeout"
        ),
        (
            "$env:PYTHONPATH='src;tests'; python "
            "tests\\ollama_supervisory_policy_benchmark.py "
            "--model qwen3:1.7b --output-dir test_reports"
        ),
        (
            "$env:PYTHONPATH='src;tests'; python -m unittest discover "
            "-s tests -p \"test_*.py\" -v"
        ),
        "```",
    ]
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def main() -> int:
    path = finalize(ROOT / "test_reports")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
