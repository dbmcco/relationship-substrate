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
