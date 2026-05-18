from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Jsonb


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _row_to_note(row: tuple) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "person_id": str(row[1]),
        "person_name": row[2],
        "person_email": row[3],
        "note_kind": row[4],
        "applies_to": row[5],
        "note": row[6],
        "source": row[7],
        "metadata": row[8] or {},
        "created_at": row[9].isoformat() if row[9] else None,
    }


def _resolve_person(cur: psycopg.Cursor, person_ref: str) -> tuple:
    clean_ref = _clean_text(person_ref)
    if not clean_ref:
        raise ValueError("person_ref is required")
    lowered = clean_ref.lower()
    if "@" in lowered:
        cur.execute(
            """
            SELECT id, display_name, primary_email
            FROM relationship_substrate.person
            WHERE lower(primary_email) = lower(%s)
            """,
            (lowered,),
        )
    else:
        cur.execute(
            """
            SELECT id, display_name, primary_email
            FROM relationship_substrate.person
            WHERE lower(display_name) = lower(%s)
            ORDER BY updated_at DESC, id
            """,
            (clean_ref,),
        )
    rows = cur.fetchall()
    if not rows and "@" not in lowered:
        cur.execute(
            """
            SELECT id, display_name, primary_email
            FROM relationship_substrate.person
            WHERE display_name ILIKE %s
            ORDER BY updated_at DESC, id
            LIMIT 10
            """,
            (f"%{clean_ref}%",),
        )
        rows = cur.fetchall()
    if not rows:
        raise ValueError(f"person not found: {clean_ref}")
    if len(rows) > 1:
        candidates = [
            {"display_name": row[1], "primary_email": row[2]} for row in rows[:10]
        ]
        raise ValueError(f"person_ref is ambiguous: {candidates}")
    return rows[0]


def record_person_note(
    database_url: str,
    *,
    person_ref: str,
    note_kind: str,
    note: str,
    applies_to: str | None = None,
    source: str = "user_correction",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clean_kind = _clean_text(note_kind)
    clean_note = _clean_text(note)
    clean_source = _clean_text(source) or "user_correction"
    if not clean_kind:
        raise ValueError("note_kind is required")
    if not clean_note:
        raise ValueError("note is required")
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            person = _resolve_person(cur, person_ref)
            cur.execute(
                """
                INSERT INTO relationship_substrate.person_note (
                  person_id, note_kind, applies_to, note, source, metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, person_id, %s, %s, note_kind, applies_to, note, source, metadata, created_at
                """,
                (
                    person[0],
                    clean_kind,
                    _clean_text(applies_to) or None,
                    clean_note,
                    clean_source,
                    Jsonb(metadata or {}),
                    person[1],
                    person[2],
                ),
            )
            row = cur.fetchone()
        conn.commit()
    if row is None:
        raise RuntimeError("person_note insert returned no row")
    return _row_to_note(row)


def list_person_notes(
    database_url: str,
    *,
    person_ref: str | None = None,
    note_kind: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    filters: list[str] = []
    params: list[Any] = []
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            if person_ref:
                person = _resolve_person(cur, person_ref)
                filters.append("pn.person_id = %s")
                params.append(person[0])
            if note_kind:
                filters.append("pn.note_kind = %s")
                params.append(_clean_text(note_kind))
            where = f"WHERE {' AND '.join(filters)}" if filters else ""
            params.append(max(1, min(int(limit), 200)))
            cur.execute(
                f"""
                SELECT
                  pn.id,
                  pn.person_id,
                  p.display_name,
                  p.primary_email,
                  pn.note_kind,
                  pn.applies_to,
                  pn.note,
                  pn.source,
                  pn.metadata,
                  pn.created_at
                FROM relationship_substrate.person_note pn
                JOIN relationship_substrate.person p
                  ON p.id = pn.person_id
                {where}
                ORDER BY pn.created_at DESC, pn.id DESC
                LIMIT %s
                """,
                params,
            )
            rows = cur.fetchall()
    return [_row_to_note(row) for row in rows]
