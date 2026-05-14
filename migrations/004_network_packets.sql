CREATE TABLE IF NOT EXISTS relationship_substrate.network_packet (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    packet_kind TEXT NOT NULL,
    contract_version INTEGER NOT NULL,
    query JSONB NOT NULL DEFAULT '{}'::jsonb,
    readiness JSONB NOT NULL DEFAULT '{}'::jsonb,
    packet_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_refs JSONB NOT NULL DEFAULT '{}'::jsonb,
    model_recommendations JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS network_packet_created_at_idx
ON relationship_substrate.network_packet (created_at DESC);
