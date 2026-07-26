# Policy-Aware Rule Controller Report

## Physical Authority

`PolicyAwareRuleController` alone translates validated high-level policy into
the physical node targets 22 C, 23 C, or 25 C. Policy never contains any of
those commands.

The controller derives deterministic thresholds from:

- zone thermal target;
- thermal priority;
- energy priority;
- conservative/normal/aggressive profile;
- current and previous zone temperature;
- validated minimum action-hold intervals.

High thermal priority and aggressive operation lower the response threshold.
High energy priority can cautiously raise the node target only below the high
thermal threshold. A zone temperature at least 1 C above the policy target is
treated as an emergency and may bypass the policy hold interval.

## Preserved Final Authority

Every proposed `ControlAction` is passed to the unchanged `SafetyValidator`.
The validator still enforces:

- 22.0-25.0 C physical node range;
- maximum 1.0 C change per physical decision;
- correction without throwing.

Policy cannot modify or bypass those constraints.

## Tests

Unit tests verify thermal and energy policy effects, target-dependent
thresholds, hold enforcement, and final physical safety.

Full EnergyPlus evidence shows different deterministic physical behavior:

- default policy: 1,536 applied setpoint changes;
- thermal-priority policy: 1 applied setpoint change;
- energy-priority policy: 919 changes and 459 final safety corrections;
- alternating policy: 787 changes and 394 final safety corrections.

These differences prove policy influences deterministic rules. They do not
represent direct LLM actuator control.
