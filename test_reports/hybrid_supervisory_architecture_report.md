# Hybrid Supervisory Architecture Report

## Implemented Flow

Every zone control timestep:

```text
EnergyPlus
  -> SensorReader
  -> BuildingState + bounded ControllerState history
  -> PolicyAwareRuleController
  -> ControlAction
  -> SafetyValidator
  -> ActuatorWriter
  -> EnergyPlus
```

Every configured 4-6 simulated hours:

```text
BuildingState history + MetricsTracker snapshot + current policy
  -> PolicyPromptBuilder
  -> SupervisoryLLMController
  -> SupervisorOutputParser
  -> PolicyValidator
  -> validated SupervisorPolicy in ControllerState
```

The supervisor returns policy only. `PolicyAwareRuleController` is the only
hybrid component that creates `ControlAction`.

## Components

- `SupervisorPolicy`: immutable high-level guidance with no actuator fields.
- `SupervisorOutputParser`: exact JSON keys, types, finite values, and enums.
- `PolicyValidator`: configurable bounds and policy-to-policy change limits.
- `PolicyPromptBuilder`: several hours of state history, power, metrics, policy,
  expiry, and explicit policy-only authority.
- `SupervisoryLLMController`: query, parse, validate, timing, and deterministic
  previous/default fallback.
- `PolicyAwareRuleController`: deterministic thresholds, energy bias, and
  minimum physical-action hold.
- `ControlPipeline`: policy cadence/expiry/cooldown orchestration followed by a
  deterministic physical decision every timestep.
- `ControlLogger` and `MetricsTracker`: separate policy and physical evidence.

`ControllerState.history` remains bounded at 72 samples. With the proven six
timesteps per hour this retains up to 12 hours.

## Runtime Modes

- `rule`: existing RuleController with no supervisor.
- `hybrid_supervisory`: policy-aware deterministic physical control, with the
  supervisor enabled or disabled.
- Retired `llm` direct-actuator mode is rejected by the production runner.

The legacy direct-controller module remains in the repository for historical
tests, but it cannot be launched through `run_simulation`.

## Preserved EnergyPlus Boundary

No callback, SensorReader, ActuatorWriter, actuator key, component/control type,
handle initialization, or Runtime API call was changed. The proven callback
remains `callback_after_predictor_after_hvac_managers`.

## Readiness

Mock-only hybrid integration is complete. Real supervisory inference has not
been run and is not yet validated for policy quality or latency.

## Regression Commands

```powershell
$env:PYTHONPATH = "$(Resolve-Path 'src');$(Resolve-Path 'tests')"
python -m compileall -q src tests
python -m unittest discover -s tests -p 'test_*.py' -v
```

Final result: 73 tests passed.
