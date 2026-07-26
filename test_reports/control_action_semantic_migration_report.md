# Control-Action Semantic Migration Report

## Result

**PASS**

The controller now consistently treats its command as the supply-air
temperature setpoint for the cooling-coil outlet node. No Ollama client or
external AI dependency was added.

## Semantic Correction

- Previous misleading term: `cooling_setpoint`
- New source-of-truth field: `supply_air_temperature_setpoint`
- Meaning: requested temperature setpoint for
  `MAIN COOLING COIL 1 OUTLET NODE`
- Physical direction: lower values generally produce colder supply air and
  stronger cooling; higher values generally reduce cooling.
- The command is not a zone thermostat or room-temperature target.

The `ControlAction.cooling_setpoint` property remains as a read-only legacy
alias. It returns `supply_air_temperature_setpoint`, so two independent values
cannot disagree. The strict LLM parser does not accept the legacy field.

## Proven EnergyPlus Boundary

- Component type: `System Node Setpoint`
- Control type: `Temperature Setpoint`
- Actuator key: `MAIN COOLING COIL 1 OUTLET NODE`
- Runtime callback: `callback_after_predictor_after_hvac_managers`
- Production range: 22.0 C to 25.0 C
- Maximum change: 1.0 C per decision

Callback registration, Runtime API handle resolution, and
`set_actuator_value()` placement were preserved. All actuator writes remain in
`ActuatorWriter`.

## Architecture

At each non-warmup zone timestep, sensors and telemetry are updated. The first
LLM-mode action comes from `RuleController`. A mocked LLM decision is requested
every six zone timesteps; intermediate timesteps reuse the previous validated
action. Parse/client failures use the rule fallback, and every newly requested
action passes through `SafetyValidator`.

`ControllerState` retains the previous validated action, previous validation
status, strategy, failure count, last LLM decision timestep, and a bounded
building-state history. The prompt includes current and previous node values,
zone-temperature and power trends, measured supply-air temperature, HVAC and
facility power, outdoor temperature, time, and previous decision context.

CSV telemetry separates:

- requested supply-air setpoint
- validated supply-air setpoint
- previously applied supply-air setpoint
- measured node setpoint
- measured supply-air temperature
- actual zone thermostat cooling setpoint
- safety correction, fallback, cadence, and reuse status

## Files Changed

Production modules:

- `src/controller/action.py`
- `src/controller/state.py`
- `src/controller/controller_state.py`
- `src/controller/prompt_builder.py`
- `src/controller/output_parser.py`
- `src/controller/safety.py`
- `src/controller/rule_controller.py`
- `src/controller/llm_controller.py`
- `src/controller/pipeline.py`
- `src/energyplus/config.py`
- `src/energyplus/sensors.py`
- `src/energyplus/actuators.py`
- `src/energyplus/runner.py`
- `src/llm/client.py`
- `src/telemetry/logger.py`
- `src/telemetry/metrics.py`

Validation modules:

- `tests/test_actuator_writer.py`
- `tests/test_llm_controller.py`
- `tests/test_logger.py`
- `tests/test_metrics.py`
- `tests/test_output_parser.py`
- `tests/test_pipeline.py`
- `tests/test_prompt_builder.py`
- `tests/test_rule_controller.py`
- `tests/test_safety.py`
- `tests/test_support.py`
- `tests/run_integration_scenarios.py`

## Validation

Python compilation succeeded for all files under `src/` and `tests/`.

The unit suite passed 45 of 45 tests. Coverage includes strict schema parsing,
legacy-field rejection, finite-number checks, physical clamping, rate limiting,
rule direction, decision cadence, startup behavior, warmup suppression,
fallback behavior, one-timestep action timing, telemetry labels, and metrics.

All 12 full mocked-controller EnergyPlus scenarios passed:

- rule baseline
- valid response
- unsafe low
- unsafe high
- malformed JSON
- missing field
- wrong type
- legacy wrong field
- empty response
- client exception
- timeout
- alternating setpoints

Each scenario produced 9,216 non-warmup sensor rows, exited with code 0, and
reported zero severe EnergyPlus errors. Successful LLM scenarios made 1,536
calls and reused 7,679 actions after the startup rule decision. Every expected fallback
occurred, unsafe values were corrected, measured/applied node values agreed,
and the one-zone-timestep closed-loop delay was preserved.

The independent physical A/B test also passed:

| Measurement | 22.0 C command | 25.0 C command | Difference |
| --- | ---: | ---: | ---: |
| Cooling-coil outlet temperature | 22.000 C | 25.000 C | 3.000 C |
| Supply outlet temperature | 22.438 C | 25.456 C | 3.017 C |
| Mean zone air temperature | 30.768 C | 34.438 C | 3.670 C |
| Mean facility HVAC demand | 10.342 kW | 11.804 kW | 1.462 kW |

Both A/B simulations exited cleanly, resolved the same actuator handle, and
reported zero severe errors.

## Commands

```powershell
$env:PYTHONPATH='src;tests'
Get-ChildItem -Recurse -Filter *.py src,tests |
    ForEach-Object { python -m py_compile $_.FullName }
python -m unittest discover -s tests -v

$env:PYTHONPATH='src'
python tests\run_integration_scenarios.py

$env:PYTHONPATH='src;tests'
python tests\coil_outlet_node_actuator_ab.py
```

## Remaining Limitations

The IDF contains `Timestep, 6`, so each zone timestep is 10 simulated minutes.
The configured interval is six timesteps, or one simulated hour.

Occupancy and PMV are unavailable from the current model/API variable set and
remain null in `BuildingState`; the prompt states when trend inputs are
unavailable.

The real Ollama transport was tested separately. The installed `qwen3:8b`
model failed its latency, JSON-reliability, and physical-direction gates, so no
real-model EnergyPlus smoke test was run.
