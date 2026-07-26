# Read-Only Dashboard Readiness

## Decision

**PASS FOR LOCAL DEMONSTRATION.**

The Streamlit dashboard reads existing CSV telemetry and sibling EnergyPlus
summary/error files. It has no dependency on controller, actuator, EnergyPlus
Runtime API, or NVIDIA client modules and exposes no control inputs.

## Delivered

- `dashboard/app.py`
- `dashboard/telemetry_loader.py`
- `dashboard/metrics_helpers.py`
- `dashboard/demo_data.py`
- `dashboard/README.md`
- Dashboard loader, metric, JSON parsing, and Streamlit smoke tests
- `requirements.txt` additions for pandas and Streamlit

## Verification

- Full project test suite: `129/129` passed
- Empty telemetry state: passed
- Synthetic demo state: passed
- Real one-day telemetry render: passed with zero Streamlit exceptions
- Real telemetry rows: `144`
- Dashboard NVIDIA calls/successes: `8/8`
- Dashboard strict rankings: `8`
- Dashboard policy changes: `3`
- Dashboard physical safety corrections: `16`
- Dashboard warning/severe counts: `3/0`
- Corrected operational thermal-target violation rate: `45.1%`
- Credential/API-header patterns in dashboard files: none

## Visual Description

The wide desktop layout opens with two compact rows of run-status metrics,
followed by current building values. Three trend views show zone temperature
against the active policy target, requested/validated/applied supply-air
control against the 22-25 C bounds, and HVAC/facility power.

The latest NVIDIA panel places deterministic recommendation, raw model
selection, and final validated selection side by side. Its candidate table
highlights selection roles, while model reasoning is explicitly labeled
advisory. A control-authority sequence, safety panel, filtered event table, and
cumulative run metrics complete the page.

## Commands

```powershell
python -m pip install -r requirements.txt
$env:PYTHONPATH='.;src;tests'
python -m unittest discover -s tests -p 'test_*.py' -q
python -m streamlit run dashboard/app.py --server.headless=true
```

## Limitations

- Live trend classifications are not persisted in the current CSV, so those
  widgets are omitted for real telemetry and shown only when fields exist.
- The dashboard does not infer occupant comfort from PMV because PMV is
  unavailable.
- Auto-refresh observes file updates; it does not control simulation lifecycle.
- The dashboard is intended for local demonstration, not an authenticated
  remote deployment.
