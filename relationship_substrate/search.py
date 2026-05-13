from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

import psycopg

from relationship_substrate.embeddings import EMBEDDING_DIMENSIONS
from relationship_substrate.freshness import relationship_freshness


DEFAULT_ROLE_KEYWORDS = [
    "consultant",
    "consulting",
    "advisor",
    "advisory",
    "partner",
    "principal",
    "strategy",
    "operations",
    "supply chain",
    "medcom",
    "medical communications",
    "commercial",
]


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _clean_email(value: object) -> str:
    return _clean_text(value).lower()


def _display_name(payload: dict[str, Any]) -> str:
    full_name = _clean_text(payload.get("full_name"))
    if full_name:
        return full_name
    parts = [_clean_text(payload.get("first_name")), _clean_text(payload.get("last_name"))]
    name = " ".join(part for part in parts if part)
    return name or _clean_email(payload.get("email")) or "Unknown person"


def _keyword_matches(*, haystack: str, keywords: list[str]) -> list[str]:
    normalized = haystack.lower()
    return [keyword for keyword in keywords if keyword and keyword.lower() in normalized]


def _relationship_sort_key(row: dict[str, Any]) -> tuple[int, str]:
    relationship = row["relationship"]
    return (
        int(relationship["interaction_count"]),
        str(relationship["last_interaction_at"] or ""),
    )


def _vector_literal(vector: list[float]) -> str:
    if len(vector) != EMBEDDING_DIMENSIONS:
        raise ValueError(f"semantic query embedding must have {EMBEDDING_DIMENSIONS} dimensions")
    return "[" + ",".join(str(float(value)) for value in vector) + "]"


def _semantic_sort_key(row: dict[str, Any]) -> tuple[float, int, str]:
    semantic = row.get("semantic") or {}
    similarity = semantic.get("similarity")
    return (
        float(similarity) if similarity is not None else -2.0,
        int(row["relationship"]["interaction_count"]),
        str(row["relationship"]["last_interaction_at"] or ""),
    )


def _curated_contact_rows(
    database_url: str,
    *,
    semantic_query_embedding: list[float] | None = None,
) -> list[dict[str, Any]]:
    semantic_select = "NULL::double precision AS semantic_distance"
    params: list[object] = []
    if semantic_query_embedding is not None:
        semantic_select = "p.content_embedding <=> %s::vector AS semantic_distance"
        params.append(_vector_literal(semantic_query_embedding))
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                  se.id,
                  se.source_name,
                  se.source_event_key,
                  se.source_payload,
                  se.source_posture,
                  se.provenance_status,
                  p.id,
                  p.primary_email,
                  p.display_name,
                  COALESCE(re.interaction_count, 0) AS interaction_count,
                  re.last_interaction_at,
                  {semantic_select}
                FROM relationship_substrate.source_event se
                LEFT JOIN relationship_substrate.person p
                  ON p.primary_email = lower(se.source_payload->>'email')
                LEFT JOIN relationship_substrate.relationship_edge re
                  ON re.person_id = p.id
                WHERE se.source_name = 'next_up'
                AND se.source_event_type = 'curated_contact'
                AND nullif(se.source_payload->>'email', '') IS NOT NULL
                ORDER BY se.observed_at, se.source_event_key
                """,
                params,
            )
            rows = cur.fetchall()
    return [
        {
            "source_event_id": str(row[0]),
            "source_name": row[1],
            "source_event_key": row[2],
            "payload": row[3],
            "source_posture": row[4],
            "provenance_status": row[5],
            "person_id": str(row[6]) if row[6] else None,
            "primary_email": row[7],
            "person_display_name": row[8],
            "interaction_count": row[9],
            "last_interaction_at": row[10].isoformat() if row[10] else None,
            "semantic_distance": row[11],
        }
        for row in rows
    ]


def search_people(
    database_url: str,
    *,
    role_keywords: list[str] | None = None,
    company_size_min: int | None = None,
    company_size_max: int | None = None,
    semantic_query_embedding: list[float] | None = None,
    sort: str | None = None,
    limit: int = 25,
    as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    rows = _curated_contact_rows(database_url, semantic_query_embedding=semantic_query_embedding)
    company_counts = Counter(
        _clean_text(row["payload"].get("company")) for row in rows if _clean_text(row["payload"].get("company"))
    )
    keywords = (
        [keyword.strip().lower() for keyword in role_keywords if keyword.strip()]
        if role_keywords is not None
        else DEFAULT_ROLE_KEYWORDS
    )

    results: list[dict[str, Any]] = []
    seen_emails: set[str] = set()
    for row in rows:
        payload = row["payload"]
        email = _clean_email(payload.get("email"))
        if not email or email in seen_emails:
            continue
        company = _clean_text(payload.get("company"))
        company_people_count = company_counts.get(company, 0)
        if company_size_min is not None and company_people_count < company_size_min:
            continue
        if company_size_max is not None and company_people_count > company_size_max:
            continue
        title = _clean_text(payload.get("title"))
        keyword_matches = _keyword_matches(haystack=title, keywords=keywords)
        if keywords and not keyword_matches:
            continue

        match_reasons = [f"role_keyword:{keyword}" for keyword in keyword_matches]
        semantic_distance = row["semantic_distance"]
        semantic_similarity = 1.0 - float(semantic_distance) if semantic_distance is not None else None
        if semantic_query_embedding is not None and semantic_similarity is not None:
            match_reasons.append("semantic_query")
        if company_size_min is not None or company_size_max is not None:
            match_reasons.append(f"company_size:{company_people_count}")

        results.append(
            {
                "person_id": row["person_id"],
                "email": email,
                "name": row["person_display_name"] or _display_name(payload),
                "title": title,
                "company": company,
                "company_people_count": company_people_count,
                "relationship": {
                    "interaction_count": row["interaction_count"],
                    "last_interaction_at": row["last_interaction_at"],
                    "freshness": relationship_freshness(row["last_interaction_at"], as_of=as_of),
                },
                "semantic": {
                    "distance": semantic_distance,
                    "similarity": semantic_similarity,
                },
                "match_reasons": match_reasons,
                "evidence": {
                    "source_event_id": row["source_event_id"],
                    "source_name": row["source_name"],
                    "source_event_key": row["source_event_key"],
                    "source_posture": row["source_posture"],
                    "provenance_status": row["provenance_status"],
                },
            }
        )
        seen_emails.add(email)

    sort_mode = sort or ("semantic" if semantic_query_embedding is not None and not keywords else "relationship")
    key = _semantic_sort_key if sort_mode == "semantic" else _relationship_sort_key
    return sorted(results, key=key, reverse=True)[:limit]
