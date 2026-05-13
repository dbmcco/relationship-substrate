from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from relationship_substrate.contracts import SourceEventIn, SourcePosture
from relationship_substrate.db import run_migrations
from relationship_substrate.embeddings import embed_curated_contacts
from relationship_substrate.materialize import materialize_exact_emails
from relationship_substrate.repositories import upsert_source_event
from relationship_substrate.search import search_people


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
    assert current_results[0]["company_people_count"] == 10
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

    results = search_people(
        database_url,
        role_keywords=[],
        semantic_query_embedding=_embedding(1.0),
        company_size_min=10,
        company_size_max=15,
        limit=1000,
    )

    current_results = [row for row in results if row["email"] in {supply_email, unrelated_email}]
    assert [row["email"] for row in current_results] == [supply_email, unrelated_email]
    assert current_results[0]["semantic"]["similarity"] > current_results[1]["semantic"]["similarity"]
    assert "semantic_query" in current_results[0]["match_reasons"]
