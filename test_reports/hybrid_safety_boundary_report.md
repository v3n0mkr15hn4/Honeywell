# Hybrid Safety Boundary Report

## Enforced Boundaries

1. The supervisory schema has no actuator command.
2. Exact-key parsing rejects direct actuator fields.
3. PolicyValidator bounds policy independently of physical safety.
4. Only PolicyAwareRuleController creates ControlAction.
5. Every ControlAction passes through SafetyValidator.
6. Only ActuatorWriter calls `set_actuator_value`.
7. The existing post-manager callback reapplies the proven node override.
8. Production runner rejects the retired direct-LLM mode.

## Failure Behavior

- Malformed JSON: previous/default policy retained.
- Invalid enum: strict parser rejection and policy fallback.
- Direct setpoint attempt: strict parser rejection.
- Timeout/exception/empty response: previous/default policy retained.
- Three consecutive failures: supervisory cooldown.
- Cooldown: no LLM call; deterministic policy and physical control continue.
- Expired policy: grace is bounded, then deterministic default is restored.
- Concurrent request attempt: in-flight guard prevents a second call.

None of these paths disables RuleController, SafetyValidator, telemetry, or
EnergyPlus.

## Measured Evidence

Across twelve annual mock scenarios:

- EnergyPlus exit code 0: 12/12;
- severe errors: 0 in all runs;
- physical decisions: 9,216 per run;
- validated physical range compliance: 12/12;
- physical rate-limit compliance: 12/12;
- measured/applied node agreement: 9,215/9,215 comparable timesteps per run;
- prior-validated one-timestep timing: 9,215/9,215 per run;
- unsafe policy corrections: 256/256;
- direct actuator attempts accepted: 0.

Some policies generated large physical rule changes, producing 853 aggregate
physical SafetyValidator corrections. This is expected safety activity and
demonstrates why the physical validator remains mandatory.

## Honest Limit

These results validate software boundaries and deterministic failure behavior.
They do not prove that a real model will recommend useful policy, improve
thermal compliance, reduce energy, or meet latency requirements.
