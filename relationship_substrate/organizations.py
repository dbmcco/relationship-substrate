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
