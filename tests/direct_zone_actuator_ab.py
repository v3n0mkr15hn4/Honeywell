"""Aggressive A/B test for the direct MAIN ZONE cooling setpoint actuator."""

from __future__ import annotations

import json
from pathlib import Path

from actuator_candidate_harness import (
    ActuatorCandidate,
    CallbackTiming,
    run_ab_test,
)


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = (
    WORKSPACE_ROOT
    / "sampleSimulation"
    / "actuator_candidate_runs"
    / "direct_zone_cooling_setpoint"
)
REPORT_PATH = WORKSPACE_ROOT / "test_reports" / "direct_zone_actuator_ab_report.md"
RESULT_PATH = WORKSPACE_ROOT / "test_reports" / "direct_zone_actuator_ab_result.json"


def main() -> int:
    candidate = ActuatorCandidate(
        candidate_id="direct_zone_cooling_setpoint",
        component_type="Zone Temperature Control",
        control_type="Cooling Setpoint",
        actuator_key="MAIN ZONE",
        units="C",
        related_idf_object="ZoneControl:Thermostat / Main Zone Thermostat",
        expected_physical_effect=(
            "Lower target should increase predicted cooling demand and reduce "
            "zone temperature or increase cooling output/electricity."
        ),
        override_risk=(
            "The air-loop SetpointManager:Warmest can constrain supply air, "
            "but this actuator directly overrides the zone cooling setpoint."
        ),
        low_value=22.0,
        high_value=30.0,
        callback_timing=CallbackTiming.BEGIN_ZONE_BEFORE_INIT_HEAT_BALANCE,
    )
    result = run_ab_test(
        energyplus_root=Path(r"C:\EnergyPlusV26-1-0"),
        idf_path=WORKSPACE_ROOT / "1ZoneDataCenterCRAC_wApproachTemp.idf",
        epw_path=(
            WORKSPACE_ROOT
            / "USA_CA_San.Francisco.Intl.AP.724940_TMY3.epw"
        ),
        output_root=OUTPUT_ROOT,
        candidate=candidate,
    )
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    REPORT_PATH.write_text(build_report(result), encoding="utf-8")
    print(REPORT_PATH)
    print(f"PASS={result['pass']}")
    return 0 if result["pass"] else 1


def build_report(result: dict[str, object]) -> str:
    candidate = result["candidate"]
    low = result["low_case"]
    high = result["high_case"]
    comparisons = result["output_comparisons"]
    assert isinstance(candidate, dict)
    assert isinstance(low, dict)
    assert isinstance(high, dict)
    assert isinstance(comparisons, dict)

    lines = [
        "# Direct Zone Actuator A/B Report",
        "",
        "## Candidate",
        "",
        f"- Component type: `{candidate['component_type']}`",
        f"- Control type: `{candidate['control_type']}`",
        f"- Actuator key: `{candidate['actuator_key']}`",
        f"- Callback: `{candidate['callback_timing']}`",
        "- Low command: 22.0 C",
        "- High command: 30.0 C",
        "",
        "## Runtime Verification",
        "",
        f"- Low handle: `{low['actuator_handle']}`",
        f"- High handle: `{high['actuator_handle']}`",
        f"- Low writes: `{low['write_count']}`",
        f"- High writes: `{high['write_count']}`",
        f"- Low samples: `{low['sample_count']}`",
        f"- High samples: `{high['sample_count']}`",
        f"- Commands written correctly: `{result['commands_written']}`",
        f"- Clean simulations: `{result['simulations_clean']}`",
        "",
        "No `reset_actuator()` call is made. The override remains active after "
        "the first successful write and is refreshed at every selected callback.",
        "",
        "## Physical Comparison",
        "",
        "| Output | Units | Low mean | High mean | High-low mean | "
        "Max timestep delta | Direction sensible |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for output_id, item in comparisons.items():
        assert isinstance(item, dict)
        if not item["available"]:
            lines.append(
                f"| {output_id} | {item['units']} | unavailable | unavailable "
                "| | | False |"
            )
            continue
        lines.append(
            f"| {output_id} | {item['units']} | "
            f"{number(item['low_mean'])} | {number(item['high_mean'])} | "
            f"{number(item['mean_delta_high_minus_low'])} | "
            f"{number(item['max_timestep_absolute_difference'])} | "
            f"{item['physically_sensible']} |"
        )

    lines.extend(
        [
            "",
            "## Pass Criteria",
            "",
            "- Both simulations exit with code 0 and zero severe errors.",
            "- Both runs resolve the actuator and write distinct values.",
            "- At least one physical output exceeds 0.1 C, or exceeds 1% / "
            "100 W for rates, at timestep or aggregate level.",
            "- The detected change must have a physically sensible direction.",
            "",
            "## Result",
            "",
            f"- Sensible physical effects: "
            f"`{result['sensible_physical_effects']}`",
            f"- **{'PASS' if result['pass'] else 'FAIL'}**",
            "",
        ]
    )
    return "\n".join(lines)


def number(value: object) -> str:
    if not isinstance(value, (int, float)):
        return ""
    return f"{float(value):.6f}"


if __name__ == "__main__":
    raise SystemExit(main())
