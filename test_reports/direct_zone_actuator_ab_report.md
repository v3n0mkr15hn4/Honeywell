# Direct Zone Actuator A/B Report

## Candidate

- Component type: `Zone Temperature Control`
- Control type: `Cooling Setpoint`
- Actuator key: `MAIN ZONE`
- Callback: `begin_zone_before_init_heat_balance`
- Low command: 22.0 C
- High command: 30.0 C

## Runtime Verification

- Low handle: `72`
- High handle: `72`
- Low writes: `12672`
- High writes: `12672`
- Low samples: `9216`
- High samples: `9216`
- Commands written correctly: `True`
- Clean simulations: `True`

No `reset_actuator()` call is made. The override remains active after the first successful write and is refreshed at every selected callback.

## Physical Comparison

| Output | Units | Low mean | High mean | High-low mean | Max timestep delta | Direction sensible |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| zone_mean_air_temperature | C | 31.308306 | 31.308306 | 0.000000 | 0.000000 | False |
| zone_operative_temperature | C | 30.399266 | 30.399266 | 0.000000 | 0.000000 | False |
| zone_thermostat_cooling_setpoint | C | 22.000000 | 30.000000 | 8.000000 | 8.000000 | False |
| zone_air_sensible_cooling_rate | W | 73915.697190 | 73915.697190 | 0.000000 | 0.000000 | False |
| zone_predicted_cooling_load | W | -73915.675451 | -73915.675451 | 0.000000 | 0.000000 | False |
| cooling_coil_total_rate | W | 78151.273608 | 78151.273608 | 0.000000 | 0.000000 | False |
| cooling_coil_sensible_rate | W | 78151.273608 | 78151.273608 | 0.000000 | 0.000000 | False |
| cooling_coil_electricity_rate | W | 6891.908508 | 6891.908508 | 0.000000 | 0.000000 | False |
| facility_hvac_electricity_rate | W | 11125.766521 | 11125.766521 | 0.000000 | 0.000000 | False |
| facility_electricity_rate | W | 87169.069091 | 87169.069091 | 0.000000 | 0.000000 | False |
| zone_cooling_setpoint_not_met_time | hr | 0.000000 | 0.000000 | 0.000000 | 0.000000 | False |
| supply_outlet_temperature | C | 23.181714 | 23.181714 | 0.000000 | 0.000000 | False |
| supply_outlet_setpoint_temperature | C | 23.181714 | 23.181714 | 0.000000 | 0.000000 | False |
| cooling_coil_outlet_temperature | C | 22.730110 | 22.730110 | 0.000000 | 0.000000 | False |
| cooling_coil_outlet_setpoint_temperature | C | 22.730110 | 22.730110 | 0.000000 | 0.000000 | False |

## Pass Criteria

- Both simulations exit with code 0 and zero severe errors.
- Both runs resolve the actuator and write distinct values.
- At least one physical output exceeds 0.1 C, or exceeds 1% / 100 W for rates, at timestep or aggregate level.
- The detected change must have a physically sensible direction.

## Result

- Sensible physical effects: `[]`
- **FAIL**
