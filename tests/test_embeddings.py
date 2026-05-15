from __future__ import annotations

import json
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from relationship_substrate.db import run_migrations
from relationship_substrate.embeddings import embed_missing_organizations, embed_missing_people, ollama_embed_texts


class _FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_ollama_embed_texts_uses_local_embed_api(monkeypatch):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return _FakeResponse(
            {
                "model": "mxbai-embed-large:latest",
                "embeddings": [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]],
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    vectors = ollama_embed_texts(
        ["consulting advisor", "supply chain operator"],
        model="mxbai-embed-large:latest",
        endpoint="http://localhost:11434/api/embed",
    )

    request, timeout = requests[0]
    payload = json.loads(request.data)
    assert request.full_url == "http://localhost:11434/api/embed"
    assert payload == {
        "model": "mxbai-embed-large:latest",
        "input": ["consulting advisor", "supply chain operator"],
    }
    assert timeout == 60
    assert vectors == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]


def test_migrations_allow_variable_embedding_dimensions(database_url):
    run_migrations(database_url)

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT att.atttypmod
                FROM pg_attribute att
                JOIN pg_class cls ON cls.oid = att.attrelid
                JOIN pg_namespace ns ON ns.oid = cls.relnamespace
                WHERE ns.nspname = 'relationship_substrate'
                AND cls.relname = 'person'
                AND att.attname = 'content_embedding'
                """
            )
            assert cur.fetchone() == (-1,)


def test_embed_missing_people_uses_relationship_and_affiliation_context(database_url):
    run_migrations(database_url)
    run_id = uuid4().hex
    email = f"pat-consultant-{run_id}@example.com"
    domain = f"signal-advisory-{run_id}.example"
    captured_texts: list[str] = []
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO relationship_substrate.organization (
                  name, domain, source_posture, provenance_status
                )
                VALUES ('Signal Advisory', %s, 'test', 'test')
                RETURNING id
                """,
                (domain,),
            )
            organization_id = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO relationship_substrate.person (
                  display_name, primary_email, source_posture, provenance_status
                )
                VALUES ('Pat Consultant', %s, 'test', 'test')
                RETURNING id
                """,
                (email,),
            )
            person_id = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO relationship_substrate.affiliation (
                  person_id, organization_id, role_or_title, source_posture, provenance_status
                )
                VALUES (%s, %s, 'Principal Consultant', 'test', 'test')
                """,
                (person_id, organization_id),
            )
            cur.execute(
                """
                INSERT INTO relationship_substrate.relationship_edge (
                  person_id, interaction_count, metadata
                )
                VALUES (%s, 12, %s)
                """,
                (person_id, Jsonb({"calendar_interaction_count": 3, "email_message_count": 9})),
            )
        conn.commit()

    def fake_embed(texts: list[str]) -> list[list[float]]:
        captured_texts.extend(texts)
        return [[0.1, 0.2, 0.3] for _ in texts]

    report = embed_missing_people(
        database_url,
        embed_texts=fake_embed,
        provider_name="test",
        model="test-model",
        limit=100000,
    )

    assert report["embedded"] >= 1
    assert any("Pat Consultant" in text for text in captured_texts)
    assert any("Principal Consultant" in text for text in captured_texts)
    assert any("Signal Advisory" in text for text in captured_texts)
    assert any("Interaction count: 12" in text for text in captured_texts)
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT content_embedding IS NOT NULL, metadata->'embedding'->>'source'
                FROM relationship_substrate.person
                WHERE primary_email = %s
                """,
                (email,),
            )
            assert cur.fetchone() == (True, "all_people")


def test_embed_missing_organizations_uses_enrichment_context(database_url):
    run_migrations(database_url)
    run_id = uuid4().hex
    domain = f"small-medcoms-{run_id}.example"
    captured_texts: list[str] = []
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO relationship_substrate.organization (
                  name, domain, source_posture, provenance_status, metadata
                )
                VALUES ('Small Medcoms', %s, 'test', 'test', %s)
                """,
                (
                    domain,
                    Jsonb(
                        {
                            "enrichment": {
                                "company_type": "medical communications consultancy",
                                "employee_count_min": 10,
                                "employee_count_max": 15,
                                "consultant_count_estimate": 12,
                            }
                        }
                    ),
                ),
            )
        conn.commit()

    def fake_embed(texts: list[str]) -> list[list[float]]:
        captured_texts.extend(texts)
        return [[0.4, 0.5, 0.6] for _ in texts]

    report = embed_missing_organizations(
        database_url,
        embed_texts=fake_embed,
        provider_name="test",
        model="test-model",
        limit=100000,
    )

    assert report["embedded"] >= 1
    assert any("Small Medcoms" in text for text in captured_texts)
    assert any("medical communications consultancy" in text for text in captured_texts)
    assert any("Consultant count estimate: 12" in text for text in captured_texts)
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT content_embedding IS NOT NULL, metadata->'embedding'->>'source'
                FROM relationship_substrate.organization
                WHERE domain = %s
                """,
                (domain,),
            )
            assert cur.fetchone() == (True, "organizations")
