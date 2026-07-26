# EnergyPlus MCP Agent Validation Report

## Design

The agent uses NVIDIA's OpenAI-compatible endpoint with native function
calling and the `/no_think` directive. Authenticated MCP schemas are exposed
as model tools, and a separate `finish_task` function represents the terminal
response. The model must emit exactly one function call per step. Its
arguments are parsed as strict JSON and then pass through the existing
allowlist, JSON Schema, path-boundary, sequencing, and approval checks.
Arbitrary text, markdown, extra fields, code, and shell commands are never
executed.

Limits:

- Maximum steps: 10
- Maximum simulation launches: 1
- IDF modifications: 0
- Validation required before simulation: yes
- Human approval required before simulation: yes

Tool schemas come from the authenticated MCP server. The model does not receive
non-allowlisted modification, log-management, copy, or server-control tools.

## Results

Mocked boundary tests passed for the complete authorization flow, including
validation ordering, cross-run rejection, modification rejection, duplicate
simulation rejection, malformed JSON, unknown tools, and step exhaustion.

The existing NVIDIA candidate-ranking path remains separately validated and
unchanged.

## Real-Model Finding And Fix

A real NVIDIA MCP-agent loop was run from the user's configured PowerShell
session. Its first MCP call succeeded, but the next model response contained
multiple top-level JSON values and was rejected by the strict parser:

```text
Model response is not strict JSON: Extra data: line 1 column 298
```

The boundary now uses the model's documented native function-calling
interface instead of asking it to serialize agent actions as raw response
text. Mocked tests cover native MCP calls, terminal `finish_task` calls,
malformed arguments, and multiple-call rejection.

The corrected boundary was then rerun against the real NVIDIA model through
the healthy Docker MCP service. It passed in seven steps with no missing
required calls:

- Successful MCP tools: 7 of 7
- Missing required tools: 0
- Agent status: `completed`
- Fallback used: no
- Simulation launched: no
- Run ID: `93b6b374024b4124be8e6f2e0f03f561`

The machine-readable result is
`test_reports/energyplus_mcp_agent_validation_results.json`.
