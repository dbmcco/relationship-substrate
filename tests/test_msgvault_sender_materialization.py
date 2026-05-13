from __future__ import annotations

import psycopg

from relationship_substrate.cli import ingest_msgvault_sender_rows
from relationship_substrate.db import run_migrations
from relationship_substrate.materialize import materialize_msgvault_senders


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
    _delete_sender_events(database_url, "braydon@intempio.com", "external@example.com")

    stats = ingest_msgvault_sender_rows(
        database_url,
        [
            {"email": "braydon@intempio.com", "message_count": 11721},
            {"email": "external@example.com", "message_count": 2600},
        ],
        self_aliases={"braydon@intempio.com"},
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
                AND source_event_key IN ('msgvault:sender:braydon@intempio.com', 'msgvault:sender:external@example.com')
                ORDER BY source_event_key
                """
            )
            rows = cur.fetchall()

    assert rows == [("direct_interaction", "msgvault_profile", "external@example.com")]


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
