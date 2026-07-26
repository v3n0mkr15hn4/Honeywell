# NVIDIA NIM Client Implementation

- Official OpenAI Python client: `openai 2.48.0`
- Provider: `nvidia_nim`
- Model: `nvidia/llama-3.3-nemotron-super-49b-v1.5`
- Base URL default: `https://integrate.api.nvidia.com/v1`
- Temperature: `0.0`
- Top P: `1.0`
- Maximum output tokens: `256`
- Nemotron reasoning mode: disabled with `/no_think`
- Stream: `False`
- Timeout default: `30 s`
- Maximum transient retries: `1`

The client implements the existing provider-neutral `query(prompt)` interface. It converts the candidate-ranking prompt into one system and one non-empty user message. SDK-internal retries are disabled and one bounded wrapper retry is used so retry telemetry is exact.

Authentication, permission, model availability, rate limit, timeout, network, server, and empty-response failures are mapped to stable sanitized categories. LLMPolicyRanker always maps failures to the current deterministic candidate recommendation.
