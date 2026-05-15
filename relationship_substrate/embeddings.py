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
PERSON_EMBEDDING_TEXT_VERSION = "person-profile-v1"
ORGANIZATION_EMBEDDING_TEXT_VERSION = "organization-profile-v1"

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


def person_embedding_text(payload: dict[str, Any]) -> str:
    parts = [
        ("Name", payload.get("display_name")),
        ("Email", payload.get("primary_email")),
        ("Source posture", payload.get("source_posture")),
        ("Provenance", payload.get("provenance_status")),
    ]
    lines = [f"{label}: {_clean_text(value)}" for label, value in parts if _clean_text(value)]
    affiliations = payload.get("affiliations") or []
    for affiliation in affiliations:
        organization = _clean_text(affiliation.get("organization"))
        role = _clean_text(affiliation.get("role_or_title"))
        domain = _clean_text(affiliation.get("domain"))
        if organization or role or domain:
            line = "Affiliation: "
            if role:
                line += role
            if organization:
                line += f" at {organization}" if role else organization
            if domain:
                line += f" ({domain})"
            lines.append(line)
    relationship = payload.get("relationship") or {}
    if relationship:
        lines.append(f"Interaction count: {int(relationship.get('interaction_count') or 0)}")
        lines.append(f"Calendar interactions: {int(relationship.get('calendar_interaction_count') or 0)}")
        lines.append(f"Email messages: {int(relationship.get('email_message_count') or 0)}")
        if _clean_text(relationship.get("last_interaction_at")):
            lines.append(f"Last interaction: {_clean_text(relationship.get('last_interaction_at'))}")
    return "\n".join(lines)


def organization_embedding_text(payload: dict[str, Any]) -> str:
    parts = [
        ("Organization", payload.get("name")),
        ("Domain", payload.get("domain")),
        ("Source posture", payload.get("source_posture")),
        ("Provenance", payload.get("provenance_status")),
    ]
    lines = [f"{label}: {_clean_text(value)}" for label, value in parts if _clean_text(value)]
    enrichment = payload.get("enrichment") or {}
    enrichment_parts = [
        ("Company type", enrichment.get("company_type")),
        ("Employee count label", enrichment.get("employee_count_label")),
        ("Employee count min", enrichment.get("employee_count_min")),
        ("Employee count max", enrichment.get("employee_count_max")),
        ("Consultant count estimate", enrichment.get("consultant_count_estimate")),
        ("Source", enrichment.get("source_name")),
        ("Source URL", enrichment.get("source_url")),
    ]
    lines.extend(f"{label}: {_clean_text(value)}" for label, value in enrichment_parts if _clean_text(value))
    relationship = payload.get("relationship") or {}
    if relationship:
        lines.append(f"Known affiliated people: {int(relationship.get('affiliated_people_count') or 0)}")
        lines.append(f"Total interaction count: {int(relationship.get('total_interaction_count') or 0)}")
        if _clean_text(relationship.get("last_interaction_at")):
            lines.append(f"Last interaction: {_clean_text(relationship.get('last_interaction_at'))}")
    return "\n".join(lines)


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


def embed_missing_people(
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
                SELECT
                  p.id,
                  p.display_name,
                  p.primary_email,
                  p.source_posture,
                  p.provenance_status,
                  p.metadata,
                  COALESCE(e.interaction_count, 0)::int AS interaction_count,
                  e.first_interaction_at,
                  e.last_interaction_at,
                  e.metadata AS relationship_metadata,
                  COALESCE(
                    jsonb_agg(
                      DISTINCT jsonb_build_object(
                        'organization', o.name,
                        'domain', o.domain,
                        'role_or_title', a.role_or_title
                      )
                    ) FILTER (WHERE o.id IS NOT NULL),
                    '[]'::jsonb
                  ) AS affiliations
                FROM relationship_substrate.person p
                LEFT JOIN relationship_substrate.relationship_edge e
                  ON e.person_id = p.id
                LEFT JOIN relationship_substrate.affiliation a
                  ON a.person_id = p.id
                LEFT JOIN relationship_substrate.organization o
                  ON o.id = a.organization_id
                WHERE p.content_embedding IS NULL
                AND (
                  nullif(p.primary_email, '') IS NOT NULL
                  OR nullif(p.display_name, '') IS NOT NULL
                )
                GROUP BY p.id, e.id
                ORDER BY
                  COALESCE(e.interaction_count, 0) DESC,
                  e.last_interaction_at DESC NULLS LAST,
                  p.updated_at DESC,
                  p.primary_email NULLS LAST,
                  p.display_name
                {limit_clause}
                """,
                params,
            )
            rows = cur.fetchall()

    payloads: list[dict[str, Any]] = []
    for row in rows:
        relationship_metadata = row[9] or {}
        payloads.append(
            {
                "display_name": row[1],
                "primary_email": row[2],
                "source_posture": row[3],
                "provenance_status": row[4],
                "metadata": row[5] or {},
                "relationship": {
                    "interaction_count": row[6],
                    "first_interaction_at": row[7].isoformat() if row[7] else None,
                    "last_interaction_at": row[8].isoformat() if row[8] else None,
                    "calendar_interaction_count": relationship_metadata.get("calendar_interaction_count"),
                    "email_message_count": relationship_metadata.get("email_message_count"),
                },
                "affiliations": row[10] or [],
            }
        )
    texts = [person_embedding_text(payload) for payload in payloads]
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
                                    "source": "all_people",
                                    "text_version": PERSON_EMBEDDING_TEXT_VERSION,
                                    "text_preview": text[:500],
                                }
                            }
                        ),
                        row[0],
                    ),
                )
        conn.commit()

    return {
        "source": "all_people",
        "provider": provider_name,
        "model": model or "",
        "candidates": len(rows),
        "embedded": len(vectors),
    }


def embed_missing_organizations(
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
                SELECT
                  o.id,
                  o.name,
                  o.domain,
                  o.source_posture,
                  o.provenance_status,
                  o.metadata,
                  count(DISTINCT a.person_id)::int AS affiliated_people_count,
                  COALESCE(sum(e.interaction_count), 0)::int AS total_interaction_count,
                  max(e.last_interaction_at) AS last_interaction_at
                FROM relationship_substrate.organization o
                LEFT JOIN relationship_substrate.affiliation a
                  ON a.organization_id = o.id
                LEFT JOIN relationship_substrate.relationship_edge e
                  ON e.person_id = a.person_id
                WHERE o.content_embedding IS NULL
                GROUP BY o.id
                ORDER BY
                  COALESCE(sum(e.interaction_count), 0) DESC,
                  count(DISTINCT a.person_id) DESC,
                  o.updated_at DESC,
                  o.name
                {limit_clause}
                """,
                params,
            )
            rows = cur.fetchall()

    payloads: list[dict[str, Any]] = []
    for row in rows:
        metadata = row[5] or {}
        payloads.append(
            {
                "name": row[1],
                "domain": row[2],
                "source_posture": row[3],
                "provenance_status": row[4],
                "metadata": metadata,
                "enrichment": metadata.get("enrichment") or {},
                "relationship": {
                    "affiliated_people_count": row[6],
                    "total_interaction_count": row[7],
                    "last_interaction_at": row[8].isoformat() if row[8] else None,
                },
            }
        )
    texts = [organization_embedding_text(payload) for payload in payloads]
    vectors = embed_texts(texts) if texts else []
    if len(vectors) != len(rows):
        raise ValueError("embedding provider returned the wrong number of vectors")

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            for row, vector, text in zip(rows, vectors, texts, strict=True):
                cur.execute(
                    """
                    UPDATE relationship_substrate.organization
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
                                    "source": "organizations",
                                    "text_version": ORGANIZATION_EMBEDDING_TEXT_VERSION,
                                    "text_preview": text[:500],
                                }
                            }
                        ),
                        row[0],
                    ),
                )
        conn.commit()

    return {
        "source": "organizations",
        "provider": provider_name,
        "model": model or "",
        "candidates": len(rows),
        "embedded": len(vectors),
    }
