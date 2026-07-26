# EnergyPlus MCP Integration Report

## Scope

The official LBNL repository was cloned beside the project at commit
`5a7d3bb1d2e537ba329d3412c8b79d22cedd7c70`. Its source was not copied into
the application. The existing Runtime API controller and its physical
actuation path were not modified.

## Service

- Deployments tested: separate local HTTP process and Docker Compose
- Transport: Streamable HTTP
- Authentication: distinct locally generated bearer token
- Health endpoint: `{"status":"ok"}`
- MCP initialization: pass
- Official tools discovered: 35
- Required tools missing: 0
- Server-declared application version: 0.1.0
- EnergyPlus version: 26.1.0

Docker Desktop 4.83.0 was installed and tested with Docker Engine/CLI 29.6.2
and Compose 5.3.1. The official development image built successfully and the
`honeywell-energyplus-mcp-1` service reached Docker's healthy state.

The Compose deployment uses a non-root MCP service, an initialization service
that assigns its named virtual-environment volume to UID/GID 1000, and a
read-only HTTP health probe. The host simulation workspace is mounted at
`/workspace/simulation_workspace`.

An authenticated client session against the container discovered all 35
tools. A real IDF from run `7bc1ac40982341a7a2ce6c6f5078e980` was authorized
on its Windows host path, translated to the per-run Linux container path,
loaded, and validated successfully. Container path mapping is therefore
tested end to end, not only in unit tests.

## Upstream Compatibility Patch

The first real `validate_idf` call failed inside the official server:

```text
unsupported operand type(s) for +: 'Idf_MSequence' and 'Idf_MSequence'
```

A minimal patch was applied only in the separate official clone:

`energyplus_mcp_server/energyplus_tools.py`

The two eppy sequences used for material validation are converted to `list`
before concatenation. No behavior was bypassed. After restart, the same IDF
returned `is_valid: true`, zero warnings, and zero validation errors.

## Real Integration

Run ID: `7bc1ac40982341a7a2ce6c6f5078e980`

The known project IDF and EPW passed local package validation and were copied
into an isolated UUID workspace. Real calls succeeded for:

- `load_idf_model`
- `validate_idf`
- `get_model_summary`
- `list_zones`
- `check_simulation_settings`
- `get_output_variables`
- `get_output_meters`
- `discover_hvac_loops`
- `get_server_configuration`
- `run_energyplus_simulation`
- `create_interactive_plot`

The one EnergyPlus launch completed in 87.019 seconds. It produced 20 output
files, including CSV, meter CSV, SQL, HTML tabular output, the original error
log, and an interactive meter plot.

EnergyPlus result:

- Fatal errors: 0
- Severe errors: 0
- Warnings: 5
- Process result: successful

## Boundary

MCP manages uploaded-model inspection and standard simulations. It has no
reference to EnergyPlus Runtime API callbacks, sensor handles, actuator
handles, candidate policies, or physical setpoint limits. The validated
controller remains the only path that can write its known actuator.
