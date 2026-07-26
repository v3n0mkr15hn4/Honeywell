"""Guarded cold/warm admission test for qwen3:1.7b supervision."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from controller.policy_prompt_builder import build_policy_prompt  # noqa: E402
from controller.policy_validator import PolicyValidator  # noqa: E402
from ollama_supervisory_policy_benchmark import (  # noqa: E402
    benchmark_cases,
    build_fixture,
    create_client,
    evaluate_case,
    installed_models,
    run_fallback_self_test,
)


PRECHECK_CASE_IDS = (
    "strong_thermal_deterioration",
    "thermal_recovery",
    "high_energy_thermally_acceptable",
    "high_energy_and_overheating",
)


def _api_json(
    base_url: str,
    endpoint: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(
        f"{base_url.rstrip('/')}{endpoint}",
        data=data,
        headers=headers,
        method="POST" if payload is not None else "GET",
    )
    with urlopen(request, timeout=5) as response:
        result = json.load(response)
    if not isinstance(result, dict):
        raise RuntimeError(f"Unexpected Ollama response from {endpoint}")
    return result


def collect_environment(model: str, base_url: str) -> dict[str, Any]:
    models = installed_models(base_url)
    model_info = next(
        (
            item
            for item in models
            if item.get("name") == model or item.get("model") == model
        ),
        None,
    )
    if model_info is None:
        raise RuntimeError(f"Installed model not found: {model}")
    details = _api_json(base_url, "/api/show", {"model": model})
    version = _api_json(base_url, "/api/version").get("version", "unknown")
    loaded_before = _api_json(base_url, "/api/ps").get("models", [])
    return {
        "exact_model_tag": model,
        "ollama_version": version,
        "model": model_info,
        "model_details": details.get("details", {}),
        "cpu": platform.processor() or platform.machine(),
        "logical_cpu_count": os.cpu_count(),
        "ram_bytes": _physical_memory_bytes(),
        "gpu_availability": _gpu_summary(),
        "loaded_models_before_testing": loaded_before,
        "clean_loaded_state": loaded_before == [],
    }


def audit_prompt() -> dict[str, Any]:
    case = benchmark_cases()[0]
    state, controller_state, metrics = build_fixture(case)
    prompt = build_policy_prompt(
        state,
        controller_state,
        metrics,
        case.current_policy,
    )
    completed_object_marker = '{"thermal_priority"'
    required_statements = {
        "policy_only_role": "bounded high-level policy only" in prompt,
        "deterministic_physical_controller": (
            "RuleController converts validated policy" in prompt
        ),
        "multi_hour_policy": "remains active for several hours" in prompt,
        "avoid_unnecessary_changes": (
            "Avoid unnecessary policy changes" in prompt
        ),
        "occupancy_unavailable": "Occupancy: Unavailable" in prompt,
        "pmv_unavailable": "PMV: Unavailable" in prompt,
        "state_based_reason": "referencing relevant state" in prompt,
        "strict_json_only": "Return JSON only" in prompt,
        "direct_actuator_prohibited": (
            "Never return supply_air_temperature_setpoint" in prompt
        ),
    }
    return {
        "prompt_length": len(prompt),
        "completed_policy_example_present": completed_object_marker in prompt,
        "required_statements": required_statements,
        "passed": (
            completed_object_marker not in prompt
            and all(required_statements.values())
        ),
    }


def run_precheck(
    model: str,
    base_url: str,
    output_dir: Path,
    resume_after_cold_timeout: bool = False,
) -> dict[str, Any]:
    if resume_after_cold_timeout:
        result = _load_resumable_result(model, base_url, output_dir)
    else:
        environment = collect_environment(model, base_url)
        prompt_audit = audit_prompt()
        fallback_self_test = run_fallback_self_test(PolicyValidator())
        result = {
            "status": "running",
            "eligible_for_full_benchmark": False,
            "environment": environment,
            "prompt_audit": prompt_audit,
            "fallback_self_test": fallback_self_test,
            "requests": [],
        }
    if (
        not result["environment"]["clean_loaded_state"]
        and not resume_after_cold_timeout
    ) or not result["prompt_audit"]["passed"]:
        result["status"] = "fail"
        result["gate"] = _gate(result)
        write_results(result, output_dir)
        return result

    cases_by_id = {case.case_id: case for case in benchmark_cases()}
    client = create_client(model, base_url)
    validator = PolicyValidator()
    seen_policies: set[str] = set()
    seen_reasons: set[str] = set()
    start_index = len(result["requests"])
    for index, case_id in enumerate(
        PRECHECK_CASE_IDS[start_index:],
        start=start_index,
    ):
        phase = "cold" if index == 0 else "warm"
        print(f"[Supervisor Precheck] {phase} {case_id}", flush=True)
        row = evaluate_case(
            cases_by_id[case_id],
            model,
            client,
            validator,
        )
        row["request_phase"] = phase
        policy_key = json.dumps(row["policy_combination"], sort_keys=True)
        reason_key = " ".join(
            str((row.get("proposed_policy") or {}).get("reason", ""))
            .lower()
            .split()
        )
        row["repeated_policy"] = policy_key in seen_policies
        row["repeated_reason"] = bool(reason_key) and reason_key in seen_reasons
        seen_policies.add(policy_key)
        if reason_key:
            seen_reasons.add(reason_key)
        result["requests"].append(row)
        result["gate"] = _gate(result)
        write_results(result, output_dir)
        if (
            row["timeout"]
            or not row["strict_json_success"]
            or row["direct_actuator_field_attempt"]
            or row["unavailable_data_fabricated"]
        ):
            break

    loaded_after = _api_json(base_url, "/api/ps").get("models", [])
    result["environment"]["loaded_models_after_testing"] = loaded_after
    matching = [
        item
        for item in loaded_after
        if item.get("name") == model or item.get("model") == model
    ]
    result["environment"]["inference_backend"] = (
        "CPU-backed"
        if matching and sum(int(item.get("size_vram", 0)) for item in matching) == 0
        else "GPU-backed or mixed"
        if matching
        else "model not resident after requests"
    )
    result["gate"] = _gate(result)
    result["eligible_for_full_benchmark"] = all(
        result["gate"]["acceptance_criteria"].values()
    )
    result["status"] = (
        "pass" if result["eligible_for_full_benchmark"] else "fail"
    )
    write_results(result, output_dir)
    return result


def _load_resumable_result(
    model: str,
    base_url: str,
    output_dir: Path,
) -> dict[str, Any]:
    path = output_dir / "qwen3_1_7b_supervisor_precheck_results.json"
    result = json.loads(path.read_text(encoding="utf-8"))
    rows = result.get("requests", [])
    if (
        len(rows) != 1
        or rows[0].get("request_phase") != "cold"
        or not rows[0].get("timeout")
        or result["environment"].get("exact_model_tag") != model
    ):
        raise RuntimeError(
            "Precheck result is not a single resumable cold timeout"
        )
    loaded = _api_json(base_url, "/api/ps").get("models", [])
    unrelated = [
        item
        for item in loaded
        if item.get("name") != model and item.get("model") != model
    ]
    exact = [
        item
        for item in loaded
        if item.get("name") == model or item.get("model") == model
    ]
    if unrelated or len(exact) != 1:
        raise RuntimeError(
            "Expected exactly qwen3:1.7b resident before warm resume"
        )
    result["status"] = "running"
    result["eligible_for_full_benchmark"] = False
    result["environment"]["loaded_models_after_cold_timeout"] = loaded
    result["diagnostic_note"] = (
        "The single cold request timed out at the configured boundary, "
        "but Ollama confirmed the exact model was resident. The same "
        "recorded precheck continued with three sequential warm requests."
    )
    return result


def _gate(result: dict[str, Any]) -> dict[str, Any]:
    rows = result["requests"]
    warm = [row for row in rows if row.get("request_phase") == "warm"]
    warm_latencies = [
        float(row["response_latency_s"])
        for row in warm
        if row.get("response_latency_s") is not None
    ]
    unique_policies = {
        json.dumps(row["policy_combination"], sort_keys=True)
        for row in rows
        if row["strict_json_success"]
    }
    fallback = result["fallback_self_test"]
    loaded = (
        result["environment"].get("loaded_models_after_testing")
        or result["environment"].get("loaded_models_after_cold_timeout")
        or []
    )
    exact_model = result["environment"]["exact_model_tag"]
    model_resident = any(
        item.get("name") == exact_model or item.get("model") == exact_model
        for item in loaded
    )
    median_warm = (
        statistics.median(warm_latencies) if warm_latencies else None
    )
    criteria = {
        "model_loads": model_resident or (
            bool(rows) and rows[0]["strict_json_success"]
        ),
        "three_warm_requests_completed": len(warm) == 3,
        "warm_timeouts_zero": (
            len(warm) == 3 and not any(row["timeout"] for row in warm)
        ),
        "three_of_three_warm_strict_json": (
            len(warm) == 3
            and all(row["strict_json_success"] for row in warm)
        ),
        "direct_actuator_fields_zero": not any(
            row["direct_actuator_field_attempt"] for row in rows
        ),
        "safe_final_policies": bool(rows)
        and all(row["safe_validated_policy"] for row in rows),
        "fallback_functional": (
            fallback["previous_policy_fallback_success"]
            and fallback["default_policy_fallback_success"]
        ),
        "warm_median_below_20_seconds": (
            median_warm is not None and median_warm < 20.0
        ),
        "not_one_repeated_policy": len(unique_policies) >= 2,
        "occupancy_pmv_fabrication_zero": not any(
            row["unavailable_data_fabricated"] for row in rows
        ),
        "clean_initial_model_state": result["environment"][
            "clean_loaded_state"
        ],
        "prompt_leakage_audit_passed": result["prompt_audit"]["passed"],
    }
    return {
        "cold_latency_s": (
            rows[0]["response_latency_s"] if rows else None
        ),
        "warm_latencies_s": warm_latencies,
        "median_warm_latency_s": median_warm,
        "unique_policy_combinations": len(unique_policies),
        "acceptance_criteria": criteria,
    }


def write_results(result: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "qwen3_1_7b_supervisor_precheck_results.json"
    report_path = output_dir / "qwen3_1_7b_supervisor_precheck_report.md"
    json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    gate = result.get("gate", _gate(result))
    environment = result["environment"]
    lines = [
        "# Qwen3 1.7B Supervisor Precheck Report",
        "",
        f"**{str(result['status']).upper()}**",
        "",
        f"- Exact model tag: `{environment['exact_model_tag']}`",
        f"- Ollama version: `{environment['ollama_version']}`",
        f"- Model size: {environment['model'].get('size', 'unknown')} bytes",
        (
            "- Quantization: "
            f"`{environment['model_details'].get('quantization_level', 'unknown')}`"
        ),
        f"- CPU: {environment['cpu']}",
        f"- Logical CPUs: {environment['logical_cpu_count']}",
        f"- Physical RAM: {_bytes_gib(environment['ram_bytes'])}",
        f"- GPU: {environment['gpu_availability']}",
        (
            "- Inference backend: "
            f"{environment.get('inference_backend', 'not tested')}"
        ),
        (
            "- Loaded model state before testing: "
            f"`{environment['loaded_models_before_testing']}`"
        ),
        (
            "- Prompt completed-answer leakage: "
            f"`{result['prompt_audit']['completed_policy_example_present']}`"
        ),
        (
            "- Cold-start note: "
            + result.get(
                "diagnostic_note",
                "The cold request completed within its configured timeout.",
            )
        ),
        f"- Cold latency: {_seconds(gate['cold_latency_s'])}",
        (
            "- Warm latencies: "
            + ", ".join(_seconds(value) for value in gate["warm_latencies_s"])
        ),
        f"- Median warm latency: {_seconds(gate['median_warm_latency_s'])}",
        "",
        "| Phase | Case | Strict JSON | Safe | Fallback | Direct field | Fabrication | Repeated | Latency |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | ---: |",
    ]
    for row in result["requests"]:
        lines.append(
            f"| {row['request_phase']} | {row['case_id']} | "
            f"{row['strict_json_success']} | {row['safe_validated_policy']} | "
            f"{row['fallback_used']} | "
            f"{row['direct_actuator_field_attempt']} | "
            f"{row['unavailable_data_fabricated']} | "
            f"{row['repeated_policy']} | "
            f"{_seconds(row['response_latency_s'])} |"
        )
    lines.extend(["", "## Gate", ""])
    for key, passed in gate["acceptance_criteria"].items():
        lines.append(f"- {key}: `{passed}`")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _physical_memory_bytes() -> int | None:
    try:
        import psutil

        return int(psutil.virtual_memory().total)
    except (ImportError, AttributeError):
        if platform.system() != "Windows":
            return None

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_ulong),
            ("memory_load", ctypes.c_ulong),
            ("total_physical", ctypes.c_ulonglong),
            ("available_physical", ctypes.c_ulonglong),
            ("total_page_file", ctypes.c_ulonglong),
            ("available_page_file", ctypes.c_ulonglong),
            ("total_virtual", ctypes.c_ulonglong),
            ("available_virtual", ctypes.c_ulonglong),
            ("available_extended_virtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.length = ctypes.sizeof(MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return int(status.total_physical)


def _gpu_summary() -> str:
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        (
            "Get-CimInstance Win32_VideoController | "
            "Select-Object -ExpandProperty Name"
        ),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "Unavailable"
    names = [
        line.strip()
        for line in completed.stdout.splitlines()
        if line.strip()
        and "projection" not in line.lower()
        and "idd device" not in line.lower()
    ]
    return ", ".join(names) if names else "Unavailable"


def _bytes_gib(value: int | None) -> str:
    return "Unavailable" if value is None else f"{value / 1024**3:.2f} GiB"


def _seconds(value: Any) -> str:
    return "Unavailable" if value is None else f"{float(value):.3f} s"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="qwen3:1.7b")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument(
        "--resume-after-cold-timeout",
        action="store_true",
        help="Continue a recorded one-request cold timeout with warm calls.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "test_reports",
    )
    args = parser.parse_args()
    result = run_precheck(
        args.model,
        args.base_url,
        args.output_dir,
        resume_after_cold_timeout=args.resume_after_cold_timeout,
    )
    print(
        "[Supervisor Precheck] "
        f"status={result['status']} "
        f"eligible={result['eligible_for_full_benchmark']}",
        flush=True,
    )
    return 0 if result["eligible_for_full_benchmark"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
