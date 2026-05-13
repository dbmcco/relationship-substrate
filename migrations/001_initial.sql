CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE SCHEMA IF NOT EXISTS relationship_substrate;

CREATE TABLE IF NOT EXISTS relationship_substrate.schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS relationship_substrate.ingestion_run (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_name TEXT NOT NULL,
    adapter_name TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'succeeded', 'failed')),
    source_watermark TEXT,
    stats JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT
);

CREATE TABLE IF NOT EXISTS relationship_substrate.source_account (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_name TEXT NOT NULL,
    account_key TEXT NOT NULL,
    display_name TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_name, account_key)
);

CREATE TABLE IF NOT EXISTS relationship_substrate.source_event (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ingestion_run_id UUID REFERENCES relationship_substrate.ingestion_run(id) ON DELETE SET NULL,
    source_name TEXT NOT NULL,
    source_event_type TEXT NOT NULL,
    source_event_key TEXT NOT NULL,
    occurred_at TIMESTAMPTZ,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_posture TEXT NOT NULL,
    provenance_status TEXT NOT NULL,
    trust_role TEXT NOT NULL,
    UNIQUE (source_name, source_event_key)
);

CREATE TABLE IF NOT EXISTS relationship_substrate.evidence_ref (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_event_id UUID NOT NULL REFERENCES relationship_substrate.source_event(id) ON DELETE CASCADE,
    ref_type TEXT NOT NULL,
    ref_value TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (ref_type, ref_value)
);

CREATE TABLE IF NOT EXISTS relationship_substrate.evidence_excerpt (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    evidence_ref_id UUID NOT NULL REFERENCES relationship_substrate.evidence_ref(id) ON DELETE CASCADE,
    excerpt_text TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS relationship_substrate.source_identity (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_event_id UUID REFERENCES relationship_substrate.source_event(id) ON DELETE CASCADE,
    identity_type TEXT NOT NULL,
    identity_value TEXT NOT NULL,
    display_name TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (identity_type, identity_value)
);

CREATE TABLE IF NOT EXISTS relationship_substrate.person (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    display_name TEXT NOT NULL,
    primary_email TEXT,
    source_posture TEXT NOT NULL,
    provenance_status TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    content_embedding VECTOR(1536),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (primary_email)
);

CREATE TABLE IF NOT EXISTS relationship_substrate.organization (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    domain TEXT,
    source_posture TEXT NOT NULL,
    provenance_status TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    content_embedding VECTOR(1536),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (domain)
);

CREATE TABLE IF NOT EXISTS relationship_substrate.contact_channel (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    person_id UUID NOT NULL REFERENCES relationship_substrate.person(id) ON DELETE CASCADE,
    channel_type TEXT NOT NULL,
    channel_value TEXT NOT NULL,
    source_identity_id UUID REFERENCES relationship_substrate.source_identity(id) ON DELETE SET NULL,
    source_posture TEXT NOT NULL,
    provenance_status TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (channel_type, channel_value)
);

CREATE TABLE IF NOT EXISTS relationship_substrate.affiliation (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    person_id UUID NOT NULL REFERENCES relationship_substrate.person(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES relationship_substrate.organization(id) ON DELETE CASCADE,
    role_or_title TEXT,
    source_posture TEXT NOT NULL,
    provenance_status TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (person_id, organization_id, role_or_title)
);

CREATE TABLE IF NOT EXISTS relationship_substrate.identity_candidate (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_identity_id UUID NOT NULL REFERENCES relationship_substrate.source_identity(id) ON DELETE CASCADE,
    candidate_type TEXT NOT NULL CHECK (candidate_type IN ('person', 'organization')),
    candidate_id UUID,
    reason TEXT NOT NULL,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'candidate' CHECK (status IN ('candidate', 'accepted', 'rejected', 'superseded')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS relationship_substrate.interaction (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_event_id UUID NOT NULL REFERENCES relationship_substrate.source_event(id) ON DELETE CASCADE,
    interaction_type TEXT NOT NULL,
    occurred_at TIMESTAMPTZ,
    subject TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (source_event_id)
);

CREATE TABLE IF NOT EXISTS relationship_substrate.relationship_edge (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    person_id UUID NOT NULL REFERENCES relationship_substrate.person(id) ON DELETE CASCADE,
    first_interaction_at TIMESTAMPTZ,
    last_interaction_at TIMESTAMPTZ,
    interaction_count INTEGER NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (person_id)
);

CREATE TABLE IF NOT EXISTS relationship_substrate.relationship_state (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    person_id UUID NOT NULL REFERENCES relationship_substrate.person(id) ON DELETE CASCADE,
    state_kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    rationale TEXT NOT NULL,
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    supersedes_id UUID REFERENCES relationship_substrate.relationship_state(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS relationship_substrate.state_journal_entry (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type TEXT NOT NULL,
    entity_id UUID NOT NULL,
    change_kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
