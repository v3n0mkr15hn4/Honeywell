# HVAC Control Path Report

## Active Model Path

```text
MAIN ZONE
  -> Main Zone Thermostat
  -> DualSetPoint schedules
  -> Main Zone Equipment
  -> Main Zone VAV Air
  -> CRAC system air loop
  -> Supply air control (SetpointManager:Warmest)
  -> Supply Outlet Node temperature setpoint
  -> Coil Exit Temp Manager 1 (SetpointManager:MixedAir)
  -> Main Cooling Coil 1 Outlet Node temperature setpoint
  -> DX Cooling Coil System 1 sensor node
  -> Main Cooling Coil 1
  -> EC Plug Fan 1
  -> Main Zone Inlet Node
```

## IDF Dependency Trace

- `ZoneControl:Thermostat / Main Zone Thermostat` controls `Main Zone` with `ThermostatSetpoint:DualSetpoint / DualSetPoint`.
- `DualSetPoint` references `Heating Setpoint Schedule` and `Cooling Return Air Setpoint Schedule`.
- `ZoneHVAC:EquipmentConnections / Main Zone` connects `Main Zone Inlet Node`, `Main Zone Node`, and `Main Zone Outlet Node`.
- `ZoneHVAC:EquipmentList / Main Zone Equipment` sequences `Main Zone ATU` first for cooling and an electric baseboard for heating.
- `AirTerminal:SingleDuct:VAV:NoReheat / Main Zone VAV Air` receives air from `Main Zone ATU In Node` and supplies `Main Zone Inlet Node`.
- `AirLoopHVAC / CRAC system` contains `DX Cooling Coil System 1` followed by `EC Plug Fan 1`.
- `CoilSystem:Cooling:DX / DX Cooling Coil System 1` explicitly uses `Main Cooling Coil 1 Outlet Node` as its sensor node.
- `SetpointManager:Warmest / Supply air control` writes `Supply Outlet Node` in the declared 10-25 C range.
- `SetpointManager:MixedAir / Coil Exit Temp Manager 1` derives the downstream `Main Cooling Coil 1 Outlet Node` target from `Supply Outlet Node`.
- `AvailabilityManager:Scheduled / CRAC 1 Avail` references `System Availability Schedule`, which is 1.0 all year.
- No outdoor-air-system component exists in the air-loop branch.

## Data-Center Behavior

- `ElectricEquipment:ITE:AirCooled / Data Center Servers` is in `Main Zone`.
- Design IT load is 500 W/unit x 100 units = 50 kW before schedule, curve, fan, and UPS effects.
- It uses `FlowControlWithApproachTemperatures` and `AdjustedSupply`, tied directly to `Main Zone Inlet Node`.
- The operation schedule is always 1.0. CPU loading is 1.0 in January and 0.1 in July, the two weather run periods.
- The explicit DX coil is rated at 148.3 kW with 8.5 m3/s rated airflow; the VAV terminal also has an 8.5 m3/s maximum.

## Proven Override Points

The thermostat schedule and direct zone actuator both changed the reported
thermostat cooling setpoint but did not change zone predicted cooling load,
air-loop output, coil output, or electricity. In this model/run, that path does
not govern the active CRAC response.

Writing `Supply Outlet Node` after HVAC managers changed that node's reported
setpoint, but `Main Cooling Coil 1 Outlet Node` retained the old value because
`SetpointManager:MixedAir` had already propagated the upstream target.

Writing `Main Cooling Coil 1 Outlet Node` after HVAC managers overrides the
last manager in the chain and directly changes the setpoint consumed by
`DX Cooling Coil System 1`. This produced large physical changes.

## Root Cause

The original schedule actuator was valid but ineffective for physical control.
The active DX coil is controlled by its outlet sensor-node target after
setpoint-manager processing. The thermostat schedule is therefore too far
upstream, and the post-manager supply-outlet write is too late to propagate
through `SetpointManager:MixedAir`.
