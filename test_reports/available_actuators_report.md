# Available Cooling-Control Actuators

Source: EnergyPlus 26.1 `eplusout.edd` from the original schedule A/B run.
Names below are copied exactly from EnergyPlus.

| Candidate | Component type | Control type | Actuator key | Units | Related object | Expected effect | Override risk |
| --- | --- | --- | --- | --- | --- | --- | --- |
| schedule_cooling | Schedule:Compact | Schedule Value | COOLING RETURN AIR SETPOINT SCHEDULE | blank | ThermostatSetpoint:DualSetpoint | Change zone thermostat schedule | Does not reach active CRAC physics in measured run |
| direct_zone_cooling | Zone Temperature Control | Cooling Setpoint | MAIN ZONE | C | ZoneControl:Thermostat | Override zone cooling setpoint | Readback changes; active load path remained unchanged |
| supply_outlet_temperature | System Node Setpoint | Temperature Setpoint | SUPPLY OUTLET NODE | C | SetpointManager:Warmest | Override air-loop supply target | MixedAir propagation already completed after managers |
| coil_outlet_temperature | System Node Setpoint | Temperature Setpoint | MAIN COOLING COIL 1 OUTLET NODE | C | SetpointManager:MixedAir / CoilSystem:Cooling:DX | Directly control DX coil sensor-node target | MixedAir overwrites it unless Python writes after HVAC managers |
| zone_inlet_temperature | System Node Setpoint | Temperature Setpoint | MAIN ZONE INLET NODE | C | Main Zone VAV Air | Set terminal outlet target | Not the DX coil control node |
| atu_inlet_temperature | System Node Setpoint | Temperature Setpoint | MAIN ZONE ATU IN NODE | C | AirLoopHVAC:ZoneSplitter | Set branch inlet target | May be ignored by terminal/air-loop simulation |
| supply_schedule | Schedule:Compact | Schedule Value | SUPPLY AIR SETPOINT SCHEDULE | blank | Unused schedule | Change schedule value | IDF does not connect it to the active setpoint manager |
| airloop_availability | AirLoopHVAC | Availability Status | CRAC SYSTEM | blank | AirLoopHVAC | Enable/disable CRAC | Binary availability, not temperature control |
| system_availability_schedule | Schedule:Compact | Schedule Value | SYSTEM AVAILABILITY SCHEDULE | blank | AvailabilityManager:Scheduled | Enable/disable equipment | Binary availability, not temperature control |
| coil_capacity | Coil:Cooling:DX:SingleSpeed | Autosized Rated Total Cooling Capacity | MAIN COOLING COIL 1 | W | Coil:Cooling:DX:SingleSpeed | Alter autosized capacity | Model uses a hard-sized 148.3 kW value; unsafe as supervisory control |

The machine-readable version is
`test_reports/available_actuators.json`.
