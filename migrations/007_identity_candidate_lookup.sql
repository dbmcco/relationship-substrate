CREATE INDEX IF NOT EXISTS identity_candidate_lookup_idx
ON relationship_substrate.identity_candidate (source_identity_id, candidate_id, reason);
