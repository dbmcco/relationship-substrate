from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import psycopg

from relationship_substrate.db import run_migrations
from relationship_substrate.dossiers import get_person_dossier
from relationship_substrate.organizations import upsert_organization_enrichment
from relationship_substrate.person_notes import list_person_notes, record_person_note
from relationship_substrate.subject_notes import list_subject_notes, record_subject_note
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
    name = f"Alice Parker {uuid4().hex}"
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
        note="Alice is the user's accountant and is not a good fit for this network-discovery context.",
        metadata={"source_utterance": "alice is my accountant"},
    )

    assert note["person_email"] == email
    notes = list_person_notes(database_url, person_ref=email)
    assert notes[0]["note"] == note["note"]

    dossier = get_person_dossier(database_url, email=email)
    assert dossier["person_notes"][0]["note_kind"] == "context_fit"
    assert "not a good fit" in dossier["person_notes"][0]["note"]
    subject_notes = list_subject_notes(
        database_url,
        subject_type="person",
        subject_ref=email,
    )
    assert subject_notes[0]["subject_type"] == "person"
    assert subject_notes[0]["person_email"] == email
    assert subject_notes[0]["note"] == note["note"]


def test_history_backed_search_includes_person_notes(database_url):
    run_migrations(database_url)
    domain = f"sar-cpa-{uuid4().hex}.example"
    email = f"pat@{domain}"
    _insert_person_with_relationship(
        database_url,
        name="Alice Parker",
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
        note="Not a useful lead for small consulting firm discovery; this is the user's accountant.",
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
    assert result["subject_note_context"][0]["applies_to"] == "small_consulting_firm_discovery"
    assert result["person_notes"][0]["applies_to"] == "small_consulting_firm_discovery"
    assert result["subject_notes"] == result["subject_note_context"]
    assert result["person_notes"] == result["subject_note_context"]
    assert "accountant" in result["person_notes"][0]["note"]


def test_subject_note_context_demotes_or_explains_without_hiding_search_hit(database_url):
    run_migrations(database_url)
    domain = f"not-hidden-{uuid4().hex}.example"
    email = f"context@{domain}"
    _insert_person_with_relationship(
        database_url,
        name="Contextual Candidate",
        email=email,
        interaction_count=30,
    )
    upsert_organization_enrichment(
        database_url,
        company_name=domain,
        domain=domain,
        company_type="accounting_consultancy",
        employee_count_min=8,
        employee_count_max=12,
        employee_count_label="test size band",
        consultant_count_estimate=8,
        source_name="test",
        source_url="https://example.com",
        provenance_status="test",
    )
    record_subject_note(
        database_url,
        subject_type="person",
        subject_ref=email,
        note_kind="context_fit",
        applies_to="small_consulting_firm_discovery",
        note="Demote for this search context; explain the caveat, but do not hide the record.",
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
    assert result["match_reasons"]
    assert result["subject_note_context"][0]["note_kind"] == "context_fit"
    assert "do not hide" in result["subject_note_context"][0]["note"]


def test_subject_note_can_attach_to_organization(database_url):
    run_migrations(database_url)
    domain = f"small-advisory-{uuid4().hex}.example"
    upsert_organization_enrichment(
        database_url,
        company_name="Small Advisory",
        domain=domain,
        company_type="advisory_firm",
        employee_count_min=5,
        employee_count_max=12,
        employee_count_label="test",
        consultant_count_estimate=7,
        source_name="test",
        source_url="https://example.com",
        provenance_status="test",
    )

    note = record_subject_note(
        database_url,
        subject_type="organization",
        subject_ref=domain,
        note_kind="context_fit",
        applies_to="small_consulting_firm_discovery",
        note="This company is relevant only for finance-specific advisory questions.",
        evidence_refs=["msgvault:thread:test"],
        metadata={"source_utterance": "only finance-specific"},
    )

    assert note["subject_type"] == "organization"
    assert note["organization_domain"] == domain
    assert note["evidence_refs"] == ["msgvault:thread:test"]

    notes = list_subject_notes(
        database_url,
        subject_type="organization",
        subject_ref=domain,
    )
    assert notes[0]["note"] == note["note"]
    assert notes[0]["metadata"]["source_utterance"] == "only finance-specific"
