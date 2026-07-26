# Validation Evidence

This directory contains concise, reviewable evidence from controller, NVIDIA
NIM, EnergyPlus, dashboard, and MCP validation. Reproducible EnergyPlus binary
outputs, process logs, caches, and multi-megabyte raw timestep dumps are
excluded from version control.

## Start Here

- `final_actuator_selection_report.md`: physically effective actuator and
  validated operating range
- `nvidia_nim_selection_decision.md`: guarded supervisory-model decision
- `nvidia_nim_one_day_smoke_test_report.md`: real one-day closed-loop run
- `hybrid_safety_boundary_report.md`: final deterministic authority
- `dashboard_readiness_report.md`: telemetry user interface validation
- `energyplus_mcp_integration_report.md`: real official-server integration
- `energyplus_mcp_agent_validation_report.md`: native tool-calling agent gate
- `mcp_final_readiness_decision.md`: honest MCP deployment boundary

The retained `nvidia_nim_one_day_output_20260726_184804` directory contains
only compact CSV telemetry, its text summary, and the EnergyPlus error log so
the dashboard can display a real completed run immediately after cloning.

## Scope

These reports prove integration, physical authority, safety boundaries, and
bounded agent behavior. They do not prove energy savings or occupant-comfort
improvement because no standard-scheduling A/B baseline with an aligned
comfort metric has been completed.
