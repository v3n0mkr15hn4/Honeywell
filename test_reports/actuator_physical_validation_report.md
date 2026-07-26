# Actuator Physical Validation Report

## Configuration

- Run A: heating 18.0 C, cooling 22.0 C
- Run B: heating 18.0 C, cooling 30.0 C
- Same IDF, weather file, run period, timestep, initial conditions, schedules, and Runtime API callbacks.

## Commands Executed

- `$env:PYTHONPATH='src'; python tests\physical_ab_validation.py`

## Applied Actuator Values

- Run A first console-applied cooling values: [22.0, 22.0, 22.0, 22.0, 22.0, 22.0]
- Run B first console-applied cooling values: [30.0, 30.0, 30.0, 30.0, 30.0, 30.0]
- Different setpoints written: True

## Output Variables And Aggregate Differences

| Variable | Units | A Mean | B Mean | B-A Mean | Different |
| --- | --- | ---: | ---: | ---: | --- |
| Zone Mean Air Temperature | C | 31.308306 | 31.308306 | 0.000000 | False |
| Zone Operative Temperature | unavailable | | | | False |
| Facility Total Electricity Demand Rate | W | 87169.069091 | 87169.069091 | 0.000000 | False |
| Facility Total HVAC Electricity Demand Rate | W | 11125.766521 | 11125.766521 | 0.000000 | False |
| Cooling Coil Electricity Rate | W | 6891.908508 | 6891.908508 | 0.000000 | False |
| Cooling Coil Total Cooling Rate | W | 78151.273608 | 78151.273608 | 0.000000 | False |
| Cooling Coil Sensible Cooling Rate | W | 78151.273608 | 78151.273608 | 0.000000 | False |
| Zone Thermostat Control Type | unavailable | | | | False |
| Zone Cooling Setpoint Not Met Time | unavailable | | | | False |
| Cooling Return Air Setpoint Schedule:Schedule Value |  | 22.000977 | 30.000109 | 7.999132 | True |

## Sample Rows

Run A first CSV rows:

```json
[
  {
    "simulation_time": "2026-12-21 0.17 h (zone timestep #1)",
    "timestep": "1",
    "indoor_temperature": "30.846",
    "outdoor_temperature": "-18.800",
    "power": "102.611",
    "heating_setpoint": "18.000",
    "cooling_setpoint": "22.000",
    "indoor_temp_c": "30.846",
    "outdoor_temp_c": "-18.800",
    "occupancy": "",
    "pmv": "",
    "power_kw": "102.611",
    "cooling_coil_power_kw": "0.913",
    "strategy": "ab_cooling_22",
    "reason": "Fixed aggressive cooling setpoint for actuator physical A/B testing.",
    "heating_setpoint_c": "18.000",
    "cooling_setpoint_c": "22.000",
    "measured_heating_setpoint_c": "15.000",
    "measured_cooling_setpoint_c": "31.000",
    "validation_result": "valid",
    "controller_type": "LLMController",
    "llm_response_time_s": "0.000",
    "fallback_used": "False",
    "safety_corrected": "False",
    "validation_status": "valid"
  },
  {
    "simulation_time": "2026-12-21 0.33 h (zone timestep #2)",
    "timestep": "2",
    "indoor_temperature": "30.846",
    "outdoor_temperature": "-18.800",
    "power": "102.611",
    "heating_setpoint": "18.000",
    "cooling_setpoint": "22.000",
    "indoor_temp_c": "30.846",
    "outdoor_temp_c": "-18.800",
    "occupancy": "",
    "pmv": "",
    "power_kw": "102.611",
    "cooling_coil_power_kw": "0.913",
    "strategy": "ab_cooling_22",
    "reason": "Fixed aggressive cooling setpoint for actuator physical A/B testing.",
    "heating_setpoint_c": "18.000",
    "cooling_setpoint_c": "22.000",
    "measured_heating_setpoint_c": "18.000",
    "measured_cooling_setpoint_c": "22.000",
    "validation_result": "valid",
    "controller_type": "LLMController",
    "llm_response_time_s": "0.000",
    "fallback_used": "False",
    "safety_corrected": "False",
    "validation_status": "valid"
  },
  {
    "simulation_time": "2026-12-21 0.50 h (zone timestep #3)",
    "timestep": "3",
    "indoor_temperature": "30.846",
    "outdoor_temperature": "-18.800",
    "power": "102.611",
    "heating_setpoint": "18.000",
    "cooling_setpoint": "22.000",
    "indoor_temp_c": "30.846",
    "outdoor_temp_c": "-18.800",
    "occupancy": "",
    "pmv": "",
    "power_kw": "102.611",
    "cooling_coil_power_kw": "0.913",
    "strategy": "ab_cooling_22",
    "reason": "Fixed aggressive cooling setpoint for actuator physical A/B testing.",
    "heating_setpoint_c": "18.000",
    "cooling_setpoint_c": "22.000",
    "measured_heating_setpoint_c": "18.000",
    "measured_cooling_setpoint_c": "22.000",
    "validation_result": "valid",
    "controller_type": "LLMController",
    "llm_response_time_s": "0.000",
    "fallback_used": "False",
    "safety_corrected": "False",
    "validation_status": "valid"
  }
]
```

Run B first CSV rows:

```json
[
  {
    "simulation_time": "2026-12-21 0.17 h (zone timestep #1)",
    "timestep": "1",
    "indoor_temperature": "30.846",
    "outdoor_temperature": "-18.800",
    "power": "102.611",
    "heating_setpoint": "18.000",
    "cooling_setpoint": "30.000",
    "indoor_temp_c": "30.846",
    "outdoor_temp_c": "-18.800",
    "occupancy": "",
    "pmv": "",
    "power_kw": "102.611",
    "cooling_coil_power_kw": "0.913",
    "strategy": "ab_cooling_30",
    "reason": "Fixed relaxed cooling setpoint for actuator physical A/B testing.",
    "heating_setpoint_c": "18.000",
    "cooling_setpoint_c": "30.000",
    "measured_heating_setpoint_c": "15.000",
    "measured_cooling_setpoint_c": "31.000",
    "validation_result": "valid",
    "controller_type": "LLMController",
    "llm_response_time_s": "0.000",
    "fallback_used": "False",
    "safety_corrected": "False",
    "validation_status": "valid"
  },
  {
    "simulation_time": "2026-12-21 0.33 h (zone timestep #2)",
    "timestep": "2",
    "indoor_temperature": "30.846",
    "outdoor_temperature": "-18.800",
    "power": "102.611",
    "heating_setpoint": "18.000",
    "cooling_setpoint": "30.000",
    "indoor_temp_c": "30.846",
    "outdoor_temp_c": "-18.800",
    "occupancy": "",
    "pmv": "",
    "power_kw": "102.611",
    "cooling_coil_power_kw": "0.913",
    "strategy": "ab_cooling_30",
    "reason": "Fixed relaxed cooling setpoint for actuator physical A/B testing.",
    "heating_setpoint_c": "18.000",
    "cooling_setpoint_c": "30.000",
    "measured_heating_setpoint_c": "18.000",
    "measured_cooling_setpoint_c": "30.000",
    "validation_result": "valid",
    "controller_type": "LLMController",
    "llm_response_time_s": "0.000",
    "fallback_used": "False",
    "safety_corrected": "False",
    "validation_status": "valid"
  },
  {
    "simulation_time": "2026-12-21 0.50 h (zone timestep #3)",
    "timestep": "3",
    "indoor_temperature": "30.846",
    "outdoor_temperature": "-18.800",
    "power": "102.611",
    "heating_setpoint": "18.000",
    "cooling_setpoint": "30.000",
    "indoor_temp_c": "30.846",
    "outdoor_temp_c": "-18.800",
    "occupancy": "",
    "pmv": "",
    "power_kw": "102.611",
    "cooling_coil_power_kw": "0.913",
    "strategy": "ab_cooling_30",
    "reason": "Fixed relaxed cooling setpoint for actuator physical A/B testing.",
    "heating_setpoint_c": "18.000",
    "cooling_setpoint_c": "30.000",
    "measured_heating_setpoint_c": "18.000",
    "measured_cooling_setpoint_c": "30.000",
    "validation_result": "valid",
    "controller_type": "LLMController",
    "llm_response_time_s": "0.000",
    "fallback_used": "False",
    "safety_corrected": "False",
    "validation_status": "valid"
  }
]
```

## Investigation Notes

- The IDF references `Cooling Return Air Setpoint Schedule` through `ThermostatSetpoint:DualSetpoint`; the schedule name itself is not obviously wrong.
- The CSV confirms `Zone Thermostat Cooling Setpoint Temperature` changes from 22 C to 30 C after the first timestep.
- The ESO confirms `COOLING RETURN AIR SETPOINT SCHEDULE, Schedule Value` changes by about 8 C between runs.
- The EDD lists a more direct actuator: `MAIN ZONE, Zone Temperature Control, Cooling Setpoint, [C]`.
- The air loop is controlled by `SetpointManager:Warmest` with a 10 C to 25 C supply outlet setpoint range, which may dominate the CRAC behavior.
- The tested schedule actuator is therefore not proven to be the physically effective control point for this model.

## Final Conclusion

FAIL: The A/B test did not prove a physical EnergyPlus response. Do not proceed to Ollama performance comparisons.
