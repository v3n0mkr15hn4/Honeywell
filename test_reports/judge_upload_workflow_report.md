# Judge Upload Workflow Report

## Implemented Flow

1. The judge uploads loose allowlisted files or one ZIP on **Create
   Simulation**.
2. `SimulationPackageValidator` checks names, types, sizes, archive metadata,
   IDF/EPW cardinality, EnergyPlus version, headers, and schedule references.
3. `RunWorkspaceManager` creates a UUID workspace and a secret-free manifest.
4. The dashboard confirms MCP health and required tool inventory.
5. NVIDIA NIM receives only the assigned paths and allowlisted schemas.
6. Strict JSON tool requests pass through `MCPToolGuard`.
7. **Agent Activity** records observable reasons, validated argument summaries,
   duration, status, and sanitized results.
8. **Run Simulation** is disabled until an inspection result exists and is an
   explicit human action.
9. One approved MCP simulation writes only to that run's output directory.
10. **Simulation Results** shows error counts, original logs, compatible CSV
    charts, and safe downloads.

Refreshes do not automatically submit jobs. `SimulationJobManager` rejects
duplicate active launches and allows only one application-level simulation at
a time.

## Modes

Every arbitrary upload starts as `Standard EnergyPlus`. The dashboard does not
insert Runtime API control. `Closed-loop compatible` requires deterministic
proof of variables, meters, exact validated model identity, and the Runtime
API actuator inventory. MCP inspection alone cannot supply the final actuator
proof.

## Sample Bundle

`demo_assets/judge_upload_sample.zip` contains one EnergyPlus 26.1 IDF, one
EPW, and a README. The same contents passed the package validator without
source-code changes.
