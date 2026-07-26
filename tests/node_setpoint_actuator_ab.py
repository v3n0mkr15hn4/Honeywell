"""A/B test for the CRAC supply-outlet node temperature setpoint actuator."""

from __future__ import annotations

import json
from pathlib import Path

from actuator_candidate_harness import (
    ActuatorCandidate,
    CallbackTiming,
    run_ab_test,
)
from direct_zone_actuator_ab import build_report


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = (
    WORKSPACE_ROOT
    / "sampleSimulation"
    / "actuator_candidate_runs"
    / "supply_outlet_temperature_setpoint"
)
REPORT_PATH = WORKSPACE_ROOT / "test_reports" / "node_setpoint_actuator_ab_report.md"
RESULT_PATH = WORKSPACE_ROOT / "test_reports" / "node_setpoint_actuator_ab_result.json"


def main() -> int:
    candidate = ActuatorCandidate(
        candidate_id="supply_outlet_temperature_setpoint",
        component_type="System Node Setpoint",
        control_type="Temperature Setpoint",
        actuator_key="SUPPLY OUTLET NODE",
        units="C",
        related_idf_object=(
            "SetpointManager:Warmest / Supply air control / Supply Outlet Node"
        ),
        expected_physical_effect=(
            "A lower supply-air target should lower actual supply temperature "
            "and increase DX cooling output and electricity."
        ),
        override_risk=(
            "SetpointManager:Warmest writes this node during HVAC manager "
            "processing, so Python must write after HVAC managers."
        ),
        low_value=12.0,
        high_value=25.0,
        callback_timing=CallbackTiming.AFTER_PREDICTOR_AFTER_HVAC_MANAGERS,
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
    report = build_report(result).replace(
        "# Direct Zone Actuator A/B Report",
        "# Node Setpoint Actuator A/B Report",
    ).replace(
        "- Low command: 22.0 C\n- High command: 30.0 C",
        "- Low command: 12.0 C\n- High command: 25.0 C",
    )
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(REPORT_PATH)
    print(f"PASS={result['pass']}")
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
