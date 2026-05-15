from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

import psycopg

from relationship_substrate.freshness import relationship_freshness
from relationship_substrate.organizations import organization_enrichment_by_name


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
    if not vector:
        raise ValueError("semantic query embedding must not be empty")
    return "[" + ",".join(str(float(value)) for value in vector) + "]"


def _semantic_sort_key(row: dict[str, Any]) -> tuple[float, int, str]:
    semantic = row.get("semantic") or {}
    similarity = semantic.get("similarity")
    return (
        float(similarity) if similarity is not None else -2.0,
        int(row["relationship"]["interaction_count"]),
        str(row["relationship"]["last_interaction_at"] or ""),
    )


def _enrichment_matches_employee_range(
    enrichment: dict[str, Any] | None,
    *,
    actual_employee_count_min: int | None,
    actual_employee_count_max: int | None,
) -> bool:
    if actual_employee_count_min is None and actual_employee_count_max is None:
        return True
    if enrichment is None:
        return False
    employee_min = enrichment.get("employee_count_min")
    employee_max = enrichment.get("employee_count_max")
    if actual_employee_count_min is not None and employee_min is None:
        return False
    if actual_employee_count_max is not None and employee_max is None:
        return False
    if actual_employee_count_min is not None and int(employee_min) < actual_employee_count_min:
        return False
    if actual_employee_count_max is not None and int(employee_max) > actual_employee_count_max:
        return False
    return True


def _enrichment_matches_consultant_count(
    enrichment: dict[str, Any] | None,
    *,
    consultant_count_min: int | None,
    consultant_count_max: int | None,
) -> bool:
    if consultant_count_min is None and consultant_count_max is None:
        return True
    if enrichment is None:
        return False
    consultant_count = enrichment.get("consultant_count_estimate")
    if consultant_count is None:
        return False
    consultant_count = int(consultant_count)
    if consultant_count_min is not None and consultant_count < consultant_count_min:
        return False
    if consultant_count_max is not None and consultant_count > consultant_count_max:
        return False
    return True


def _curated_contact_rows(
    database_url: str,
    *,
    semantic_query_embedding: list[float] | None = None,
) -> list[dict[str, Any]]:
    semantic_select = "NULL::double precision AS semantic_distance"
    params: list[object] = []
    if semantic_query_embedding is not None:
        semantic_select = """
          CASE
            WHEN p.content_embedding IS NOT NULL
            AND vector_dims(p.content_embedding) = %s
            THEN p.content_embedding <=> %s::vector
            ELSE NULL
          END AS semantic_distance
        """
        params.extend([len(semantic_query_embedding), _vector_literal(semantic_query_embedding)])
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
    known_people_at_company_min: int | None = None,
    known_people_at_company_max: int | None = None,
    actual_employee_count_min: int | None = None,
    actual_employee_count_max: int | None = None,
    consultant_count_min: int | None = None,
    consultant_count_max: int | None = None,
    semantic_query_embedding: list[float] | None = None,
    sort: str | None = None,
    limit: int = 25,
    as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    known_people_at_company_min = (
        company_size_min if known_people_at_company_min is None else known_people_at_company_min
    )
    known_people_at_company_max = (
        company_size_max if known_people_at_company_max is None else known_people_at_company_max
    )
    rows = _curated_contact_rows(database_url, semantic_query_embedding=semantic_query_embedding)
    organization_enrichments = organization_enrichment_by_name(database_url)
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
        known_people_at_company_count = company_counts.get(company, 0)
        if (
            known_people_at_company_min is not None
            and known_people_at_company_count < known_people_at_company_min
        ):
            continue
        if (
            known_people_at_company_max is not None
            and known_people_at_company_count > known_people_at_company_max
        ):
            continue
        organization_enrichment = organization_enrichments.get(company.lower())
        if not _enrichment_matches_employee_range(
            organization_enrichment,
            actual_employee_count_min=actual_employee_count_min,
            actual_employee_count_max=actual_employee_count_max,
        ):
            continue
        if not _enrichment_matches_consultant_count(
            organization_enrichment,
            consultant_count_min=consultant_count_min,
            consultant_count_max=consultant_count_max,
        ):
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
        if known_people_at_company_min is not None or known_people_at_company_max is not None:
            match_reasons.append(f"known_people_at_company:{known_people_at_company_count}")
        if consultant_count_min is not None or consultant_count_max is not None:
            consultant_count = (
                organization_enrichment["consultant_count_estimate"] if organization_enrichment else None
            )
            match_reasons.append(f"consultant_count_estimate:{consultant_count}")

        results.append(
            {
                "person_id": row["person_id"],
                "email": email,
                "name": row["person_display_name"] or _display_name(payload),
                "title": title,
                "company": company,
                "known_people_at_company_count": known_people_at_company_count,
                "organization_enrichment": organization_enrichment,
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


def search_history_backed_people(
    database_url: str,
    *,
    actual_employee_count_min: int | None = None,
    actual_employee_count_max: int | None = None,
    consultant_count_min: int | None = None,
    consultant_count_max: int | None = None,
    limit: int = 25,
    as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH history_people AS (
                  SELECT
                    p.id,
                    p.display_name,
                    p.primary_email,
                    split_part(lower(p.primary_email), '@', 2) AS domain,
                    COALESCE(e.interaction_count, 0)::int AS interaction_count,
                    e.last_interaction_at,
                    COALESCE((e.metadata->>'calendar_interaction_count')::int, 0)::int
                      AS calendar_interaction_count
                  FROM relationship_substrate.person p
                  JOIN relationship_substrate.relationship_edge e
                    ON e.person_id = p.id
                  WHERE p.primary_email IS NOT NULL
                )
                SELECT
                  p.id,
                  p.display_name,
                  p.primary_email,
                  p.domain,
                  p.interaction_count,
                  p.last_interaction_at,
                  p.calendar_interaction_count,
                  o.name,
                  o.organization_enrichment
                FROM history_people p
                JOIN LATERAL (
                  SELECT
                    organization.name,
                    organization.metadata->'enrichment' AS organization_enrichment
                  FROM relationship_substrate.organization
                  WHERE organization.metadata ? 'enrichment'
                  AND (
                    lower(organization.name) = p.domain
                    OR lower(COALESCE(organization.domain, '')) = p.domain
                    OR (organization.metadata->'enrichment'->'aliases') ? p.domain
                  )
                  ORDER BY
                    CASE
                      WHEN lower(organization.name) = p.domain THEN 0
                      WHEN lower(COALESCE(organization.domain, '')) = p.domain THEN 1
                      ELSE 2
                    END,
                    organization.updated_at DESC
                  LIMIT 1
                ) o ON true
                ORDER BY p.interaction_count DESC,
                  p.last_interaction_at DESC NULLS LAST,
                  p.display_name
                """
            )
            rows = cur.fetchall()

    results: list[dict[str, Any]] = []
    seen_emails: set[str] = set()
    for row in rows:
        email = _clean_email(row[2])
        if not email or email in seen_emails:
            continue
        enrichment = row[8]
        if not _enrichment_matches_employee_range(
            enrichment,
            actual_employee_count_min=actual_employee_count_min,
            actual_employee_count_max=actual_employee_count_max,
        ):
            continue
        if not _enrichment_matches_consultant_count(
            enrichment,
            consultant_count_min=consultant_count_min,
            consultant_count_max=consultant_count_max,
        ):
            continue
        interaction_count = int(row[4] or 0)
        calendar_interaction_count = int(row[6] or 0)
        last_interaction_at = row[5].isoformat() if row[5] else None
        results.append(
            {
                "person_id": str(row[0]),
                "name": row[1],
                "email": email,
                "domain": row[3],
                "company": row[7],
                "organization_enrichment": enrichment,
                "relationship": {
                    "interaction_count": interaction_count,
                    "email_interaction_count": max(interaction_count - calendar_interaction_count, 0),
                    "calendar_interaction_count": calendar_interaction_count,
                    "last_interaction_at": last_interaction_at,
                    "freshness": relationship_freshness(last_interaction_at, as_of=as_of),
                },
                "match_reasons": [
                    "history_backed_domain",
                    f"actual_employee_count:{enrichment.get('employee_count_min')}-{enrichment.get('employee_count_max')}",
                    f"consultant_count_estimate:{enrichment.get('consultant_count_estimate')}",
                ],
            }
        )
        seen_emails.add(email)
        if len(results) >= limit:
            break
    return results
