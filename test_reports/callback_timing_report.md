# Callback Timing Report

## Selected Timing

`callback_after_predictor_after_hvac_managers`

EnergyPlus setpoint managers have completed at this point, but HVAC equipment
has not yet consumed the final node targets for the current system timestep.
The selected node actuator is refreshed here on every system iteration. The
action itself was computed at the prior end-zone callback, preserving the
closed-loop one-zone-timestep delay.

## Timing Findings

| Callback | Tested | Finding |
| --- | --- | --- |
| Begin zone before set current weather | No | Earlier than weather and HVAC setpoint processing; unsuitable for final node override |
| Begin zone before init heat balance | Yes | Existing schedule callback; direct zone handle/readback changed, physical outputs did not |
| Begin zone after init heat balance | No | Still before HVAC setpoint managers |
| Begin system timestep before predictor | No | Node value would remain vulnerable to later managers |
| After predictor before HVAC managers | No | `Warmest` and `MixedAir` run afterward and can overwrite node targets |
| After predictor after HVAC managers | Yes | Supply-outlet write was too late to propagate; direct coil-outlet write changed physics |
| Inside HVAC system iteration loop | No | Later and more frequent than required after the post-manager test passed |
| End system timestep | No | Too late to influence the completed system timestep |
| End zone timestep | Yes, sensing only | Reads final state and computes/stores the next action |

## Timing Diagnostic

Each A/B case records:

- simulation timestamp
- callback name
- written command
- actuator readback
- thermostat cooling setpoint
- zone temperature
- supply-outlet temperature
- supply-outlet setpoint

Files are under:

`sampleSimulation/actuator_candidate_runs/<candidate>/<low|high>/timing_diagnostic.csv`

No production or test path calls `reset_actuator()`. The selected override is
refreshed after managers on each system iteration.
