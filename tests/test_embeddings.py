from __future__ import annotations

import json

import psycopg

from relationship_substrate.db import run_migrations
from relationship_substrate.embeddings import ollama_embed_texts


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
