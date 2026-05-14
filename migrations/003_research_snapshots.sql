CREATE TABLE IF NOT EXISTS relationship_substrate.research_snapshot (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    subject_type TEXT NOT NULL,
    subject TEXT NOT NULL,
    retrieved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    summary TEXT NOT NULL,
    confidence TEXT NOT NULL,
    sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS research_snapshot_subject_idx
ON relationship_substrate.research_snapshot (lower(subject), subject_type, retrieved_at DESC);
