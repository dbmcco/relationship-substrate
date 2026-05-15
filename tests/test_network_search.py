from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from relationship_substrate.cli import ingest_msgvault_sender_rows
from relationship_substrate.contracts import SourceEventIn, SourcePosture
from relationship_substrate.db import run_migrations
from relationship_substrate.embeddings import embed_curated_contacts
from relationship_substrate.materialize import materialize_exact_emails, materialize_msgvault_senders
from relationship_substrate.organizations import upsert_organization_enrichment
from relationship_substrate.repositories import upsert_source_event
from relationship_substrate.search import search_history_backed_people, search_people


def _curated_contact(
    database_url: str,
    *,
    email: str,
    title: str,
    company: str,
    full_name: str,
) -> None:
    upsert_source_event(
        database_url,
        SourceEventIn(
            source_name="next_up",
            source_event_type="curated_contact",
            source_event_key=f"test-next-up:{email}",
            source_payload={
                "email": email,
                "full_name": full_name,
                "title": title,
                "company": company,
            },
            source_posture=SourcePosture.CURATED_EXPORT,
            provenance_status="test_curated_export",
            trust_role="identity/context seed",
        ),
    )


def _set_relationship_strength(
    database_url: str,
    *,
    email: str,
    interaction_count: int,
    last_interaction_at: datetime,
) -> None:
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM relationship_substrate.person WHERE primary_email = %s",
                (email,),
            )
            person_id = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO relationship_substrate.relationship_edge (
                  person_id, first_interaction_at, last_interaction_at, interaction_count, metadata
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (person_id)
                DO UPDATE SET
                  first_interaction_at = EXCLUDED.first_interaction_at,
                  last_interaction_at = EXCLUDED.last_interaction_at,
                  interaction_count = EXCLUDED.interaction_count,
                  metadata = EXCLUDED.metadata
                """,
                (
                    person_id,
                    last_interaction_at,
                    last_interaction_at,
                    interaction_count,
                    Jsonb({"source": "test"}),
                ),
            )
        conn.commit()


def _set_person_embedding(database_url: str, *, email: str, embedding: list[float]) -> None:
    vector = "[" + ",".join(str(value) for value in embedding) + "]"
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE relationship_substrate.person
                SET content_embedding = %s::vector
                WHERE primary_email = %s
                """,
                (vector, email),
            )
        conn.commit()


def _embedding(first: float, second: float = 0.0) -> list[float]:
    return [first, second, *([0.0] * 1534)]


def test_search_people_filters_consultant_like_roles_by_company_size_and_ranks_by_strength(
    database_url,
):
    run_migrations(database_url)
    run_id = uuid4().hex
    company = f"Signal Advisory {run_id}"
    stronger_email = f"strong-{run_id}@example.com"
    weaker_email = f"weak-{run_id}@example.com"
    outsider_email = f"outsider-{run_id}@example.com"

    _curated_contact(
        database_url,
        email=stronger_email,
        title="Principal Consultant, Supply Chain",
        company=company,
        full_name="Strong Consultant",
    )
    _curated_contact(
        database_url,
        email=weaker_email,
        title="Medical Communications Advisor",
        company=company,
        full_name="Weak Consultant",
    )
    for index in range(8):
        _curated_contact(
            database_url,
            email=f"peer-{index}-{run_id}@example.com",
            title="Delivery Lead",
            company=company,
            full_name=f"Peer {index}",
        )
    _curated_contact(
        database_url,
        email=outsider_email,
        title="Principal Consultant",
        company=f"Too Small Consulting {run_id}",
        full_name="Outside Consultant",
    )
    materialize_exact_emails(database_url)
    _set_relationship_strength(
        database_url,
        email=stronger_email,
        interaction_count=12,
        last_interaction_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    _set_relationship_strength(
        database_url,
        email=weaker_email,
        interaction_count=3,
        last_interaction_at=datetime(2026, 2, 1, tzinfo=UTC),
    )

    results = search_people(
        database_url,
        role_keywords=["consultant", "advisor", "medical communications", "supply chain"],
        company_size_min=10,
        company_size_max=15,
        limit=1000,
        as_of=datetime(2026, 5, 13, tzinfo=UTC),
    )

    current_results = [row for row in results if row["email"] in {stronger_email, weaker_email, outsider_email}]
    assert [row["email"] for row in current_results] == [stronger_email, weaker_email]
    assert outsider_email not in {row["email"] for row in results}
    assert current_results[0]["relationship"]["interaction_count"] == 12
    assert current_results[0]["relationship"]["freshness"]["state"] == "recent"
    assert current_results[0]["known_people_at_company_count"] == 10
    assert "company_people_count" not in current_results[0]
    assert "role_keyword:consultant" in current_results[0]["match_reasons"]
    assert current_results[0]["evidence"]["source_name"] == "next_up"


def test_embed_curated_contacts_populates_person_vectors(database_url):
    run_migrations(database_url)
    run_id = uuid4().hex
    email = f"embed-{run_id}@example.com"
    captured_texts: list[str] = []

    _curated_contact(
        database_url,
        email=email,
        title="Supply Chain Consultant",
        company=f"Embedding Advisors {run_id}",
        full_name="Embedding Person",
    )
    materialize_exact_emails(database_url)

    def fake_embed(texts: list[str]) -> list[list[float]]:
        captured_texts.extend(texts)
        return [_embedding(1.0) for _ in texts]

    report = embed_curated_contacts(database_url, embed_texts=fake_embed)

    assert report["embedded"] >= 1
    assert any("Supply Chain Consultant" in text for text in captured_texts)
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT content_embedding IS NOT NULL
                FROM relationship_substrate.person
                WHERE primary_email = %s
                """,
                (email,),
            )
            assert cur.fetchone() == (True,)


def test_search_people_can_use_semantic_similarity_without_role_keywords(database_url):
    run_migrations(database_url)
    run_id = uuid4().hex
    company = f"Semantic Advisors {run_id}"
    supply_email = f"supply-{run_id}@example.com"
    unrelated_email = f"unrelated-{run_id}@example.com"

    _curated_contact(
        database_url,
        email=supply_email,
        title="Partner",
        company=company,
        full_name="Supply Partner",
    )
    _curated_contact(
        database_url,
        email=unrelated_email,
        title="Partner",
        company=company,
        full_name="Unrelated Partner",
    )
    for index in range(8):
        _curated_contact(
            database_url,
            email=f"semantic-peer-{index}-{run_id}@example.com",
            title="Delivery Lead",
            company=company,
            full_name=f"Semantic Peer {index}",
        )
    materialize_exact_emails(database_url)
    _set_person_embedding(database_url, email=supply_email, embedding=_embedding(1.0))
    _set_person_embedding(database_url, email=unrelated_email, embedding=_embedding(0.0, 1.0))
    upsert_organization_enrichment(
        database_url,
        company_name=company,
        company_type="test_consultancy",
        employee_count_min=1234,
        employee_count_max=1234,
        employee_count_label="test_fixture",
        source_name="test_fixture",
        provenance_status="test",
    )

    results = search_people(
        database_url,
        role_keywords=[],
        semantic_query_embedding=_embedding(1.0),
        company_size_min=10,
        company_size_max=15,
        actual_employee_count_min=1234,
        actual_employee_count_max=1234,
        limit=1000,
    )

    current_results = [row for row in results if row["email"] in {supply_email, unrelated_email}]
    assert [row["email"] for row in current_results] == [supply_email, unrelated_email]
    assert current_results[0]["semantic"]["similarity"] > current_results[1]["semantic"]["similarity"]
    assert "semantic_query" in current_results[0]["match_reasons"]


def test_search_people_separates_known_people_count_from_organization_enrichment(database_url):
    run_migrations(database_url)
    run_id = uuid4().hex
    company = f"Enterprise Pharma {run_id}"
    email = f"enterprise-{run_id}@example.com"

    _curated_contact(
        database_url,
        email=email,
        title="Medical Communications Lead",
        company=company,
        full_name="Enterprise Contact",
    )
    for index in range(9):
        _curated_contact(
            database_url,
            email=f"enterprise-peer-{index}-{run_id}@example.com",
            title="Peer",
            company=company,
            full_name=f"Enterprise Peer {index}",
        )
    materialize_exact_emails(database_url)
    upsert_organization_enrichment(
        database_url,
        company_name=company,
        company_type="public_pharmaceutical_company",
        employee_count_min=50000,
        employee_count_label="enterprise",
        source_name="manual_research",
        source_url="https://example.com/company-profile",
        provenance_status="external_research",
    )

    result = next(
        row
        for row in search_people(
            database_url,
            role_keywords=["medical communications"],
            known_people_at_company_min=10,
            known_people_at_company_max=15,
            limit=1000,
        )
        if row["email"] == email
    )

    assert result["known_people_at_company_count"] == 10
    assert result["organization_enrichment"] == {
        "company_type": "public_pharmaceutical_company",
        "employee_count_label": "enterprise",
        "employee_count_min": 50000,
        "employee_count_max": None,
        "consultant_count_estimate": None,
        "source_name": "manual_research",
        "source_url": "https://example.com/company-profile",
        "provenance_status": "external_research",
    }


def test_search_people_filters_by_actual_organization_size_not_known_people(database_url):
    run_migrations(database_url)
    run_id = uuid4().hex
    small_company = f"Small Medcoms {run_id}"
    enterprise_company = f"Enterprise Pharma Size Filter {run_id}"
    unknown_company = f"Unknown Size Medcoms {run_id}"
    broad_range_company = f"Broad Range Medcoms {run_id}"
    small_email = f"small-size-{run_id}@example.com"
    enterprise_email = f"enterprise-size-{run_id}@example.com"
    unknown_email = f"unknown-size-{run_id}@example.com"
    broad_range_email = f"broad-range-{run_id}@example.com"

    for company, email in [
        (small_company, small_email),
        (enterprise_company, enterprise_email),
        (unknown_company, unknown_email),
        (broad_range_company, broad_range_email),
    ]:
        _curated_contact(
            database_url,
            email=email,
            title="Medical Communications Consultant",
            company=company,
            full_name=f"Contact {company}",
        )
        for index in range(14):
            _curated_contact(
                database_url,
                email=f"peer-{index}-{email}",
                title="Peer",
                company=company,
                full_name=f"Peer {index}",
            )
    materialize_exact_emails(database_url)
    upsert_organization_enrichment(
        database_url,
        company_name=small_company,
        company_type="medical_communications_consultancy",
        employee_count_min=10,
        employee_count_max=20,
        employee_count_label="small_team",
        source_name="manual_research",
        provenance_status="external_research",
    )
    upsert_organization_enrichment(
        database_url,
        company_name=enterprise_company,
        company_type="public_pharmaceutical_company",
        employee_count_min=50000,
        employee_count_label="enterprise",
        source_name="manual_research",
        provenance_status="external_research",
    )
    upsert_organization_enrichment(
        database_url,
        company_name=broad_range_company,
        company_type="medical_communications_consultancy",
        employee_count_min=11,
        employee_count_max=50,
        employee_count_label="small_to_mid_market",
        source_name="manual_research",
        provenance_status="external_research",
    )

    results = search_people(
        database_url,
        role_keywords=["medical communications", "consultant"],
        actual_employee_count_min=10,
        actual_employee_count_max=20,
        limit=1000,
    )

    result_emails = {row["email"] for row in results}
    result = next(row for row in results if row["email"] == small_email)
    assert small_email in result_emails
    assert enterprise_email not in result_emails
    assert unknown_email not in result_emails
    assert broad_range_email not in result_emails
    assert result["known_people_at_company_count"] == 15
    assert result["organization_enrichment"]["employee_count_min"] == 10
    assert result["organization_enrichment"]["employee_count_max"] == 20


def test_search_people_filters_by_enriched_consultant_count(database_url):
    run_migrations(database_url)
    run_id = uuid4().hex
    target_company = f"Team Sized Medcoms {run_id}"
    too_small_company = f"Tiny Medcoms {run_id}"
    unknown_company = f"Unknown Team Medcoms {run_id}"
    target_email = f"team-sized-{run_id}@example.com"
    too_small_email = f"tiny-team-{run_id}@example.com"
    unknown_email = f"unknown-team-{run_id}@example.com"

    for company, email in [
        (target_company, target_email),
        (too_small_company, too_small_email),
        (unknown_company, unknown_email),
    ]:
        _curated_contact(
            database_url,
            email=email,
            title="Medical Communications Consultant",
            company=company,
            full_name=f"Contact {company}",
        )
    materialize_exact_emails(database_url)
    upsert_organization_enrichment(
        database_url,
        company_name=target_company,
        company_type="medical_communications_consultancy",
        employee_count_min=11,
        employee_count_max=50,
        employee_count_label="small_to_mid_market",
        consultant_count_estimate=14,
        source_name="linkedin_employee_profiles",
        provenance_status="external_research",
    )
    upsert_organization_enrichment(
        database_url,
        company_name=too_small_company,
        company_type="medical_communications_consultancy",
        employee_count_min=2,
        employee_count_max=10,
        employee_count_label="small_team",
        consultant_count_estimate=7,
        source_name="linkedin_employee_profiles",
        provenance_status="external_research",
    )

    results = search_people(
        database_url,
        role_keywords=["medical communications", "consultant"],
        consultant_count_min=10,
        consultant_count_max=20,
        limit=1000,
    )

    result_emails = {row["email"] for row in results}
    result = next(row for row in results if row["email"] == target_email)
    assert target_email in result_emails
    assert too_small_email not in result_emails
    assert unknown_email not in result_emails
    assert "consultant_count_estimate:14" in result["match_reasons"]
    assert result["organization_enrichment"]["consultant_count_estimate"] == 14


def test_search_people_matches_curated_company_alias_to_enrichment(database_url):
    run_migrations(database_url)
    run_id = uuid4().hex
    company = f"Canonical Medcoms {run_id}"
    curated_alias = f"Canonical Medical Communications {run_id}"
    email = f"curated-alias-{run_id}@example.com"
    _curated_contact(
        database_url,
        email=email,
        title="Medical Communications Consultant",
        company=curated_alias,
        full_name="Curated Alias Contact",
    )
    materialize_exact_emails(database_url)
    upsert_organization_enrichment(
        database_url,
        company_name=company,
        aliases=[curated_alias],
        company_type="medical_communications_consultancy",
        employee_count_min=10,
        employee_count_max=20,
        employee_count_label="small_team",
        consultant_count_estimate=12,
        source_name="manual_research",
        provenance_status="external_research",
    )

    rows = search_people(
        database_url,
        role_keywords=["medical communications", "consultant"],
        actual_employee_count_min=10,
        actual_employee_count_max=20,
        consultant_count_min=10,
        consultant_count_max=20,
        limit=1000,
    )

    result = next(row for row in rows if row["email"] == email)
    assert result["company"] == curated_alias
    assert result["organization_enrichment"]["company_type"] == "medical_communications_consultancy"
    assert result["organization_enrichment"]["aliases"] == [curated_alias.lower()]


def test_search_history_backed_people_filters_by_domain_organization_enrichment(database_url):
    run_migrations(database_url)
    run_id = uuid4().hex
    target_domain = f"target-history-{run_id}.example"
    excluded_domain = f"excluded-history-{run_id}.example"
    ingest_msgvault_sender_rows(
        database_url,
        [
            {"email": f"strong@{target_domain}", "display_name": "Strong Target", "message_count": 20},
            {"email": f"weak@{target_domain}", "display_name": "Weak Target", "message_count": 3},
            {"email": f"big@{excluded_domain}", "display_name": "Big Excluded", "message_count": 50},
        ],
        self_aliases=set(),
        skipped_domains=set(),
    )
    materialize_msgvault_senders(database_url)
    upsert_organization_enrichment(
        database_url,
        company_name=target_domain,
        company_type="life_sciences_training_consultancy",
        employee_count_min=18,
        employee_count_max=18,
        employee_count_label="test public team count",
        consultant_count_estimate=18,
        source_name="test",
        provenance_status="test",
    )
    upsert_organization_enrichment(
        database_url,
        company_name=excluded_domain,
        company_type="large_company",
        employee_count_min=51,
        employee_count_max=200,
        employee_count_label="test large company",
        consultant_count_estimate=100,
        source_name="test",
        provenance_status="test",
    )

    rows = search_history_backed_people(
        database_url,
        actual_employee_count_min=10,
        actual_employee_count_max=20,
        consultant_count_min=10,
        consultant_count_max=20,
        limit=1000,
    )

    current = [row for row in rows if row["domain"] == target_domain]
    assert [row["email"] for row in current] == [
        f"strong@{target_domain}",
        f"weak@{target_domain}",
    ]
    assert all(row["domain"] != excluded_domain for row in rows)


def test_search_history_backed_people_matches_enrichment_domain_and_alias(database_url):
    run_migrations(database_url)
    run_id = uuid4().hex
    domain = f"alias-history-{run_id}.example"
    alias_domain = f"legacy-alias-{run_id}.example"
    company = f"Alias Matched Medcoms {run_id}"
    domain_email = f"domain-person@{domain}"
    alias_email = f"alias-person@{alias_domain}"
    ingest_msgvault_sender_rows(
        database_url,
        [
            {"email": domain_email, "display_name": "Domain Person", "message_count": 18},
            {"email": alias_email, "display_name": "Alias Person", "message_count": 16},
        ],
        self_aliases=set(),
        skipped_domains=set(),
    )
    materialize_msgvault_senders(database_url)
    upsert_organization_enrichment(
        database_url,
        company_name=company,
        domain=domain,
        aliases=[alias_domain],
        company_type="medical_communications_consultancy",
        employee_count_min=10,
        employee_count_max=20,
        employee_count_label="small_team",
        consultant_count_estimate=12,
        source_name="manual_research",
        provenance_status="external_research",
    )

    rows = search_history_backed_people(
        database_url,
        actual_employee_count_min=10,
        actual_employee_count_max=20,
        consultant_count_min=10,
        consultant_count_max=20,
        limit=1000,
    )

    current = [row for row in rows if row["email"] in {domain_email, alias_email}]
    assert [row["email"] for row in current] == [domain_email, alias_email]
    assert {row["company"] for row in current} == {company}
    assert all(row["organization_enrichment"]["domain"] == domain for row in current)
    assert all(alias_domain in row["organization_enrichment"]["aliases"] for row in current)
