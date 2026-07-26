# Candidate Policy Mock Validation

**PASS**

- Scenarios: 13/13
- Final selections inside current candidate set: `True`
- Final policies safe: `True`

| Mode | Fallback | Parser failure | Timeout | Final ID | Pass |
| --- | --- | --- | --- | --- | --- |
| valid_top_deterministic | False | False | False | P4 | True |
| valid_alternative_high_confidence | False | False | False | P3 | True |
| valid_medium_confidence_top_two | False | False | False | P3 | True |
| low_confidence | True | False | False | P4 | True |
| unknown_candidate | True | False | False | P4 | True |
| duplicate_ranking | True | True | False | P4 | True |
| incomplete_ranking | True | False | False | P4 | True |
| selected_not_first | True | False | False | P4 | True |
| extra_actuator_field | True | True | False | P4 | True |
| extra_policy_values | True | True | False | P4 | True |
| malformed_json | True | True | False | P4 | True |
| timeout | True | False | True | P4 | True |
| exception | True | False | False | P4 | True |
