CREATE TABLE IF NOT EXISTS relationship_substrate.subject_note (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    subject_type TEXT NOT NULL CHECK (subject_type IN ('person', 'organization')),
    subject_id UUID NOT NULL,
    note_kind TEXT NOT NULL,
    applies_to TEXT,
    note TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'user_correction',
    source_ref TEXT,
    evidence_refs TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    supersedes_id UUID REFERENCES relationship_substrate.subject_note(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS subject_note_subject_idx
ON relationship_substrate.subject_note (subject_type, subject_id, created_at DESC);

CREATE INDEX IF NOT EXISTS subject_note_kind_idx
ON relationship_substrate.subject_note (note_kind, created_at DESC);

INSERT INTO relationship_substrate.subject_note (
  id,
  subject_type,
  subject_id,
  note_kind,
  applies_to,
  note,
  source,
  metadata,
  created_at
)
SELECT
  id,
  'person',
  person_id,
  note_kind,
  applies_to,
  note,
  source,
  metadata,
  created_at
FROM relationship_substrate.person_note
ON CONFLICT (id) DO NOTHING;
