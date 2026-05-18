CREATE TABLE IF NOT EXISTS relationship_substrate.person_note (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    person_id UUID NOT NULL REFERENCES relationship_substrate.person(id) ON DELETE CASCADE,
    note_kind TEXT NOT NULL,
    applies_to TEXT,
    note TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'user_correction',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS person_note_person_idx
ON relationship_substrate.person_note (person_id, created_at DESC);

CREATE INDEX IF NOT EXISTS person_note_kind_idx
ON relationship_substrate.person_note (note_kind, created_at DESC);
