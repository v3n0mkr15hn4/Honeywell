# NVIDIA NIM Selection Decision

## Decision

**PASS FOR GUARDED RESEARCH/DEMO USE; NOT PRODUCTION READY.**

The hosted NVIDIA boundary, strict candidate ranking, deterministic fallback, EnergyPlus integration, and physical safety path all completed successfully. This proves bounded integration viability. It does not prove better energy or thermal performance.

## Verification

- Full regression suite: `119/119` passed
- NVIDIA-focused client/provider tests: `9/9` passed
- Connection status: `pass`
- Connection request made: `True`
- Six-case ranking status: `pass`
- EnergyPlus one-day smoke test: `pass`
- EnergyPlus exit code: `0`
- EnergyPlus warnings/severe errors: `3` / `0`
- Control timesteps: `144`
- NVIDIA calls/successes: `8` / `8`
- Validated physical setpoint range: `22.0` to `23.0 C`
- Maximum validated physical change: `1.0 C`
- Physical safety corrections: `16`
- Average/maximum supervisory latency: `5.103727` / `7.651262` s
- Additional models: **NOT TESTED**

## Honest Interpretation

All eight real rankings were valid and safe, but all eight exactly matched the deterministic recommendation. The LLM demonstrated no distinct selection value in this run. Several explanations also overstated energy effects or made imprecise comparisons between candidates. Treat explanations as untrusted telemetry, not evidence.

The 16 safety corrections prove the physical rate limiter remained authoritative, but they also show frequent two-degree requests from the deterministic physical controller. The 100% zone-target violation metric is measured against a fixed 30 C threshold while the selected policy target was generally 32.5 C, so that KPI is not aligned with the supervisory target and cannot support an optimization claim.

No deterministic-only baseline was run. Do not claim energy savings, thermal improvement, autonomous optimization, occupant comfort optimization, or production readiness.

## Architecture Claim

A GPU-hosted NVIDIA NIM language model ranks dynamically generated safe HVAC supervisory policies using processed thermal, power, and environmental facts. Deterministic validation and control layers ensure that only admissible policies can influence physical actuation.
