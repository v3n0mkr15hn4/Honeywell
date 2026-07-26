# Hybrid Supervisory Architecture Recommendation

## Recommendation

Keep `RuleController` as the only decision maker that can produce a physical
node setpoint:

```text
EnergyPlus
  -> SensorReader
  -> BuildingState + history
  -> RuleController(validated supervisory policy)
  -> SafetyValidator
  -> ActuatorWriter
```

An optional LLM may propose policy every 4-6 simulated hours. It must never
return or directly influence `supply_air_temperature_setpoint`.

## Supervisory Contract

```json
{
  "thermal_priority": "high",
  "energy_priority": "medium",
  "target_zone_temperature_c": 31.0,
  "hysteresis_width_c": 1.0,
  "controller_aggressiveness": "normal",
  "minimum_action_hold_intervals": 2,
  "strategy": "prioritize thermal recovery",
  "reason": "Zone temperature has been rising for several hours."
}
```

Allowed fields and validation:

| Field | Allowed value |
| --- | --- |
| `thermal_priority` | `low`, `medium`, `high` |
| `energy_priority` | `low`, `medium`, `high` |
| `target_zone_temperature_c` | finite 26.0-32.0 C, deployment-configurable |
| `hysteresis_width_c` | finite 0.5-2.0 C |
| `controller_aggressiveness` | `conservative`, `normal`, `aggressive` |
| `minimum_action_hold_intervals` | integer 1-4 |
| `strategy` | short non-empty string |
| `reason` | short non-empty state-based explanation |

The target range must remain configuration-owned and should be calibrated
against the validated IDF before implementation. It is policy guidance, not an
actuator range.

## Policy Validation

Use a dedicated `PolicyValidator` that never communicates with EnergyPlus:

- require exactly the approved fields and reject malformed JSON;
- reject non-finite values and unsupported enums;
- clamp numeric values to configured policy ranges;
- clamp hold intervals to integer bounds;
- record every correction;
- reject internally contradictory priority/strategy combinations;
- retain the last validated policy on timeout, parse failure, or rejected
  output;
- fall back to a conservative built-in default if no validated policy exists.

Policy failure must never invoke an LLM retry inside an EnergyPlus callback.

## RuleController Consumption

`RuleController` remains deterministic:

- zone error relative to `target_zone_temperature_c` selects the control band;
- `hysteresis_width_c` prevents rapid switching;
- thermal and energy priorities bias deterministic thresholds within tested
  limits;
- aggressiveness selects among predefined rule profiles, never arbitrary
  setpoints;
- hold intervals impose a minimum dwell time unless a deterministic emergency
  condition is active;
- every resulting node target still passes through the existing 22-25 C clamp
  and 1 C rate limit.

The LLM policy cannot disable hard limits, fallback, emergency rules, telemetry,
or validation.

## Cadence And State

- Request policy every 4-6 simulated hours, asynchronously where possible.
- Continue using the last validated policy while inference is pending.
- Store policy version, issue time, validation result, corrections, and source.
- Expire stale policy after a configured lifetime and revert to defaults.
- Log the rule action separately from the supervisory recommendation.

## Ranked Alternatives

1. RuleController controls the actuator; LLM supplies bounded low-frequency
   policy.
2. RuleController controls the actuator; LLM asynchronously explains results.
3. Use the LLM offline to generate candidate policies for deterministic tests.
4. Consider remote inference only when project rules and data policy allow it.

Options 2 and 3 are not real-time LLM control.

## Implementation Status

Design recommendation only. No supervisory policy classes, validators,
pipeline changes, callbacks, or EnergyPlus integrations were implemented.
