# EnergyPlus MCP Security Boundary Report

## Enforced Controls

- Uploads are validated in memory before filesystem writes.
- Exactly one IDF and one EPW are required.
- Extensions are allowlisted; executables, scripts, libraries, FMUs, and
  nested archives are rejected.
- ZIP traversal, absolute members, hidden paths, symbolic links, file-count
  excess, and expanded-size excess are rejected.
- IDF version 26.1 is treated as equivalent to server version 26.1.0.
- Older, newer, and unknown versions cannot be staged for simulation.
- Detectable `Schedule:File` CSV references must be present.
- Every run uses a random UUID and separate input, working, output, logs, and
  metadata directories.
- Host paths are canonicalized beneath the current run before optional
  host-to-container path translation.
- Cross-run paths, network URLs, shell metacharacters, unknown arguments, and
  non-allowlisted MCP tools are rejected.
- Tool arguments are validated against schemas returned by `list_tools`.
- Modification tools are disabled.
- One simulation call is allowed per approved agent task.
- Running jobs retain the global concurrency lock after a client timeout.
- Manifests and dashboard pages do not render bearer tokens, API keys, or
  authorization headers.
- Downloads are restricted to allowlisted files inside the selected run.

## Adversarial Tests

Tests passed for loose-file traversal, ZIP traversal, nested ZIPs, ZIP
symlinks, oversized files, compressed expansion, duplicate primary files,
missing schedule CSVs, cross-run access, network paths, shell syntax, unknown
arguments, unknown tools, disabled modifications, missing human approval,
duplicate simulation calls, malformed model JSON, and maximum agent steps.

## Honest Limits

This is a local hackathon boundary, not a multi-tenant public sandbox. The
local service and dashboard run under the same Windows user and therefore
share that user's OS permissions. Docker would improve process isolation, but
Docker was unavailable and remains unverified.

The official MCP server itself accepts absolute paths. Security therefore
depends on all judge calls passing through `MCPToolGuard`; judges must not
receive direct MCP bearer credentials.

The official server exposes no safe cancellation tool for an already running
simulation. The job manager can cancel queued work and time out client
waiting, but it deliberately does not kill a running remote process.
