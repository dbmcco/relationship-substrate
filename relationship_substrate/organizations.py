from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Jsonb


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def upsert_organization_enrichment(
    database_url: str,
    *,
    company_name: str,
    company_type: str | None = None,
    employee_count_min: int | None = None,
    employee_count_max: int | None = None,
    employee_count_label: str | None = None,
    consultant_count_estimate: int | None = None,
    source_name: str,
    source_url: str | None = None,
    provenance_status: str,
) -> dict[str, Any]:
    name = _clean_text(company_name)
    if not name:
        raise ValueError("company_name is required")
    enrichment = {
        "company_type": company_type,
        "employee_count_label": employee_count_label,
        "employee_count_min": employee_count_min,
        "employee_count_max": employee_count_max,
        "consultant_count_estimate": consultant_count_estimate,
        "source_name": source_name,
        "source_url": source_url,
        "provenance_status": provenance_status,
    }
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id
                FROM relationship_substrate.organization
                WHERE lower(name) = lower(%s)
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (name,),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    """
                    INSERT INTO relationship_substrate.organization (
                      name, source_posture, provenance_status, metadata
                    )
                    VALUES (%s, 'enrichment', %s, %s)
                    RETURNING id
                    """,
                    (name, provenance_status, Jsonb({"enrichment": enrichment})),
                )
                organization_id = cur.fetchone()[0]
            else:
                organization_id = row[0]
                cur.execute(
                    """
                    UPDATE relationship_substrate.organization
                    SET
                      source_posture = 'enrichment',
                      provenance_status = %s,
                      metadata = metadata || %s,
                      updated_at = now()
                    WHERE id = %s
                    """,
                    (provenance_status, Jsonb({"enrichment": enrichment}), organization_id),
                )
        conn.commit()
    return {"organization_id": str(organization_id), "company_name": name, "enrichment": enrichment}


def organization_enrichment_by_name(database_url: str) -> dict[str, dict[str, Any]]:
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (lower(name))
                  lower(name),
                  metadata->'enrichment'
                FROM relationship_substrate.organization
                WHERE metadata ? 'enrichment'
                ORDER BY lower(name), updated_at DESC
                """
            )
            rows = cur.fetchall()
    return {row[0]: row[1] for row in rows if row[1] is not None}


def organization_enrichment_worklist(database_url: str, *, limit: int = 50) -> list[dict[str, Any]]:
    enrichments = organization_enrichment_by_name(database_url)
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH curated AS (
                  SELECT
                    nullif(source_payload->>'company', '') AS company_name,
                    nullif(source_payload->>'title', '') AS title
                  FROM relationship_substrate.source_event
                  WHERE source_name = 'next_up'
                  AND source_event_type = 'curated_contact'
                  AND nullif(source_payload->>'company', '') IS NOT NULL
                ),
                ranked_titles AS (
                  SELECT
                    company_name,
                    title,
                    row_number() OVER (
                      PARTITION BY company_name
                      ORDER BY title
                    ) AS title_rank
                  FROM (
                    SELECT DISTINCT company_name, title
                    FROM curated
                    WHERE title IS NOT NULL
                  ) titles
                ),
                company_counts AS (
                  SELECT company_name, count(*)::int AS known_people_at_company_count
                  FROM curated
                  GROUP BY company_name
                ),
                title_samples AS (
                  SELECT
                    company_name,
                    array_agg(title ORDER BY title) FILTER (WHERE title_rank <= 5) AS sample_titles
                  FROM ranked_titles
                  GROUP BY company_name
                )
                SELECT
                  cc.company_name,
                  cc.known_people_at_company_count,
                  COALESCE(ts.sample_titles, ARRAY[]::text[]) AS sample_titles
                FROM company_counts cc
                LEFT JOIN title_samples ts
                  ON ts.company_name = cc.company_name
                ORDER BY
                  CASE WHEN lower(cc.company_name) = ANY(%s) THEN 1 ELSE 0 END,
                  cc.known_people_at_company_count DESC,
                  cc.company_name
                LIMIT %s
                """,
                (list(enrichments.keys()), limit),
            )
            rows = cur.fetchall()
    return [
        {
            "company_name": row[0],
            "known_people_at_company_count": row[1],
            "has_enrichment": row[0].lower() in enrichments,
            "organization_enrichment": enrichments.get(row[0].lower()),
            "sample_titles": list(dict.fromkeys(row[2] or [])),
            "research_prompt": (
                "Find actual organization size, company type, whether this is a medcoms/medical "
                f"communications consultancy, and source URLs for {row[0]}."
            ),
        }
        for row in rows
    ]


def import_organization_enrichments(
    database_url: str,
    records: list[dict[str, Any]],
) -> dict[str, int | str]:
    report: dict[str, int | str] = {
        "source": "organization_enrichment_import",
        "seen": len(records),
        "imported": 0,
        "skipped": 0,
    }
    for record in records:
        company_name = _clean_text(record.get("company_name") or record.get("company"))
        source_name = _clean_text(record.get("source_name"))
        provenance_status = _clean_text(record.get("provenance_status")) or "external_research"
        if not company_name or not source_name:
            report["skipped"] += 1
            continue
        upsert_organization_enrichment(
            database_url,
            company_name=company_name,
            company_type=record.get("company_type"),
            employee_count_min=record.get("employee_count_min"),
            employee_count_max=record.get("employee_count_max"),
            employee_count_label=record.get("employee_count_label"),
            consultant_count_estimate=record.get("consultant_count_estimate"),
            source_name=source_name,
            source_url=record.get("source_url"),
            provenance_status=provenance_status,
        )
        report["imported"] += 1
    return report
