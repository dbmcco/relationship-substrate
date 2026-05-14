from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

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


def test_materialize_curated_contact_creates_organization_affiliation_and_is_idempotent(database_url):
    run_migrations(database_url)
    unique = uuid4().hex
    email = f"org-affiliation-{unique}@example.com"
    company = f"ExampleCo {unique}"
    event = SourceEventIn(
        source_name="next_up",
        source_event_type="curated_contact",
        source_event_key=f"next_up:org-affiliation:{unique}:2",
        source_payload={
            "first_name": "Jane",
            "last_name": "Doe",
            "email": email,
            "company": company,
            "title": "VP Product",
        },
        source_posture=SourcePosture.CURATED_EXPORT,
        provenance_status="unknown_upstream",
        trust_role="identity/context seed",
    )
    source_event_id = upsert_source_event(database_url, event)

    person_id = materialize_curated_contact(database_url, source_event_id)
    second_person_id = materialize_curated_contact(database_url, source_event_id)

    assert second_person_id == person_id
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, metadata->>'source'
                FROM relationship_substrate.organization
                WHERE lower(name) = lower(%s)
                """,
                (company,),
            )
            organization_rows = cur.fetchall()
            assert len(organization_rows) == 1
            organization_id = organization_rows[0][0]
            assert organization_rows[0][1:] == (company, "curated_contact")
            cur.execute(
                """
                SELECT role_or_title, metadata->>'source_event_id'
                FROM relationship_substrate.affiliation
                WHERE person_id = %s
                AND organization_id = %s
                """,
                (person_id, organization_id),
            )
            assert cur.fetchall() == [("VP Product", str(source_event_id))]


def test_materialize_curated_contact_updates_affiliation_title_for_same_source_event(database_url):
    run_migrations(database_url)
    unique = uuid4().hex
    email = f"org-affiliation-update-{unique}@example.com"
    company = f"UpdateCo {unique}"
    event = SourceEventIn(
        source_name="next_up",
        source_event_type="curated_contact",
        source_event_key=f"next_up:org-affiliation-update:{unique}:2",
        source_payload={
            "first_name": "Jane",
            "last_name": "Doe",
            "email": email,
            "company": company,
            "title": "VP Product",
        },
        source_posture=SourcePosture.CURATED_EXPORT,
        provenance_status="unknown_upstream",
        trust_role="identity/context seed",
    )
    source_event_id = upsert_source_event(database_url, event)
    materialize_curated_contact(database_url, source_event_id)
    updated_event = event.model_copy(
        update={
            "source_payload": {
                **event.source_payload,
                "title": "Chief Product Officer",
            }
        }
    )
    upsert_source_event(database_url, updated_event)

    person_id = materialize_curated_contact(database_url, source_event_id)

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT a.role_or_title
                FROM relationship_substrate.affiliation a
                JOIN relationship_substrate.organization o ON o.id = a.organization_id
                WHERE a.person_id = %s
                AND lower(o.name) = lower(%s)
                """,
                (person_id, company),
            )
            assert cur.fetchall() == [("Chief Product Officer",)]


def test_materialize_curated_contact_preserves_existing_organization_enrichment(database_url):
    run_migrations(database_url)
    unique = uuid4().hex
    email = f"org-enrichment-preserve-{unique}@example.com"
    company = f"EnrichedCo {unique}"
    enrichment = {
        "company_type": "public_pharmaceutical_company",
        "source_name": "reviewed_batch",
    }
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO relationship_substrate.organization (
                  name, source_posture, provenance_status, metadata
                )
                VALUES (%s, 'enrichment', 'external_research', %s)
                """,
                (company, Jsonb({"enrichment": enrichment})),
            )
        conn.commit()
    event = SourceEventIn(
        source_name="next_up",
        source_event_type="curated_contact",
        source_event_key=f"next_up:org-enrichment-preserve:{unique}:2",
        source_payload={
            "first_name": "Jane",
            "last_name": "Doe",
            "email": email,
            "company": company,
            "title": "VP Product",
        },
        source_posture=SourcePosture.CURATED_EXPORT,
        provenance_status="unknown_upstream",
        trust_role="identity/context seed",
    )
    source_event_id = upsert_source_event(database_url, event)

    materialize_curated_contact(database_url, source_event_id)

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT metadata
                FROM relationship_substrate.organization
                WHERE lower(name) = lower(%s)
                """,
                (company,),
            )
            metadata = cur.fetchone()[0]
            assert metadata["enrichment"] == enrichment
            assert metadata["source"] == "curated_contact"


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
