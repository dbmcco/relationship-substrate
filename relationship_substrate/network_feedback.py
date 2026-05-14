from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from relationship_substrate.network_packets import get_network_packet


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _row_to_feedback(row: tuple) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "packet_id": str(row[1]),
        "person_email": row[2],
        "feedback_kind": row[3],
        "feedback": row[4] or {},
        "created_at": row[5].isoformat() if row[5] else None,
    }


def _packet_people(packet: dict[str, Any]) -> set[str]:
    summary = packet.get("packet_summary") or {}
    return {
        _clean_text(person.get("email")).lower()
        for person in summary.get("people", [])
        if _clean_text(person.get("email"))
    }


def record_network_feedback(
    database_url: str,
    *,
    packet_id: str,
    feedback_kind: str,
    feedback: dict[str, Any],
    person_email: str | None = None,
) -> dict[str, Any]:
    clean_kind = _clean_text(feedback_kind)
    if not clean_kind:
        raise ValueError("feedback_kind is required")
    if not isinstance(feedback, dict) or not feedback:
        raise ValueError("feedback must be a non-empty object")
    clean_person_email = _clean_text(person_email).lower() if person_email else None
    packet = get_network_packet(database_url, packet_id=packet_id)
    if clean_person_email and clean_person_email not in _packet_people(packet):
        raise ValueError("person_email is not present in the network packet")

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO relationship_substrate.network_feedback (
                  packet_id, person_email, feedback_kind, feedback
                )
                VALUES (%s, %s, %s, %s)
                RETURNING id, packet_id, person_email, feedback_kind, feedback, created_at
                """,
                (UUID(packet_id), clean_person_email, clean_kind, Jsonb(feedback)),
            )
            row = cur.fetchone()
        conn.commit()
    if row is None:
        raise RuntimeError("network_feedback insert returned no row")
    return _row_to_feedback(row)


def list_network_feedback(
    database_url: str,
    *,
    packet_id: str | None = None,
    person_email: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    filters: list[str] = []
    params: list[Any] = []
    if packet_id is not None:
        filters.append("packet_id = %s")
        params.append(UUID(packet_id))
    if person_email is not None:
        filters.append("lower(person_email) = lower(%s)")
        params.append(person_email)
    where = f"WHERE {' AND '.join(filters)}" if filters else ""
    params.append(limit)
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, packet_id, person_email, feedback_kind, feedback, created_at
                FROM relationship_substrate.network_feedback
                {where}
                ORDER BY created_at DESC
                LIMIT %s
                """,
                params,
            )
            rows = cur.fetchall()
    return [_row_to_feedback(row) for row in rows]
