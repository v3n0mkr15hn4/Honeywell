# EnergyPlus Supervisory Dashboard

This Streamlit dashboard is a read-only visualization of telemetry produced by
the existing EnergyPlus supervisory controller. It does not start or stop
EnergyPlus, call NVIDIA NIM, change policy configuration, or write actuator
values.

## Installation

From the project root:

```powershell
pip install -r requirements.txt
```

## Run

The dashboard automatically selects the newest NVIDIA one-day telemetry file:

```powershell
streamlit run dashboard/app.py
```

To select a specific CSV:

```powershell
$env:ENERGYPLUS_TELEMETRY_CSV="path\to\control_log.csv"
streamlit run dashboard/app.py
```

An optional expected timestep count can be supplied while watching an
in-progress run:

```powershell
$env:DASHBOARD_EXPECTED_TIMESTEPS="144"
```

## Demo Data

Demo mode creates sanitized synthetic telemetry in memory. It does not call
EnergyPlus or NVIDIA:

```powershell
$env:DASHBOARD_DEMO_MODE="true"
streamlit run dashboard/app.py
```

The page displays a `DEMO DATA` badge so synthetic and real telemetry cannot be
confused.

## Control Authority

NVIDIA NIM ranks safe candidate policy IDs. Strict deterministic validation
selects an admissible policy. `PolicyAwareRuleController` calculates each
physical supply-air setpoint, `SafetyValidator` enforces the 22-25 C range and
1 C maximum change, and `ActuatorWriter` applies the final value to EnergyPlus.

The dashboard observes this process from CSV telemetry and sibling report
files. It has no imports from the controller, actuator, EnergyPlus Runtime API,
or NVIDIA client packages.

## Uploaded Models

The root page remains the read-only validated closed-loop telemetry view.
Streamlit also exposes these pages:

- **Create Simulation** validates and isolates uploads, runs bounded MCP/NVIDIA
  inspection, and requires explicit simulation approval.
- **Agent Activity** shows observable tool requests and results without hidden
  model reasoning.
- **Simulation Results** shows run-scoped diagnostics, charts, and allowlisted
  downloads.
- **Run History** shows sanitized manifests only.

These pages call the separately running official EnergyPlus MCP service. They
do not import or alter the Runtime API actuator path. Start and configure the
service using the root `README.md` before opening uploaded-model pages.
