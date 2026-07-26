# NVIDIA NIM Candidate Ranking Gate

**PASS**

- Provider: `nvidia_nim`
- Model: `nvidia/llama-3.3-nemotron-super-49b-v1.5`
- Cases: 6/6
- Actual calls: 5
- Median latency: 7.662 s

| Case | Candidates | Strict | Complete | Selected first | Final | Fallback |
| --- | --- | --- | --- | --- | --- | --- |
| severe_thermal_deterioration | P1 | True | True | True | P1 | False |
| overheating_under_energy_saving | P1,P2 | True | True | True | P1 | False |
| hot_and_rising | P1,P2,P3 | True | True | True | P2 | False |
| hot_but_recovering | P2,P3,P6 | True | True | True | P3 | False |
| thermally_acceptable_high_power | P3,P4,P5,P6 | True | True | True | P4 | False |
| stable_conditions | P3,P4,P6 | True | True | True | P6 | False |

## Manual Review

### severe_thermal_deterioration

Forced deterministic candidate; no LLM call.

### overheating_under_energy_saving

Final `P1`; confidence `0.85`; reason: Thermal deterioration is prioritized due to current zone temperature (34.000°C) being above target (33.000°C) and strongly rising trends in both zone temperature and power. P1's aggressive thermal recovery mode and high thermal priority address the immediate thermal issue more effectively than P2's balanced approach, despite P1's lower energy setting. The current policy's conservative aggressiveness and energy-saving strategy are overridden due to the critical thermal state.

### hot_and_rising

Final `P2`; confidence `0.85`; reason: Thermal deterioration is prioritized due to current zone temperature (33.2°C) being above target (32.0°C) and rising trends in both zone temperature and power. P2 balances thermal recovery with moderate energy use, aligning with the current policy's moderate aggressiveness and the need to address rising thermal conditions without excessive energy consumption. P1 is too aggressive in energy reduction, which may not be necessary given the 'high_power' flag is false. P3 does not sufficiently address the thermal recovery need as it maintains the current target temperature and reduces thermal priority.

### hot_but_recovering

Final `P3`; confidence `0.85`; reason: Thermal deterioration takes priority. P3 maintains the target temperature (32.0°C) while balancing thermal and energy, aligning with the current 'balanced_default' strategy and normal aggressiveness. The zone temperature is falling but still above target, and P3 supports gradual adjustment without overreacting. P2 lowers the target further (31.5°C), which may increase energy use unnecessarily, while P6 holds current conditions longer but does not actively guide the zone toward the target efficiently.

### thermally_acceptable_high_power

Final `P4`; confidence `0.85`; reason: Thermal state is near target and stable, but power trend is rising and high_power is true. P4 balances thermal comfort (medium) with conservative energy use, slightly raising the zone target to reduce load while managing energy consumption effectively. This aligns with the priority of preventing thermal deterioration while addressing rising power trends.

### stable_conditions

Final `P6`; confidence `0.95`; reason: Thermal state is near target and stable, with no thermal deterioration risk. P6 maintains current thermal level (high) with medium energy, ensuring stability. P3 reduces thermal to medium, which may risk deviation from target, while P4 increases energy to high and adjusts target, which is unnecessary given current stability. Occupancy and PMV unavailable, so no additional comfort factors considered.
