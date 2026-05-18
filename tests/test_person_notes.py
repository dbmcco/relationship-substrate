from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import psycopg

from relationship_substrate.db import run_migrations
from relationship_substrate.dossiers import get_person_dossier
from relationship_substrate.organizations import upsert_organization_enrichment
from relationship_substrate.person_notes import list_person_notes, record_person_note
from relationship_substrate.search import search_history_backed_people


def _insert_person_with_relationship(
    database_url: str,
    *,
    name: str,
    email: str,
    interaction_count: int = 5,
) -> None:
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO relationship_substrate.person (
                  display_name, primary_email, source_posture, provenance_status
                )
                VALUES (%s, %s, 'direct_interaction', 'test')
                RETURNING id
                """,
                (name, email),
            )
            person_id = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO relationship_substrate.relationship_edge (
                  person_id, first_interaction_at, last_interaction_at, interaction_count, metadata
                )
                VALUES (%s, %s, %s, %s, '{}')
                """,
                (
                    person_id,
                    datetime(2026, 5, 1, tzinfo=UTC),
                    datetime(2026, 5, 1, tzinfo=UTC),
                    interaction_count,
                ),
            )
        conn.commit()


def test_person_note_is_recorded_listed_and_visible_in_dossier(database_url):
    run_migrations(database_url)
    name = f"Patrick Sharkey {uuid4().hex}"
    email = f"pat-{uuid4().hex}@example.com"
    _insert_person_with_relationship(
        database_url,
        name=name,
        email=email,
    )

    note = record_person_note(
        database_url,
        person_ref=name,
        note_kind="context_fit",
        applies_to="small_consulting_firm_discovery",
        note="Patrick is Braydon's accountant and is not a good fit for this network-discovery context.",
        metadata={"source_utterance": "patrick is my accountant"},
    )

    assert note["person_email"] == email
    notes = list_person_notes(database_url, person_ref=email)
    assert notes[0]["note"] == note["note"]

    dossier = get_person_dossier(database_url, email=email)
    assert dossier["person_notes"][0]["note_kind"] == "context_fit"
    assert "not a good fit" in dossier["person_notes"][0]["note"]


def test_history_backed_search_includes_person_notes(database_url):
    run_migrations(database_url)
    domain = f"sar-cpa-{uuid4().hex}.example"
    email = f"pat@{domain}"
    _insert_person_with_relationship(
        database_url,
        name="Patrick Sharkey",
        email=email,
        interaction_count=20,
    )
    upsert_organization_enrichment(
        database_url,
        company_name=domain,
        domain=domain,
        company_type="accounting_consultancy",
        employee_count_min=11,
        employee_count_max=50,
        employee_count_label="test size band",
        consultant_count_estimate=11,
        source_name="test",
        source_url="https://example.com",
        provenance_status="test",
    )
    record_person_note(
        database_url,
        person_ref=email,
        note_kind="context_fit",
        applies_to="small_consulting_firm_discovery",
        note="Not a useful lead for small consulting firm discovery; this is Braydon's accountant.",
    )

    results = search_history_backed_people(
        database_url,
        actual_employee_count_min=1,
        actual_employee_count_max=50,
        consultant_count_min=1,
        consultant_count_max=50,
        limit=200,
    )

    result = next(row for row in results if row["email"] == email)
    assert result["person_notes"][0]["applies_to"] == "small_consulting_firm_discovery"
    assert "accountant" in result["person_notes"][0]["note"]
