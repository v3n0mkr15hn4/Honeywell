# Cooling-Coil Outlet Node Actuator A/B Report

## Candidate

- Component type: `System Node Setpoint`
- Control type: `Temperature Setpoint`
- Actuator key: `MAIN COOLING COIL 1 OUTLET NODE`
- Callback: `after_predictor_after_hvac_managers`
- Low command: 22.0 C
- High command: 25.0 C

## Runtime Verification

- Low handle: `100`
- High handle: `100`
- Low writes: `12734`
- High writes: `12756`
- Low samples: `9216`
- High samples: `9216`
- Commands written correctly: `True`
- Clean simulations: `True`

No `reset_actuator()` call is made. The override remains active after the first successful write and is refreshed at every selected callback.

## Physical Comparison

| Output | Units | Low mean | High mean | High-low mean | Max timestep delta | Direction sensible |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| zone_mean_air_temperature | C | 30.768246 | 34.438207 | 3.669961 | 4.221784 | True |
| zone_operative_temperature | C | 29.896806 | 33.385993 | 3.489187 | 4.072960 | True |
| zone_thermostat_cooling_setpoint | C | 31.000000 | 31.000000 | 0.000000 | 0.000000 | False |
| zone_air_sensible_cooling_rate | W | 70719.426563 | 83473.879549 | 12754.452986 | 13099.252489 | False |
| zone_predicted_cooling_load | W | -71997.024452 | -87885.232915 | -15888.208463 | 19231.483294 | False |
| cooling_coil_total_rate | W | 74632.132151 | 87771.219743 | 13139.087593 | 13973.013019 | False |
| cooling_coil_sensible_rate | W | 74632.132151 | 87771.219743 | 13139.087593 | 13973.013019 | False |
| cooling_coil_electricity_rate | W | 6428.945977 | 7508.940866 | 1079.994888 | 2634.010601 | False |
| facility_hvac_electricity_rate | W | 10342.146678 | 11804.011303 | 1461.864624 | 3566.954976 | False |
| facility_electricity_rate | W | 83113.455233 | 97852.904545 | 14739.449312 | 17008.079247 | False |
| zone_cooling_setpoint_not_met_time | hr | 0.080729 | 0.083333 | 0.002604 | 0.166667 | False |
| supply_outlet_temperature | C | 22.438410 | 25.455592 | 3.017182 | 3.053947 | True |
| supply_outlet_setpoint_temperature | C | 23.661926 | 24.859933 | 1.198007 | 2.431193 | False |
| cooling_coil_outlet_temperature | C | 22.000000 | 25.000000 | 3.000000 | 3.000000 | True |
| cooling_coil_outlet_setpoint_temperature | C | 22.000000 | 25.000000 | 3.000000 | 3.000000 | False |

## Pass Criteria

- Both simulations exit with code 0 and zero severe errors.
- Both runs resolve the actuator and write distinct values.
- At least one physical output exceeds 0.1 C, or exceeds 1% / 100 W for rates, at timestep or aggregate level.
- The detected change must have a physically sensible direction.

## Result

- Sensible physical effects: `['zone_mean_air_temperature', 'zone_operative_temperature', 'supply_outlet_temperature', 'cooling_coil_outlet_temperature']`
- **PASS**
