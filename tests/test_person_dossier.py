from __future__ import annotations

from uuid import uuid4

import psycopg

from relationship_substrate.contracts import SourceEventIn, SourcePosture
from relationship_substrate.db import run_migrations
from relationship_substrate.dossiers import get_person_dossier
from relationship_substrate.identity import generate_identity_candidates
from relationship_substrate.materialize import materialize_calendar_events
from relationship_substrate.repositories import upsert_evidence_ref, upsert_source_event


def _insert_person(database_url: str, *, name: str, email: str) -> None:
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO relationship_substrate.person (
                  display_name, primary_email, source_posture, provenance_status
                )
                VALUES (%s, %s, 'direct_interaction', 'test')
                ON CONFLICT (primary_email)
                DO UPDATE SET display_name = EXCLUDED.display_name
                """,
                (name, email),
            )
        conn.commit()


def test_get_person_dossier_returns_evidence_interactions_and_candidates(database_url):
    run_migrations(database_url)
    localpart = f"dossier{uuid4().hex}"
    email = f"{localpart}@example.com"
    source_event = SourceEventIn(
        source_name="calendar",
        source_event_type="calendar_event",
        source_event_key=f"calendar:test:event-{localpart}",
        source_payload={
            "id": f"event-{localpart}",
            "summary": "Dossier review",
            "start": {"dateTime": "2026-05-26T13:00:00-04:00"},
            "attendees": [
                {"email": "user@example.com", "self": True},
                {"email": email, "displayName": "Dossier Person"},
            ],
        },
        source_posture=SourcePosture.DIRECT_INTERACTION,
        provenance_status="calendar_export",
        trust_role="calendar attendance evidence",
    )
    source_event_id = upsert_source_event(database_url, source_event)
    upsert_evidence_ref(
        database_url,
        source_event_id=source_event_id,
        ref_type="calendar_event",
        ref_value=source_event.source_event_key,
        metadata={"test": True},
    )
    materialize_calendar_events(
        database_url,
        self_aliases={"user@example.com"},
        skipped_domains=set(),
    )
    _insert_person(database_url, name="Dossier Person", email=f"{localpart}@other.example")
    generate_identity_candidates(database_url)

    dossier = get_person_dossier(database_url, email=email)

    assert dossier["person"]["primary_email"] == email
    assert dossier["person"]["display_name"] == "Dossier Person"
    assert dossier["relationship_edge"]["interaction_count"] == 1
    assert dossier["relationship_edge"]["calendar_interaction_count"] == 1
    assert dossier["relationship_edge"]["freshness"]["state"] == "recent"
    assert dossier["relationship_edge"]["freshness"]["basis"] == "last_materialized_interaction_at"
    assert dossier["contact_channels"] == [
        {
            "channel_type": "email",
            "channel_value": email,
            "source_posture": "direct_interaction",
            "provenance_status": "calendar_export",
        }
    ]
    assert dossier["interactions"][0]["subject"] == "Dossier review"
    assert dossier["source_events"][0]["source_event_key"] == source_event.source_event_key
    assert dossier["evidence_refs"][0]["ref_value"] == source_event.source_event_key
    assert dossier["identity_candidates"]
    assert dossier["identity_candidates"][0]["evidence"]["match_key"] == localpart
