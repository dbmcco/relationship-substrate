from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import psycopg

from relationship_substrate.cli import ingest_msgvault_sender_rows
from relationship_substrate.contracts import SourceEventIn, SourcePosture
from relationship_substrate.db import run_migrations
from relationship_substrate.materialize import (
    materialize_calendar_events,
    materialize_exact_emails,
    materialize_msgvault_senders,
)
from relationship_substrate.organizations import (
    upsert_organization_enrichment,
    history_backed_organization_worklist,
    import_organization_enrichments,
    organization_enrichment_worklist,
)
from relationship_substrate.repositories import upsert_source_event


def _curated_contact(database_url: str, *, email: str, title: str, company: str) -> None:
    upsert_source_event(
        database_url,
        SourceEventIn(
            source_name="next_up",
            source_event_type="curated_contact",
            source_event_key=f"org-enrichment-test:{email}",
            source_payload={
                "email": email,
                "first_name": email.split("@", 1)[0],
                "last_name": "Person",
                "title": title,
                "company": company,
            },
            source_posture=SourcePosture.CURATED_EXPORT,
            provenance_status="test_curated_export",
            trust_role="identity/context seed",
        ),
    )


def test_organization_enrichment_worklist_prioritizes_unenriched_companies(database_url):
    run_migrations(database_url)
    company = f"Medcom Worklist Co Exact"
    _curated_contact(
        database_url,
        email="one-worklist@example.com",
        title="Medical Communications Consultant",
        company=company,
    )
    _curated_contact(
        database_url,
        email="two-worklist@example.com",
        title="Scientific Communications Director",
        company=company,
    )
    _curated_contact(
        database_url,
        email="three@example.com",
        title="Procurement",
        company="Other Worklist Co",
    )

    rows = organization_enrichment_worklist(database_url, limit=1000)
    medcom = next(row for row in rows if row["company_name"] == company)

    assert medcom["known_people_at_company_count"] == 2
    assert medcom["has_enrichment"] is False
    assert "Medical Communications Consultant" in medcom["sample_titles"]
    assert "Scientific Communications Director" in medcom["sample_titles"]


def test_import_organization_enrichments_upserts_reviewed_facts(database_url):
    run_migrations(database_url)

    report = import_organization_enrichments(
        database_url,
        [
            {
                "company_name": "Reviewed Medcom Co",
                "company_type": "medical_communications_consultancy",
                "employee_count_min": 10,
                "employee_count_max": 20,
                "employee_count_label": "small_team",
                "consultant_count_estimate": 12,
                "source_name": "perplexity_research",
                "source_url": "https://example.com/research",
                "provenance_status": "external_research",
            }
        ],
    )

    assert report["imported"] == 1
    assert report["skipped"] == 0


def test_history_backed_organization_worklist_ranks_companies_by_direct_history(database_url):
    run_migrations(database_url)
    run_id = uuid4().hex
    company = f"MedHistory Worklist Co {run_id}"
    lower_company = f"LowHistory Worklist Co {run_id}"
    domain = f"medhistory-{run_id}.example"
    lower_domain = f"lowhistory-{run_id}.example"
    history_only_domain = f"historyonly-{run_id}.example"
    _curated_contact(
        database_url,
        email=f"ann@{domain}",
        title="Medical Communications Consultant",
        company=company,
    )
    _curated_contact(
        database_url,
        email=f"bob@{domain}",
        title="Strategy Partner",
        company=company,
    )
    _curated_contact(
        database_url,
        email=f"low@{lower_domain}",
        title="Medical Communications Consultant",
        company=lower_company,
    )
    materialize_exact_emails(database_url, skipped_domains={"intempio.com"})
    ingest_msgvault_sender_rows(
        database_url,
        [
            {"email": f"ann@{domain}", "display_name": "Ann History", "message_count": 12},
            {"email": f"bob@{domain}", "display_name": "Bob History", "message_count": 4},
            {"email": f"low@{lower_domain}", "display_name": "Low History", "message_count": 2},
            {"email": f"solo@{history_only_domain}", "display_name": "Solo History", "message_count": 9},
            {"email": "personal@gmail.com", "display_name": "Personal Mail", "message_count": 99},
        ],
        self_aliases=set(),
        skipped_domains={"gmail.com", "intempio.com"},
    )
    materialize_msgvault_senders(database_url)
    upsert_source_event(
        database_url,
        SourceEventIn(
            source_name="calendar",
            source_event_type="calendar_event",
            source_event_key=f"calendar:org-history:{run_id}",
            source_payload={
                "id": "event-1",
                "summary": "MedHistory planning",
                "start": {"dateTime": "2026-05-01T12:00:00Z"},
                "attendees": [
                    {"email": "braydon@intempio.com", "self": True},
                    {"email": f"bob@{domain}", "displayName": "Bob History"},
                ],
            },
            source_posture=SourcePosture.DIRECT_INTERACTION,
            provenance_status="calendar_export",
            trust_role="calendar attendance evidence",
        ),
    )
    materialize_calendar_events(
        database_url,
        self_aliases={"braydon@intempio.com"},
        skipped_domains={"intempio.com"},
    )

    rows = history_backed_organization_worklist(
        database_url,
        limit=1000,
        skipped_domains={"gmail.com", "intempio.com"},
        as_of=datetime(2026, 5, 13, tzinfo=UTC),
    )

    current_rows = [row for row in rows if row["domain"] in {domain, lower_domain, history_only_domain}]
    assert [row["domain"] for row in current_rows] == [domain, history_only_domain, lower_domain]
    first = current_rows[0]
    assert first["company_name"] == company
    assert first["domain"] == domain
    assert first["known_people_count"] == 2
    assert first["direct_people_count"] == 2
    assert first["email_interaction_count"] == 16
    assert first["calendar_interaction_count"] == 1
    assert first["total_interaction_count"] == 17
    assert first["last_interaction_at"] == "2026-05-01T12:00:00+00:00"
    assert first["freshness"]["state"] == "recent"
    assert first["strongest_people"][0]["email"] == f"ann@{domain}"
    assert "Medical Communications Consultant" in first["sample_titles"]
    assert "missing_organization_enrichment" in first["enrichment_reasons"]
    assert "direct_history_present" in first["enrichment_reasons"]

    history_only = next(row for row in rows if row["domain"] == history_only_domain)
    assert history_only["company_name"] == history_only_domain
    assert history_only["known_people_count"] == 0
    assert history_only["direct_people_count"] == 1
    assert history_only["total_interaction_count"] == 9
    assert all(row["domain"] != "gmail.com" for row in rows)


def test_history_backed_organization_worklist_excludes_known_non_target_domains_by_default(database_url):
    run_migrations(database_url)
    ingest_msgvault_sender_rows(
        database_url,
        [
            {"email": "one@rvibe.com", "display_name": "Rvibe Person", "message_count": 50},
            {
                "email": "two@thepracticalaccountant.com",
                "display_name": "Accountant Person",
                "message_count": 40,
            },
            {"email": "three@lehigh.edu", "display_name": "Lehigh Person", "message_count": 30},
            {"email": "four@go2impact.com", "display_name": "Impact Person", "message_count": 20},
            {"email": "five@intempio.us", "display_name": "Intempio US Person", "message_count": 10},
            {"email": "six@intempio.com", "display_name": "Intempio Person", "message_count": 9},
            {"email": "seven@mcco.us", "display_name": "MCCO Person", "message_count": 8},
        ],
        self_aliases=set(),
        skipped_domains=set(),
    )
    materialize_msgvault_senders(database_url)

    rows = history_backed_organization_worklist(database_url, limit=1000)

    domains = {row["domain"] for row in rows}
    assert "rvibe.com" not in domains
    assert "thepracticalaccountant.com" not in domains
    assert "lehigh.edu" not in domains
    assert "go2impact.com" not in domains
    assert "intempio.us" not in domains
    assert "intempio.com" not in domains
    assert "mcco.us" not in domains


def test_history_backed_organization_worklist_filters_system_senders_and_dedupes_people(database_url):
    run_migrations(database_url)
    run_id = uuid4().hex
    domain = f"dedupe-{run_id}.example"
    retail_domain = f"retail-{run_id}.example"
    email = f"person@{domain}"
    for index in range(2):
        upsert_source_event(
            database_url,
            SourceEventIn(
                source_name="next_up",
                source_event_type="curated_contact",
                source_event_key=f"org-enrichment-duplicate:{run_id}:{index}",
                source_payload={
                    "email": email,
                    "first_name": "Duplicate",
                    "last_name": "Person",
                    "title": "Strategy Consultant",
                    "company": f"Dedupe Co {run_id}",
                },
                source_posture=SourcePosture.CURATED_EXPORT,
                provenance_status="test_curated_export",
                trust_role="identity/context seed",
            ),
        )
    materialize_exact_emails(database_url, skipped_domains={"intempio.com"})
    ingest_msgvault_sender_rows(
        database_url,
        [
            {"email": email, "display_name": "Duplicate Person", "message_count": 20},
            {
                "email": f"shipment-tracking@{retail_domain}",
                "display_name": "Shipment Tracking",
                "message_count": 200,
            },
        ],
        self_aliases=set(),
        skipped_domains=set(),
    )
    materialize_msgvault_senders(database_url)

    rows = history_backed_organization_worklist(
        database_url,
        limit=1000,
        skipped_system_localparts=set(),
        skipped_system_prefixes={"shipment"},
    )

    current = next(row for row in rows if row["domain"] == domain)
    assert [person["email"] for person in current["strongest_people"]] == [email]
    assert all(row["domain"] != retail_domain for row in rows)


def test_history_backed_organization_worklist_can_return_only_missing_enrichment(database_url):
    run_migrations(database_url)
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT domain
                FROM (
                  SELECT split_part(lower(source_payload->>'email'), '@', 2) AS domain
                  FROM relationship_substrate.source_event
                  WHERE nullif(source_payload->>'email', '') IS NOT NULL
                  UNION
                  SELECT split_part(lower(primary_email), '@', 2) AS domain
                  FROM relationship_substrate.person
                  WHERE primary_email IS NOT NULL
                ) domains
                WHERE domain IS NOT NULL
                AND domain <> ''
                """
            )
            existing_domains = {row[0] for row in cur.fetchall()}
    run_id = uuid4().hex
    enriched_company = f"Enriched Queue Co {run_id}"
    missing_company = f"Missing Queue Co {run_id}"
    _curated_contact(
        database_url,
        email=f"one@enriched-{run_id}.example",
        title="Medical Communications Consultant",
        company=enriched_company,
    )
    _curated_contact(
        database_url,
        email=f"one@missing-{run_id}.example",
        title="Medical Communications Consultant",
        company=missing_company,
    )
    ingest_msgvault_sender_rows(
        database_url,
        [
            {
                "email": f"one@enriched-{run_id}.example",
                "display_name": "Enriched Queue Person",
                "message_count": 100000,
            },
            {
                "email": f"one@missing-{run_id}.example",
                "display_name": "Missing Queue Person",
                "message_count": 99999,
            },
        ],
        self_aliases=set(),
        skipped_domains=set(),
    )
    materialize_msgvault_senders(database_url)
    upsert_organization_enrichment(
        database_url,
        company_name=enriched_company,
        company_type="public_pharmaceutical_company",
        employee_count_min=1000,
        employee_count_max=1000,
        employee_count_label="1,000",
        source_name="manual_research",
        provenance_status="external_research",
    )

    rows = history_backed_organization_worklist(
        database_url,
        limit=1,
        skipped_domains=existing_domains,
        missing_enrichment_only=True,
    )

    current_company_names = {
        row["company_name"] for row in rows if row["company_name"] in {enriched_company, missing_company}
    }
    assert current_company_names == {missing_company}
