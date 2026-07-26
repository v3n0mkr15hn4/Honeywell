# LLM Mock Validation Report

Actuator-change definition: Option A, one changed ControlAction per applied timestep.
Cooling actuator: MAIN COOLING COIL 1 OUTLET NODE / System Node Setpoint / Temperature Setpoint.
Actuation callback: after predictor, after HVAC managers; the action computed at the prior zone timestep is applied.
Energy metric: Facility Total Electricity Demand Rate [W], converted to kW in SensorReader and integrated as kW * timestep hours.
PMV comfort threshold: abs(PMV) > 0.5 for occupied timesteps with valid PMV values.

| Test | Config | Expected | Actual | Pass |
| --- | --- | --- | --- | --- |
| rule | rule / valid | Rule controller baseline completes without LLM requests | exit=0, severe=0, decisions=9216, safety=0, failures=0, fallbacks=0 | True |
| llm_valid | llm / valid | Valid mocked LLM action is parsed, validated, stored, and applied | exit=0, severe=0, decisions=9216, safety=0, failures=0, fallbacks=0 | True |
| llm_unsafe | llm / unsafe | Unsafe JSON parses, safety corrects, corrected action is applied | exit=0, severe=0, decisions=9216, safety=9216, failures=0, fallbacks=0 | True |
| llm_malformed_json | llm / malformed_json | LLM failure is caught and RuleController fallback keeps simulation running | exit=0, severe=0, decisions=9216, safety=0, failures=9216, fallbacks=9216 | True |
| llm_missing_field | llm / missing_field | LLM failure is caught and RuleController fallback keeps simulation running | exit=0, severe=0, decisions=9216, safety=0, failures=9216, fallbacks=9216 | True |
| llm_wrong_type | llm / wrong_type | LLM failure is caught and RuleController fallback keeps simulation running | exit=0, severe=0, decisions=9216, safety=0, failures=9216, fallbacks=9216 | True |
| llm_empty_response | llm / empty_response | LLM failure is caught and RuleController fallback keeps simulation running | exit=0, severe=0, decisions=9216, safety=0, failures=9216, fallbacks=9216 | True |
| llm_exception | llm / exception | LLM failure is caught and RuleController fallback keeps simulation running | exit=0, severe=0, decisions=9216, safety=0, failures=9216, fallbacks=9216 | True |
| llm_timeout | llm / timeout | LLM failure is caught and RuleController fallback keeps simulation running | exit=0, severe=0, decisions=9216, safety=0, failures=9216, fallbacks=9216 | True |
| llm_alternating | llm / alternating | Alternating valid actions exercise actuator-change counting | exit=0, severe=0, decisions=9216, safety=4608, failures=0, fallbacks=0 | True |

## Commands Used

- `Get-ChildItem -Recurse -Filter *.py src,tests | ForEach-Object { python -m py_compile $_.FullName }`
- `$env:PYTHONPATH='src'; python -m unittest discover -s tests -v`
- `$env:PYTHONPATH='src'; python tests\run_integration_scenarios.py`

## Defects Found And Fixes Made

- Configurable mock LLM modes were added so success, unsafe output, parser failures, exceptions, timeouts, and alternating actions can be tested deterministically.
- `OutputParser` now rejects `NaN` and `Infinity` instead of accepting non-finite numeric values.
- `SafetyValidator` now preserves a configurable 1.0 C heating/cooling deadband after range and rate-limit checks.
- Metrics now report total integrated energy in kWh from sampled power instead of labeling average kW as energy consumption.
- Metrics now exclude invalid PMV values and report occupied comfort violation rate as unavailable when no valid occupied PMV data exists.
- CSV telemetry now includes explicit alias columns required by the validation checklist while preserving the previous unit-specific columns.
- Physical A/B testing rejected the schedule and direct-zone paths, then proved the DX coil outlet-node setpoint at the post-HVAC-manager callback.
- Production actuator selection is configuration-controlled; legacy schedule and direct-zone modes remain available.

## Final Assessment

The mocked LLM pipeline still passes through the physically proven actuator path. A real Ollama boundary test can proceed next, but these runs do not prove comfort optimization or energy savings.

## Result Files

- rule: summary `E:\SASTRA\Placement\On-Campus\Honeywell\sampleSimulation\llm_validation_runs\rule\control_summary.txt`, CSV `E:\SASTRA\Placement\On-Campus\Honeywell\sampleSimulation\llm_validation_runs\rule\control_log.csv`, console `E:\SASTRA\Placement\On-Campus\Honeywell\sampleSimulation\llm_validation_runs\rule\console.log`
- llm_valid: summary `E:\SASTRA\Placement\On-Campus\Honeywell\sampleSimulation\llm_validation_runs\llm_valid\control_summary.txt`, CSV `E:\SASTRA\Placement\On-Campus\Honeywell\sampleSimulation\llm_validation_runs\llm_valid\control_log.csv`, console `E:\SASTRA\Placement\On-Campus\Honeywell\sampleSimulation\llm_validation_runs\llm_valid\console.log`
- llm_unsafe: summary `E:\SASTRA\Placement\On-Campus\Honeywell\sampleSimulation\llm_validation_runs\llm_unsafe\control_summary.txt`, CSV `E:\SASTRA\Placement\On-Campus\Honeywell\sampleSimulation\llm_validation_runs\llm_unsafe\control_log.csv`, console `E:\SASTRA\Placement\On-Campus\Honeywell\sampleSimulation\llm_validation_runs\llm_unsafe\console.log`
- llm_malformed_json: summary `E:\SASTRA\Placement\On-Campus\Honeywell\sampleSimulation\llm_validation_runs\llm_malformed_json\control_summary.txt`, CSV `E:\SASTRA\Placement\On-Campus\Honeywell\sampleSimulation\llm_validation_runs\llm_malformed_json\control_log.csv`, console `E:\SASTRA\Placement\On-Campus\Honeywell\sampleSimulation\llm_validation_runs\llm_malformed_json\console.log`
- llm_missing_field: summary `E:\SASTRA\Placement\On-Campus\Honeywell\sampleSimulation\llm_validation_runs\llm_missing_field\control_summary.txt`, CSV `E:\SASTRA\Placement\On-Campus\Honeywell\sampleSimulation\llm_validation_runs\llm_missing_field\control_log.csv`, console `E:\SASTRA\Placement\On-Campus\Honeywell\sampleSimulation\llm_validation_runs\llm_missing_field\console.log`
- llm_wrong_type: summary `E:\SASTRA\Placement\On-Campus\Honeywell\sampleSimulation\llm_validation_runs\llm_wrong_type\control_summary.txt`, CSV `E:\SASTRA\Placement\On-Campus\Honeywell\sampleSimulation\llm_validation_runs\llm_wrong_type\control_log.csv`, console `E:\SASTRA\Placement\On-Campus\Honeywell\sampleSimulation\llm_validation_runs\llm_wrong_type\console.log`
- llm_empty_response: summary `E:\SASTRA\Placement\On-Campus\Honeywell\sampleSimulation\llm_validation_runs\llm_empty_response\control_summary.txt`, CSV `E:\SASTRA\Placement\On-Campus\Honeywell\sampleSimulation\llm_validation_runs\llm_empty_response\control_log.csv`, console `E:\SASTRA\Placement\On-Campus\Honeywell\sampleSimulation\llm_validation_runs\llm_empty_response\console.log`
- llm_exception: summary `E:\SASTRA\Placement\On-Campus\Honeywell\sampleSimulation\llm_validation_runs\llm_exception\control_summary.txt`, CSV `E:\SASTRA\Placement\On-Campus\Honeywell\sampleSimulation\llm_validation_runs\llm_exception\control_log.csv`, console `E:\SASTRA\Placement\On-Campus\Honeywell\sampleSimulation\llm_validation_runs\llm_exception\console.log`
- llm_timeout: summary `E:\SASTRA\Placement\On-Campus\Honeywell\sampleSimulation\llm_validation_runs\llm_timeout\control_summary.txt`, CSV `E:\SASTRA\Placement\On-Campus\Honeywell\sampleSimulation\llm_validation_runs\llm_timeout\control_log.csv`, console `E:\SASTRA\Placement\On-Campus\Honeywell\sampleSimulation\llm_validation_runs\llm_timeout\console.log`
- llm_alternating: summary `E:\SASTRA\Placement\On-Campus\Honeywell\sampleSimulation\llm_validation_runs\llm_alternating\control_summary.txt`, CSV `E:\SASTRA\Placement\On-Campus\Honeywell\sampleSimulation\llm_validation_runs\llm_alternating\control_log.csv`, console `E:\SASTRA\Placement\On-Campus\Honeywell\sampleSimulation\llm_validation_runs\llm_alternating\console.log`
