from __future__ import annotations

from datetime import UTC
from uuid import uuid4

import psycopg

from relationship_substrate.cli import ingest_msgvault_sender_rows
from relationship_substrate.contracts import SourceEventIn, SourcePosture
from relationship_substrate.db import run_migrations
from relationship_substrate.dossiers import get_person_dossier
from relationship_substrate.materialize import (
    materialize_msgvault_correspondence,
    materialize_msgvault_senders,
)
from relationship_substrate.repositories import upsert_source_event


def _delete_sender_events(database_url, *emails: str) -> None:
    keys = tuple(f"msgvault:sender:{email}" for email in emails)
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM relationship_substrate.source_event
                WHERE source_event_key = ANY(%s)
                """,
                (list(keys),),
            )
        conn.commit()


def test_ingest_msgvault_sender_rows_filters_self_aliases(database_url):
    run_migrations(database_url)
    _delete_sender_events(database_url, "user@examplecorp.com", "external@example.com")

    stats = ingest_msgvault_sender_rows(
        database_url,
        [
            {"email": "user@examplecorp.com", "message_count": 11721},
            {"email": "external@example.com", "message_count": 2600},
        ],
        self_aliases={"user@examplecorp.com"},
        skipped_domains=set(),
    )

    assert stats == {
        "source": "msgvault",
        "events_seen": 2,
        "events_upserted": 1,
        "skipped_self": 1,
        "skipped_domain": 0,
        "skipped_system": 0,
        "skipped_missing_email": 0,
    }

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT source_posture, provenance_status, source_payload->>'email'
                FROM relationship_substrate.source_event
                WHERE source_name = 'msgvault'
                AND source_event_type = 'sender_profile'
                AND source_event_key IN ('msgvault:sender:user@examplecorp.com', 'msgvault:sender:external@example.com')
                ORDER BY source_event_key
                """
            )
            rows = cur.fetchall()

    assert rows == [("direct_interaction", "msgvault_profile", "external@example.com")]


def test_ingest_msgvault_sender_rows_filters_self_alias_variants(database_url):
    run_migrations(database_url)
    _delete_sender_events(
        database_url,
        "user.name+history@gmail.com",
        "user.name@gmail.com",
        "external@example.com",
    )

    stats = ingest_msgvault_sender_rows(
        database_url,
        [
            {"email": "user.name+history@gmail.com", "message_count": 11721},
            {"email": "user.name@gmail.com", "message_count": 930},
            {"email": "external@example.com", "message_count": 2600},
        ],
        self_aliases={"user@gmail.com"},
        skipped_domains=set(),
    )

    assert stats == {
        "source": "msgvault",
        "events_seen": 3,
        "events_upserted": 1,
        "skipped_self": 2,
        "skipped_domain": 0,
        "skipped_system": 0,
        "skipped_missing_email": 0,
    }


def test_ingest_msgvault_sender_rows_filters_skipped_domains(database_url):
    run_migrations(database_url)
    _delete_sender_events(database_url, "anne@intempio.com", "external@example.com")

    stats = ingest_msgvault_sender_rows(
        database_url,
        [
            {"email": "anne@intempio.com", "message_count": 2600},
            {"email": "external@example.com", "message_count": 12},
        ],
        self_aliases=set(),
        skipped_domains={"intempio.com"},
    )

    assert stats["events_seen"] == 2
    assert stats["events_upserted"] == 1
    assert stats["skipped_domain"] == 1

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT source_payload->>'email'
                FROM relationship_substrate.source_event
                WHERE source_name = 'msgvault'
                AND source_event_type = 'sender_profile'
                AND source_event_key IN ('msgvault:sender:anne@intempio.com', 'msgvault:sender:external@example.com')
                ORDER BY source_event_key
                """
            )
            rows = [row[0] for row in cur.fetchall()]

    assert rows == ["external@example.com"]


def test_ingest_msgvault_sender_rows_filters_system_senders(database_url):
    run_migrations(database_url)
    _delete_sender_events(
        database_url,
        "events@rvibe.com",
        "onlinebanking@ealerts.bankofamerica.com",
        "invoice+statements@mail.anthropic.com",
        "external@example.com",
    )

    stats = ingest_msgvault_sender_rows(
        database_url,
        [
            {"email": "events@rvibe.com", "message_count": 561},
            {"email": "onlinebanking@ealerts.bankofamerica.com", "message_count": 590},
            {"email": "invoice+statements@mail.anthropic.com", "message_count": 504},
            {"email": "external@example.com", "message_count": 12},
        ],
        self_aliases=set(),
        skipped_domains=set(),
        skipped_system_localparts={"events", "onlinebanking"},
        skipped_system_prefixes={"invoice"},
    )

    assert stats["events_seen"] == 4
    assert stats["events_upserted"] == 1
    assert stats["skipped_system"] == 3

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT source_payload->>'email'
                FROM relationship_substrate.source_event
                WHERE source_name = 'msgvault'
                AND source_event_type = 'sender_profile'
                AND source_event_key IN (
                    'msgvault:sender:events@rvibe.com',
                    'msgvault:sender:onlinebanking@ealerts.bankofamerica.com',
                    'msgvault:sender:invoice+statements@mail.anthropic.com',
                    'msgvault:sender:external@example.com'
                )
                ORDER BY source_event_key
                """
            )
            rows = [row[0] for row in cur.fetchall()]

    assert rows == ["external@example.com"]


def test_materialize_msgvault_senders_creates_relationship_edges(database_url):
    run_migrations(database_url)
    _delete_sender_events(database_url, "anne@intempio.com")
    ingest_msgvault_sender_rows(
        database_url,
        [{"email": "anne@intempio.com", "message_count": 2600, "total_size": 398593897}],
        self_aliases=set(),
        skipped_domains=set(),
    )

    stats = materialize_msgvault_senders(database_url)

    assert stats["source"] == "msgvault"
    assert stats["materialized"] >= 1

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.display_name, p.primary_email, e.interaction_count
                FROM relationship_substrate.person p
                JOIN relationship_substrate.relationship_edge e ON e.person_id = p.id
                WHERE p.primary_email = 'anne@intempio.com'
                """
            )
            assert cur.fetchone() == ("anne", "anne@intempio.com", 2600)
            cur.execute(
                """
                SELECT interaction_type, metadata->>'aggregate'
                FROM relationship_substrate.interaction i
                JOIN relationship_substrate.source_event s ON s.id = i.source_event_id
                WHERE s.source_event_key = 'msgvault:sender:anne@intempio.com'
                """
            )
            assert cur.fetchone() == ("email_sender_profile", "true")


def test_materialize_msgvault_correspondence_updates_edge_dates_and_counts(database_url):
    run_migrations(database_url)
    localpart = f"andrew-{uuid4().hex}"
    email = f"{localpart}@example.com"
    first_event = SourceEventIn(
        source_name="msgvault",
        source_event_type="correspondence_message",
        source_event_key=f"msgvault:correspondence:{email}:1",
        source_payload={
            "id": 1,
            "relationship_email": email,
            "relationship_direction": "from_contact",
            "from_email": email,
            "from_name": "Andrew Example",
            "sent_at": "2024-01-02T00:00:00Z",
            "subject": "Inbound",
            "snippet": "hello",
        },
        source_posture=SourcePosture.DIRECT_INTERACTION,
        provenance_status="msgvault_message",
        trust_role="direct email correspondence evidence",
    )
    second_event = SourceEventIn(
        source_name="msgvault",
        source_event_type="correspondence_message",
        source_event_key=f"msgvault:correspondence:{email}:2",
        source_payload={
            "id": 2,
            "relationship_email": email,
            "relationship_direction": "to_contact",
            "from_email": "user@example.com",
            "from_name": "Braydon",
            "sent_at": "2024-02-03T00:00:00Z",
            "subject": "Outbound",
            "snippet": "reply",
        },
        source_posture=SourcePosture.DIRECT_INTERACTION,
        provenance_status="msgvault_message",
        trust_role="direct email correspondence evidence",
    )
    upsert_source_event(database_url, first_event)
    upsert_source_event(database_url, second_event)

    stats = materialize_msgvault_correspondence(database_url)

    assert stats["materialized"] == 2
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  p.display_name,
                  p.primary_email,
                  e.interaction_count,
                  e.first_interaction_at,
                  e.last_interaction_at,
                  e.metadata->>'email_message_count'
                FROM relationship_substrate.person p
                JOIN relationship_substrate.relationship_edge e ON e.person_id = p.id
                WHERE p.primary_email = %s
                """,
                (email,),
            )
            row = cur.fetchone()
            assert row[0] == "Andrew Example"
            assert row[1] == email
            assert row[2] == 2
            assert row[3].astimezone(UTC).isoformat() == "2024-01-02T00:00:00+00:00"
            assert row[4].astimezone(UTC).isoformat() == "2024-02-03T00:00:00+00:00"
            assert row[5] == "2"
            cur.execute(
                """
                SELECT interaction_type, subject, metadata->>'relationship_direction'
                FROM relationship_substrate.interaction
                WHERE metadata->>'relationship_email' = %s
                ORDER BY occurred_at
                """,
                (email,),
            )
            assert cur.fetchall() == [
                ("email_message", "Inbound", "from_contact"),
                ("email_message", "Outbound", "to_contact"),
            ]

    dossier = get_person_dossier(database_url, email=email)

    assert [interaction["subject"] for interaction in dossier["interactions"]] == [
        "Outbound",
        "Inbound",
    ]
