from __future__ import annotations

from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from relationship_substrate.contracts import SourceEventIn


def upsert_source_event(database_url: str, event: SourceEventIn) -> UUID:
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO relationship_substrate.source_event (
                  source_name,
                  source_event_type,
                  source_event_key,
                  source_payload,
                  source_posture,
                  provenance_status,
                  trust_role
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_name, source_event_key)
                DO UPDATE SET
                  source_payload = EXCLUDED.source_payload,
                  source_posture = EXCLUDED.source_posture,
                  provenance_status = EXCLUDED.provenance_status,
                  trust_role = EXCLUDED.trust_role
                RETURNING id
                """,
                (
                    event.source_name,
                    event.source_event_type,
                    event.source_event_key,
                    Jsonb(event.source_payload),
                    event.source_posture.value,
                    event.provenance_status,
                    event.trust_role,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    if row is None:
        msg = "source_event upsert returned no id"
        raise RuntimeError(msg)
    return row[0]


def get_source_event(database_url: str, source_event_id: UUID) -> dict:
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, source_payload, source_posture, provenance_status
                FROM relationship_substrate.source_event
                WHERE id = %s
                """,
                (source_event_id,),
            )
            row = cur.fetchone()
    if row is None:
        raise ValueError(f"source event not found: {source_event_id}")
    return {
        "id": row[0],
        "source_payload": row[1],
        "source_posture": row[2],
        "provenance_status": row[3],
    }


def list_source_events(
    database_url: str,
    *,
    source_name: str,
    source_event_type: str | None = None,
) -> list[dict]:
    filters = ["source_name = %s"]
    params: list[object] = [source_name]
    if source_event_type is not None:
        filters.append("source_event_type = %s")
        params.append(source_event_type)
    where = " AND ".join(filters)
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, source_payload, source_posture, provenance_status
                FROM relationship_substrate.source_event
                WHERE {where}
                ORDER BY observed_at, source_event_key
                """,
                params,
            )
            rows = cur.fetchall()
    return [
        {
            "id": row[0],
            "source_payload": row[1],
            "source_posture": row[2],
            "provenance_status": row[3],
        }
        for row in rows
    ]


def operating_picture_rows(database_url: str, *, limit: int = 25) -> list[dict]:
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH identity_candidate_refs AS (
                  SELECT ic.candidate_id AS person_id, count(*) AS candidate_count
                  FROM relationship_substrate.identity_candidate ic
                  WHERE ic.status = 'candidate'
                  AND ic.candidate_type = 'person'
                  AND ic.candidate_id IS NOT NULL
                  GROUP BY ic.candidate_id
                  UNION ALL
                  SELECT (si.metadata->>'person_id')::uuid AS person_id, count(*) AS candidate_count
                  FROM relationship_substrate.identity_candidate ic
                  JOIN relationship_substrate.source_identity si
                    ON si.id = ic.source_identity_id
                  WHERE ic.status = 'candidate'
                  AND si.metadata ? 'person_id'
                  GROUP BY (si.metadata->>'person_id')::uuid
                ),
                identity_candidate_totals AS (
                  SELECT person_id, sum(candidate_count)::int AS candidate_count
                  FROM identity_candidate_refs
                  GROUP BY person_id
                )
                SELECT
                  p.id,
                  p.display_name,
                  p.primary_email,
                  COALESCE(e.interaction_count, 0) AS interaction_count,
                  e.last_interaction_at,
                  p.source_posture,
                  p.provenance_status,
                  p.metadata,
                  COALESCE(ict.candidate_count, 0) AS unresolved_identity_candidates
                FROM relationship_substrate.person p
                LEFT JOIN relationship_substrate.relationship_edge e
                  ON e.person_id = p.id
                LEFT JOIN identity_candidate_totals ict
                  ON ict.person_id = p.id
                ORDER BY COALESCE(e.interaction_count, 0) DESC, p.updated_at DESC, p.display_name
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
    return [
        {
            "person_id": str(row[0]),
            "display_name": row[1],
            "primary_email": row[2],
            "interaction_count": row[3],
            "last_interaction_at": row[4].isoformat() if row[4] else None,
            "source_posture": row[5],
            "provenance_status": row[6],
            "metadata": row[7],
            "unresolved_identity_candidates": row[8],
        }
        for row in rows
    ]


def identity_candidate_counts(database_url: str) -> dict[str, int]:
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT status, count(*)::int
                FROM relationship_substrate.identity_candidate
                GROUP BY status
                """
            )
            rows = cur.fetchall()
    counts = {row[0]: row[1] for row in rows}
    return {
        "open_candidates": counts.get("candidate", 0),
        "accepted_candidates": counts.get("accepted", 0),
        "rejected_candidates": counts.get("rejected", 0),
        "superseded_candidates": counts.get("superseded", 0),
    }


def substrate_counts(database_url: str) -> dict[str, int]:
    tables = [
        "source_event",
        "person",
        "contact_channel",
        "identity_candidate",
        "interaction",
        "relationship_edge",
    ]
    counts: dict[str, int] = {}
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            for table in tables:
                cur.execute(f"SELECT count(*) FROM relationship_substrate.{table}")
                counts[table] = cur.fetchone()[0]
    return counts
