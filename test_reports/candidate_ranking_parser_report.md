# Candidate Ranking Parser

The parser requires exactly ranking, selected_policy_id, confidence, and reason. It rejects malformed or wrapped JSON, missing or extra fields, duplicate IDs, invalid types, empty text, NaN, and Infinity. Candidate-set membership remains a separate validator concern.
