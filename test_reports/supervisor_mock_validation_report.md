# Supervisor Mock Validation Report

Every physical action was produced by PolicyAwareRuleController and passed through the unchanged SafetyValidator.

| Scenario | Calls | Fallbacks | Policy corrections | Physical changes | Exit | Severe | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| default_policy_no_llm | 0 | 0 | 0 | 1536 | 0 | 0 | True |
| valid_balanced | 256 | 0 | 0 | 1536 | 0 | 0 | True |
| thermal_priority | 383 | 0 | 0 | 1 | 0 | 0 | True |
| energy_priority | 256 | 0 | 0 | 919 | 0 | 0 | True |
| unsafe_policy_corrected | 256 | 0 | 256 | 16 | 0 | 0 | True |
| invalid_enum_fallback | 66 | 256 | 0 | 1536 | 0 | 0 | True |
| direct_actuator_rejected | 66 | 256 | 0 | 1536 | 0 | 0 | True |
| malformed_json_fallback | 66 | 256 | 0 | 1536 | 0 | 0 | True |
| timeout_fallback | 66 | 256 | 0 | 1536 | 0 | 0 | True |
| expired_policy_fallback | 99 | 383 | 0 | 1536 | 0 | 0 | True |
| cooldown_behavior | 98 | 384 | 0 | 1536 | 0 | 0 | True |
| alternating_policy | 384 | 0 | 192 | 787 | 0 | 0 | True |

No real model was called. The supervisory contract contains no physical actuator setpoint field.

## Cross-Scenario Assertions

- Scenarios passed: 12/12
- EnergyPlus exit code 0: 12/12
- Zero severe errors: 12/12
- 9,216 deterministic physical decisions: 12/12
- Requested and validated physical actions inside 22-25 C: 12/12
- Physical 1 C rate limit respected: 12/12
- Applied node value matched the prior validated action: 9,215/9,215
  comparable timesteps in every scenario
- Direct actuator field attempt: rejected by strict policy parser
- Unsafe numeric policy: corrected on all 256 supervisory calls
- Timeout and malformed responses: deterministic control continued
- Expired policy: bounded grace, then default policy restored

EnergyPlus warnings ranged from 146 to 190 per run. These runs introduced zero
severe errors, but the warnings are not claimed to be eliminated or all caused
by the controller.

## Commands

```powershell
python tests\run_supervisor_integration_scenarios.py --scenario default_policy_no_llm --scenario valid_balanced
python tests\run_supervisor_integration_scenarios.py --aggregate-only --scenario default_policy_no_llm
python tests\run_supervisor_integration_scenarios.py --scenario valid_balanced
python tests\run_supervisor_integration_scenarios.py --scenario thermal_priority --scenario energy_priority --scenario unsafe_policy_corrected --scenario invalid_enum_fallback --scenario direct_actuator_rejected --scenario malformed_json_fallback --scenario timeout_fallback --scenario expired_policy_fallback --scenario cooldown_behavior --scenario alternating_policy
python tests\run_supervisor_integration_scenarios.py --aggregate-only
```

The first command completed the default-policy EnergyPlus run, then exposed a
new harness-only CSV inspection bug before the valid scenario started. The
harness incorrectly read `fieldnames` from the file object instead of
`csv.DictReader`. That defect was fixed; the completed run was aggregated
without rerunning it, and all scenarios then passed.
