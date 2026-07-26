# Semantic Mock Validation Report

Physical control variable: supply-air temperature setpoint for `MAIN COOLING COIL 1 OUTLET NODE`.
Allowed range: 22.0 C to 25.0 C. Maximum change: 1.0 C per decision.
Configured LLM interval: 6 zone timesteps.
Actual IDF timestep: 10 minutes, so the interval is one simulated hour.

| Scenario | Expected | Calls | Reused | Safety | Failures | Fallbacks | Pass |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| rule | Rule baseline decides every timestep with no LLM calls | 0 | 0 | 0 | 0 | 0 | True |
| llm_valid | Valid supply-air JSON is called every six timesteps | 1536 | 7679 | 0 | 0 | 0 | True |
| llm_unsafe_low | 18 C is clamped to the 22 C physical minimum | 1536 | 7679 | 1536 | 0 | 0 | True |
| llm_unsafe_high | 30 C is clamped and rate-limited from the prior action | 1536 | 7679 | 1536 | 0 | 0 | True |
| llm_malformed_json | Strict parser/client failure invokes validated RuleController fallback | 386 | 7679 | 0 | 386 | 1536 | True |
| llm_missing_field | Strict parser/client failure invokes validated RuleController fallback | 386 | 7679 | 0 | 386 | 1536 | True |
| llm_wrong_type | Strict parser/client failure invokes validated RuleController fallback | 386 | 7679 | 0 | 386 | 1536 | True |
| llm_wrong_field | Strict parser/client failure invokes validated RuleController fallback | 386 | 7679 | 0 | 386 | 1536 | True |
| llm_empty_response | Strict parser/client failure invokes validated RuleController fallback | 386 | 7679 | 0 | 386 | 1536 | True |
| llm_exception | Strict parser/client failure invokes validated RuleController fallback | 386 | 7679 | 0 | 386 | 1536 | True |
| llm_timeout | Strict parser/client failure invokes validated RuleController fallback | 386 | 7679 | 0 | 386 | 1536 | True |
| llm_alternating | Alternating node targets exercise rate and change counting | 1536 | 7679 | 768 | 0 | 0 | True |

Every scenario also requires exit code 0, zero severe errors, 9,216 sensor rows, the semantic telemetry schema, measured/applied node agreement, and the one-zone-timestep action delay.
