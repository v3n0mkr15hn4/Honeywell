# Supervisor Policy Schema Report

## Exact Contract

| Field | Type | Allowed or validated range |
| --- | --- | --- |
| `thermal_priority` | enum string | `low`, `medium`, `high` |
| `energy_priority` | enum string | `low`, `medium`, `high` |
| `controller_aggressiveness` | enum string | `conservative`, `normal`, `aggressive` |
| `target_zone_temperature_c` | finite number | configurable, default 30.0-34.0 C |
| `minimum_action_hold_intervals` | integer | configurable, default 1-6 |
| `policy_duration_hours` | integer | configurable, default 4-12 hours |
| `strategy` | string | non-empty |
| `reason` | string | non-empty |

No physical actuator field is part of the schema. In particular, the parser
rejects `supply_air_temperature_setpoint`, `cooling_setpoint`,
`heating_setpoint`, unknown fields, actuator identifiers, and callback names.

## Parser And Validator Separation

`SupervisorOutputParser` rejects malformed JSON, markdown/prose wrappers,
missing or extra fields, wrong types, invalid enums, empty text, `NaN`, and
`Infinity`. It does not clamp.

`PolicyValidator` handles a structurally valid `SupervisorPolicy`:

- clamps policy numeric bounds;
- replaces invalid enums/non-finite values with previous or default values;
- limits target change to 1 C per policy update;
- limits hold-interval change to 2;
- limits duration change to 4 hours;
- records corrections and rejected fields;
- cannot alter physical SafetyValidator settings.

## Deterministic Default

```text
thermal_priority: high
energy_priority: medium
controller_aggressiveness: normal
target_zone_temperature_c: 32.0
minimum_action_hold_intervals: 2
policy_duration_hours: 6
strategy: balanced_default
```

This is a zone thermal target, not a human-comfort claim and not an actuator
setpoint.

## Failure Order

1. Reuse the current validated policy through its configured grace period.
2. Revert to the deterministic default after grace expires.
3. Continue deterministic physical control throughout.

Parser or inference failures never reach ActuatorWriter and never stop
EnergyPlus.
