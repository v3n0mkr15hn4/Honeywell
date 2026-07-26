# MCP Final Readiness Decision

## Decision

**Ready for a local standard-simulation judge demo. Not accepted for a public
or production deployment.**

## Passed

- Official separate MCP service health and bearer authentication
- MCP initialize and 35-tool inventory
- All required tools present
- Secure package validation and UUID isolation
- Real known-model load, validation, inspection, simulation, and plot
- Zero fatal and zero severe errors in the real run
- Standard-mode compatibility gate
- Mocked bounded-agent authorization tests
- Real NVIDIA native-function-calling agent gate: 7 of 7 required inspections
- Docker image build, healthy Compose startup, and non-root service execution
- Authenticated host-to-container run-path translation, IDF load, and validation
- Streamlit page render tests
- Full existing controller regression suite (169 tests)

## Blocking Gaps

1. The official repository required a local eppy compatibility patch in
   `validate_idf`.
2. The official MCP API exposes no running-simulation cancellation operation.
3. This local design is not a multi-user OS sandbox.
4. One successful real-agent gate is sufficient for a demo, not a production
   soak test.

## Go/No-Go

- Local developer or judge demo using the tested Docker MCP service: **GO**.
- Arbitrary uploaded model with Runtime API control: **NO-GO** unless actuator
  and sensor compatibility are independently proven.
- Public or production service: **NO-GO** without multi-user isolation,
  durable job infrastructure, and real-agent soak tests.
