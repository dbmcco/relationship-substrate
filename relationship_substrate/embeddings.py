from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

import psycopg
from psycopg.types.json import Jsonb


HASH_EMBEDDING_DIMENSIONS = 1536
DEFAULT_OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_OLLAMA_EMBEDDING_MODEL = "mxbai-embed-large:latest"
DEFAULT_OLLAMA_ENDPOINT = "http://localhost:11434/api/embed"
EMBEDDING_TEXT_VERSION = "curated-contact-v1"

EmbedTexts = Callable[[list[str]], list[list[float]]]


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _vector_literal(vector: list[float]) -> str:
    if not vector:
        raise ValueError("embedding must not be empty")
    return "[" + ",".join(str(float(value)) for value in vector) + "]"


def curated_contact_embedding_text(payload: dict[str, Any]) -> str:
    name_parts = [_clean_text(payload.get("first_name")), _clean_text(payload.get("last_name"))]
    name = payload.get("full_name") or " ".join(part for part in name_parts if part)
    parts = [
        ("Name", name),
        ("Title", payload.get("title")),
        ("Company", payload.get("company")),
        ("Email", payload.get("email")),
    ]
    return "\n".join(f"{label}: {_clean_text(value)}" for label, value in parts if _clean_text(value))


def hash_embed_texts(texts: list[str]) -> list[list[float]]:
    embeddings: list[list[float]] = []
    for text in texts:
        values: list[float] = []
        seed = text.encode("utf-8")
        counter = 0
        while len(values) < HASH_EMBEDDING_DIMENSIONS:
            digest = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
            for byte in digest:
                values.append((byte / 127.5) - 1.0)
                if len(values) == HASH_EMBEDDING_DIMENSIONS:
                    break
            counter += 1
        embeddings.append(values)
    return embeddings


def ollama_embed_texts(
    texts: list[str],
    *,
    model: str | None = None,
    endpoint: str | None = None,
) -> list[list[float]]:
    model = model or os.environ.get("RELATIONSHIP_SUBSTRATE_OLLAMA_EMBEDDING_MODEL", DEFAULT_OLLAMA_EMBEDDING_MODEL)
    endpoint = endpoint or os.environ.get("RELATIONSHIP_SUBSTRATE_OLLAMA_EMBEDDING_ENDPOINT", DEFAULT_OLLAMA_ENDPOINT)
    payload = json.dumps(
        {
            "model": model,
            "input": texts,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ollama embeddings request failed: {exc}") from exc
    data = json.loads(raw)
    if data.get("error"):
        raise RuntimeError(f"Ollama embeddings request failed: {data['error']}")
    embeddings = data.get("embeddings")
    if embeddings is None and data.get("embedding") is not None:
        embeddings = [data["embedding"]]
    if not isinstance(embeddings, list):
        raise RuntimeError("Ollama embeddings response did not include embeddings")
    return embeddings


def openai_embed_texts(
    texts: list[str],
    *,
    api_key: str | None = None,
    model: str | None = None,
    endpoint: str = "https://api.openai.com/v1/embeddings",
) -> list[list[float]]:
    api_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for OpenAI embeddings")
    model = model or os.environ.get("RELATIONSHIP_SUBSTRATE_EMBEDDING_MODEL", DEFAULT_OPENAI_EMBEDDING_MODEL)
    payload = json.dumps(
        {
            "model": model,
            "input": texts,
            "encoding_format": "float",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI embeddings request failed: {exc.code} {detail}") from exc
    data = json.loads(raw)
    return [item["embedding"] for item in sorted(data["data"], key=lambda item: item["index"])]


def embed_curated_contacts(
    database_url: str,
    *,
    embed_texts: EmbedTexts,
    provider_name: str = "custom",
    model: str | None = None,
    limit: int | None = None,
) -> dict[str, int | str]:
    params: list[object] = []
    limit_clause = ""
    if limit is not None:
        limit_clause = "LIMIT %s"
        params.append(limit)

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT p.id, p.primary_email, se.id, se.source_payload
                FROM relationship_substrate.source_event se
                JOIN relationship_substrate.person p
                  ON p.primary_email = lower(se.source_payload->>'email')
                WHERE se.source_name = 'next_up'
                AND se.source_event_type = 'curated_contact'
                AND p.content_embedding IS NULL
                ORDER BY p.updated_at DESC, p.primary_email
                {limit_clause}
                """,
                params,
            )
            rows = cur.fetchall()

    texts = [curated_contact_embedding_text(row[3]) for row in rows]
    vectors = embed_texts(texts) if texts else []
    if len(vectors) != len(rows):
        raise ValueError("embedding provider returned the wrong number of vectors")

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            for row, vector, text in zip(rows, vectors, texts, strict=True):
                cur.execute(
                    """
                    UPDATE relationship_substrate.person
                    SET
                      content_embedding = %s::vector,
                      metadata = metadata || %s,
                      updated_at = now()
                    WHERE id = %s
                    """,
                    (
                        _vector_literal(vector),
                        Jsonb(
                            {
                                "embedding": {
                                    "provider": provider_name,
                                    "model": model,
                                    "source": "next_up",
                                    "source_event_id": str(row[2]),
                                    "text_version": EMBEDDING_TEXT_VERSION,
                                    "text_preview": text[:500],
                                }
                            }
                        ),
                        row[0],
                    ),
                )
        conn.commit()

    return {
        "source": "next_up",
        "provider": provider_name,
        "model": model or "",
        "candidates": len(rows),
        "embedded": len(vectors),
    }
