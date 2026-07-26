# Final Actuator Selection Report

## Selection

- Mode: `ActuatorControlMode.SUPPLY_NODE_SETPOINT`
- Component type: `System Node Setpoint`
- Control type: `Temperature Setpoint`
- Actuator key: `MAIN COOLING COIL 1 OUTLET NODE`
- Runtime handle in A/B runs: `100`
- Callback: `callback_after_predictor_after_hvac_managers`
- Production range: 22.0 C to 25.0 C
- A/B commands: 22.0 C and 25.0 C
- Exit status: both 0
- Severe errors: both 0
- Warnings: both 146, equal to the model's low-ambient baseline

## Physical Proof

| Physical output | 22 C mean | 25 C mean | 25-minus-22 | Maximum timestep difference |
| --- | ---: | ---: | ---: | ---: |
| Zone mean air temperature, C | 30.768246 | 34.438207 | +3.669961 | 4.221784 |
| Zone operative temperature, C | 29.896806 | 33.385993 | +3.489187 | 4.072960 |
| Supply-outlet temperature, C | 22.438410 | 25.455592 | +3.017182 | 3.053947 |
| Coil-outlet temperature, C | 22.000000 | 25.000000 | +3.000000 | 3.000000 |
| Cooling-coil electricity rate, W | 6428.945977 | 7508.940866 | +1079.994888 | 2634.010601 |
| Facility HVAC electricity rate, W | 10342.146678 | 11804.011303 | +1461.864624 | 3566.954976 |
| Facility electricity rate, W | 83113.455233 | 97852.904545 | +14739.449312 | 17008.079247 |

The lower leaving-air target produces lower supply and zone temperatures. The
electricity direction is model-specific: cooler supply also reduces the
temperature-dependent ITE load and VAV response, so total cooling and facility
power are lower in this data-center model.

## Rejected Candidates

- Cooling schedule, 22 C vs 30 C: thermostat schedule/readback changed; every physical output was identical.
- Direct `MAIN ZONE` cooling setpoint, 22 C vs 30 C: handle 72 and thermostat output changed; every physical output was identical.
- `SUPPLY OUTLET NODE`, 12 C vs 25 C after managers: node setpoint changed; downstream coil-outlet target and all physical outputs were identical.
- Selected node at 18 C: physically effective but produced about 32,000 flow/frost warnings.
- Selected node at 20 C: physically effective but produced 2,633 recurring frost-risk warnings.

## Production Integration

- `ActuatorWriter` is the only class calling `set_actuator_value()`.
- Legacy schedule and direct-zone targets remain available through configuration.
- The begin-zone callback still applies heating/schedule actions.
- The actuator-specific post-manager callback applies the previously computed cooling action.
- The end-zone callback still reads one `BuildingState`, decides, validates, stores, and logs the next action.
- `SensorReader` exposes the active coil-node setpoint separately from the zone thermostat setpoint.
- `PromptBuilder` names the actual DX coil outlet control point and its 22-25 C range.
- The complete ten-scenario mocked-controller suite passed with 0 severe errors, 9,216 telemetry samples, and 9,215 previous-action/node matches per scenario.

## Readiness

The actuator boundary is physically proven and protected by a warning-free
22-25 C safety envelope. It is safe for the next real-Ollama boundary test in
the software sense: malformed, unsafe, empty, exception, and timeout paths all
fall back or clamp correctly.

It is not evidence of comfort optimization, energy savings, or deployable
autonomous control. Average zone temperature is still high in several
controller scenarios, occupancy and PMV are unavailable, and no policy has
been tuned for this newly identified coil leaving-air control variable.
