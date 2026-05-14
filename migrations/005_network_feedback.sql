CREATE TABLE IF NOT EXISTS relationship_substrate.network_feedback (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    packet_id UUID NOT NULL REFERENCES relationship_substrate.network_packet(id) ON DELETE CASCADE,
    person_email TEXT,
    feedback_kind TEXT NOT NULL,
    feedback JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS network_feedback_packet_idx
ON relationship_substrate.network_feedback (packet_id, created_at DESC);

CREATE INDEX IF NOT EXISTS network_feedback_person_idx
ON relationship_substrate.network_feedback (lower(person_email), created_at DESC)
WHERE person_email IS NOT NULL;
