from uuid import uuid4

import psycopg

from relationship_substrate.contracts import SourceEventIn, SourcePosture
from relationship_substrate.db import run_migrations
from relationship_substrate.materialize import materialize_curated_contact, materialize_exact_emails
from relationship_substrate.repositories import upsert_source_event


def test_materialize_curated_contact_creates_person_and_channel(database_url):
    run_migrations(database_url)
    event = SourceEventIn(
        source_name="next_up",
        source_event_type="curated_contact",
        source_event_key="next_up:people.xlsx:Contacts:2",
        source_payload={
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "Jane@Example.com",
            "company": "ExampleCo",
            "title": "VP Product",
        },
        source_posture=SourcePosture.CURATED_EXPORT,
        provenance_status="unknown_upstream",
        trust_role="identity/context seed",
    )
    source_event_id = upsert_source_event(database_url, event)

    person_id = materialize_curated_contact(database_url, source_event_id)

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT display_name, primary_email FROM relationship_substrate.person WHERE id = %s",
                (person_id,),
            )
            assert cur.fetchone() == ("Jane Doe", "jane@example.com")
            cur.execute(
                "SELECT channel_value FROM relationship_substrate.contact_channel WHERE person_id = %s",
                (person_id,),
            )
            assert cur.fetchone() == ("jane@example.com",)


def test_materialize_exact_emails_skips_configured_domains(database_url):
    run_migrations(database_url)
    unique = uuid4().hex
    skipped_email = f"skip-{unique}@intempio.com"
    kept_email = f"keep-{unique}@example.com"
    for row_number, email in enumerate([skipped_email, kept_email], start=2):
        upsert_source_event(
            database_url,
            SourceEventIn(
                source_name="next_up",
                source_event_type="curated_contact",
                source_event_key=f"next_up:skip-domains:{unique}:{row_number}",
                source_payload={
                    "first_name": "Domain",
                    "last_name": "Filter",
                    "email": email,
                },
                source_posture=SourcePosture.CURATED_EXPORT,
                provenance_status="unknown_upstream",
                trust_role="identity/context seed",
            ),
        )

    stats = materialize_exact_emails(database_url, skipped_domains={"intempio.com"})

    assert stats["skipped_domain"] >= 1
    assert stats["materialized"] >= 1
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT primary_email
                FROM relationship_substrate.person
                WHERE primary_email IN (%s, %s)
                ORDER BY primary_email
                """,
                (skipped_email, kept_email),
            )
            assert cur.fetchall() == [(kept_email,)]
