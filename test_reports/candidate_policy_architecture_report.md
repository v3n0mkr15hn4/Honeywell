# Candidate Policy Architecture

EnergyPlus history is reduced to deterministic StateSummary facts. Fixed, validated policy candidates are ranked by the LLM. PolicyAwareRuleController remains the only ControlAction creator, and SafetyValidator plus ActuatorWriter retain physical authority.

The LLM performs bounded multi-objective supervisory policy selection by ranking dynamically generated safe candidates using thermal, energy, and environmental state summaries. Deterministic controllers convert the selected policy into physical commands and enforce all safety constraints.
