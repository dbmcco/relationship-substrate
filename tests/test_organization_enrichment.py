from __future__ import annotations

from relationship_substrate.contracts import SourceEventIn, SourcePosture
from relationship_substrate.db import run_migrations
from relationship_substrate.organizations import (
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
