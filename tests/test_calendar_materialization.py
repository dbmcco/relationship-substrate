from __future__ import annotations

from uuid import uuid4

import psycopg

from relationship_substrate.contracts import SourceEventIn, SourcePosture
from relationship_substrate.db import run_migrations
from relationship_substrate.materialize import materialize_calendar_events
from relationship_substrate.repositories import operating_picture_rows, upsert_source_event


def _calendar_event(*, attendees: list[dict], event_id: str = "event-1") -> SourceEventIn:
    return SourceEventIn(
        source_name="calendar",
        source_event_type="calendar_event",
        source_event_key=f"calendar:test:{event_id}",
        source_payload={
            "id": event_id,
            "summary": "Intro with Jane",
            "start": {"dateTime": "2026-05-01T15:00:00-04:00"},
            "end": {"dateTime": "2026-05-01T15:30:00-04:00"},
            "attendees": attendees,
        },
        source_posture=SourcePosture.DIRECT_INTERACTION,
        provenance_status="calendar_export",
        trust_role="calendar attendance evidence",
    )


def _clear_calendar_events(database_url: str) -> None:
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM relationship_substrate.source_event WHERE source_name = 'calendar'")
        conn.commit()


def test_materialize_calendar_events_creates_attendee_edges_and_skips_self_and_domains(database_url):
    run_migrations(database_url)
    _clear_calendar_events(database_url)
    localpart = f"jane-calendar-{uuid4().hex}"
    upsert_source_event(
        database_url,
        _calendar_event(
            attendees=[
                {"email": "user@example.com", "self": True},
                {"email": f"{localpart}@example.com", "displayName": "Jane Doe"},
                {"email": "team@intempio.com", "displayName": "Internal Team"},
            ],
            event_id=f"event-{localpart}",
        ),
    )

    stats = materialize_calendar_events(
        database_url,
        self_aliases={"user@example.com"},
        skipped_domains={"intempio.com"},
    )

    assert stats == {
        "source": "calendar",
        "events_seen": 1,
        "materialized_events": 1,
        "attendees_materialized": 1,
        "skipped_self": 1,
        "skipped_domain": 1,
        "skipped_missing_email": 0,
        "skipped_existing": 0,
    }
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  p.display_name,
                  p.primary_email,
                  e.interaction_count,
                  (e.last_interaction_at AT TIME ZONE 'UTC')::text
                FROM relationship_substrate.person p
                JOIN relationship_substrate.relationship_edge e
                  ON e.person_id = p.id
                WHERE p.primary_email = %s
                """,
                (f"{localpart}@example.com",),
            )
            row = cur.fetchone()
    assert row == ("Jane Doe", f"{localpart}@example.com", 1, "2026-05-01 19:00:00")


def test_materialize_calendar_events_is_idempotent(database_url):
    run_migrations(database_url)
    _clear_calendar_events(database_url)
    localpart = f"alex-calendar-{uuid4().hex}"
    upsert_source_event(
        database_url,
        _calendar_event(
            attendees=[
                {"email": f"{localpart}@example.com", "displayName": "Alex Example"},
            ],
            event_id=f"event-{localpart}",
        ),
    )

    first = materialize_calendar_events(database_url, self_aliases=set(), skipped_domains=set())
    second = materialize_calendar_events(database_url, self_aliases=set(), skipped_domains=set())

    assert first["attendees_materialized"] == 1
    assert second["skipped_existing"] >= 1
    rows = [
        row
        for row in operating_picture_rows(database_url, limit=1000)
        if row["primary_email"] == f"{localpart}@example.com"
    ]
    assert len(rows) == 1
    assert rows[0]["interaction_count"] == 1
    assert rows[0]["calendar_interaction_count"] == 1


def test_materialize_calendar_events_skips_self_alias_variants(database_url):
    run_migrations(database_url)
    _clear_calendar_events(database_url)
    localpart = f"sam-calendar-{uuid4().hex}"
    upsert_source_event(
        database_url,
        _calendar_event(
            attendees=[
                {"email": "user.name+calendar@gmail.com"},
                {"email": "user.name@gmail.com"},
                {"email": f"{localpart}@example.com", "displayName": "Sam Example"},
            ],
            event_id=f"event-{localpart}",
        ),
    )

    stats = materialize_calendar_events(
        database_url,
        self_aliases={"user@gmail.com"},
        skipped_domains=set(),
    )

    assert stats["attendees_materialized"] == 1
    assert stats["skipped_self"] == 2
