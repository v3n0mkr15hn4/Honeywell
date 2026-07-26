# Three-Minute Judge Demonstration

1. Open the validated closed-loop dashboard and show the completed one-day
   telemetry.
2. Point out Runtime API feedback and forward supply-air setpoint injection.
3. Open **Create Simulation** and upload
   `demo_assets/judge_upload_sample.zip`.
4. Press **Validate package** and show the EnergyPlus 26.1 version gate.
5. Press **Validate model** and open **Agent Activity**.
6. Show NVIDIA-selected MCP calls for validation, zones, HVAC loops, outputs,
   meters, and simulation settings.
7. Return to **Create Simulation** and review the standard-simulation mode,
   output directory, timeout, and zero modifications.
8. Press **Run Simulation** once.
9. Open **Simulation Results** and show the EnergyPlus error log, counts,
   output files, and interactive plot download.
10. Show that closed-loop compatibility is false until actuator handles are
    deterministically verified.

Use this statement:

> The EnergyPlus MCP server gives the NVIDIA-hosted LLM standardized tools to
> inspect, validate and execute EnergyPlus simulations. Our separate Runtime
> API controller performs safe timestep-level feedback and setpoint injection
> for validated compatible models.
