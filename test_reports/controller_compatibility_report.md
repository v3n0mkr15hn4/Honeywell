# Controller Compatibility Report

## Sample Uploaded Model

- Standard simulation compatible: yes
- Closed-loop compatible: no
- Confirmed actuator target: none
- Simulation mode: Standard EnergyPlus

The uploaded IDF hash matches the validated project model, but that fact alone
does not establish an actuator handle in a separate Runtime API process.
Official MCP model inspection can find zones, outputs, meters, and HVAC
topology; it does not perform the validated Runtime API actuator-handle
discovery.

The analyser therefore refuses to confirm
`MAIN COOLING COIL 1 OUTLET NODE` without an explicit verified actuator
inventory. Node-name similarity and LLM output are never actuator authority.

## Existing Controller

The existing project run remains independently validated with:

- Component: System Node Setpoint
- Control: Temperature Setpoint
- Key: MAIN COOLING COIL 1 OUTLET NODE
- Range: 22-25 C
- Maximum physical decision change: 1 C

No files in `src/energyplus` or the existing controller pipeline were changed
for MCP integration.
