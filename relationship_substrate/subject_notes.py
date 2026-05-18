from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Jsonb


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _clean_subject_type(subject_type: object) -> str:
    cleaned = _clean_text(subject_type).lower()
    if cleaned not in {"person", "organization"}:
        raise ValueError("subject_type must be person or organization")
    return cleaned


def _row_to_subject_note(row: tuple) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "subject_type": row[1],
        "subject_id": str(row[2]),
        "person_name": row[3],
        "person_email": row[4],
        "organization_name": row[5],
        "organization_domain": row[6],
        "note_kind": row[7],
        "applies_to": row[8],
        "note": row[9],
        "source": row[10],
        "source_ref": row[11],
        "evidence_refs": list(row[12] or []),
        "metadata": row[13] or {},
        "supersedes_id": str(row[14]) if row[14] else None,
        "created_at": row[15].isoformat() if row[15] else None,
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


def _resolve_organization(cur: psycopg.Cursor, organization_ref: str) -> tuple:
    clean_ref = _clean_text(organization_ref)
    if not clean_ref:
        raise ValueError("organization_ref is required")
    cur.execute(
        """
        SELECT id, name, domain
        FROM relationship_substrate.organization
        WHERE lower(domain) = lower(%s) OR lower(name) = lower(%s)
        ORDER BY updated_at DESC, id
        """,
        (clean_ref, clean_ref),
    )
    rows = cur.fetchall()
    if not rows:
        cur.execute(
            """
            SELECT id, name, domain
            FROM relationship_substrate.organization
            WHERE name ILIKE %s
            ORDER BY updated_at DESC, id
            LIMIT 10
            """,
            (f"%{clean_ref}%",),
        )
        rows = cur.fetchall()
    if not rows:
        raise ValueError(f"organization not found: {clean_ref}")
    if len(rows) > 1:
        candidates = [{"name": row[1], "domain": row[2]} for row in rows[:10]]
        raise ValueError(f"organization_ref is ambiguous: {candidates}")
    return rows[0]


def _resolve_subject(cur: psycopg.Cursor, subject_type: str, subject_ref: str) -> tuple:
    if subject_type == "person":
        row = _resolve_person(cur, subject_ref)
        return (row[0], row[1], row[2], None, None)
    row = _resolve_organization(cur, subject_ref)
    return (row[0], None, None, row[1], row[2])


def record_subject_note(
    database_url: str,
    *,
    subject_type: str,
    subject_ref: str,
    note_kind: str,
    note: str,
    applies_to: str | None = None,
    source: str = "user_correction",
    source_ref: str | None = None,
    evidence_refs: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    supersedes_id: str | None = None,
) -> dict[str, Any]:
    clean_subject_type = _clean_subject_type(subject_type)
    clean_kind = _clean_text(note_kind)
    clean_note = _clean_text(note)
    clean_source = _clean_text(source) or "user_correction"
    if not clean_kind:
        raise ValueError("note_kind is required")
    if not clean_note:
        raise ValueError("note is required")
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            subject = _resolve_subject(cur, clean_subject_type, subject_ref)
            cur.execute(
                """
                INSERT INTO relationship_substrate.subject_note (
                  subject_type,
                  subject_id,
                  note_kind,
                  applies_to,
                  note,
                  source,
                  source_ref,
                  evidence_refs,
                  metadata,
                  supersedes_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING
                  id,
                  subject_type,
                  subject_id,
                  %s,
                  %s,
                  %s,
                  %s,
                  note_kind,
                  applies_to,
                  note,
                  source,
                  source_ref,
                  evidence_refs,
                  metadata,
                  supersedes_id,
                  created_at
                """,
                (
                    clean_subject_type,
                    subject[0],
                    clean_kind,
                    _clean_text(applies_to) or None,
                    clean_note,
                    clean_source,
                    _clean_text(source_ref) or None,
                    evidence_refs or [],
                    Jsonb(metadata or {}),
                    _clean_text(supersedes_id) or None,
                    subject[1],
                    subject[2],
                    subject[3],
                    subject[4],
                ),
            )
            row = cur.fetchone()
        conn.commit()
    if row is None:
        raise RuntimeError("subject_note insert returned no row")
    return _row_to_subject_note(row)


def list_subject_notes(
    database_url: str,
    *,
    subject_type: str | None = None,
    subject_ref: str | None = None,
    note_kind: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    filters: list[str] = []
    params: list[Any] = []
    clean_subject_type = _clean_subject_type(subject_type) if subject_type else None
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            if clean_subject_type:
                filters.append("sn.subject_type = %s")
                params.append(clean_subject_type)
            if subject_ref:
                if not clean_subject_type:
                    raise ValueError("subject_type is required when subject_ref is provided")
                subject = _resolve_subject(cur, clean_subject_type, subject_ref)
                filters.append("sn.subject_id = %s")
                params.append(subject[0])
            if note_kind:
                filters.append("sn.note_kind = %s")
                params.append(_clean_text(note_kind))
            where = f"WHERE {' AND '.join(filters)}" if filters else ""
            params.append(max(1, min(int(limit), 200)))
            cur.execute(
                f"""
                SELECT
                  sn.id,
                  sn.subject_type,
                  sn.subject_id,
                  p.display_name AS person_name,
                  p.primary_email AS person_email,
                  o.name AS organization_name,
                  o.domain AS organization_domain,
                  sn.note_kind,
                  sn.applies_to,
                  sn.note,
                  sn.source,
                  sn.source_ref,
                  sn.evidence_refs,
                  sn.metadata,
                  sn.supersedes_id,
                  sn.created_at
                FROM relationship_substrate.subject_note sn
                LEFT JOIN relationship_substrate.person p
                  ON sn.subject_type = 'person' AND p.id = sn.subject_id
                LEFT JOIN relationship_substrate.organization o
                  ON sn.subject_type = 'organization' AND o.id = sn.subject_id
                {where}
                ORDER BY sn.created_at DESC, sn.id DESC
                LIMIT %s
                """,
                params,
            )
            rows = cur.fetchall()
    return [_row_to_subject_note(row) for row in rows]


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
    note_row = record_subject_note(
        database_url,
        subject_type="person",
        subject_ref=person_ref,
        note_kind=note_kind,
        applies_to=applies_to,
        note=note,
        source=source,
        metadata=metadata,
    )
    return {
        "id": note_row["id"],
        "person_id": note_row["subject_id"],
        "person_name": note_row["person_name"],
        "person_email": note_row["person_email"],
        "note_kind": note_row["note_kind"],
        "applies_to": note_row["applies_to"],
        "note": note_row["note"],
        "source": note_row["source"],
        "metadata": note_row["metadata"],
        "created_at": note_row["created_at"],
    }


def list_person_notes(
    database_url: str,
    *,
    person_ref: str | None = None,
    note_kind: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    subject_notes = list_subject_notes(
        database_url,
        subject_type="person" if person_ref else None,
        subject_ref=person_ref,
        note_kind=note_kind,
        limit=limit,
    )
    return [
        {
            "id": note_row["id"],
            "person_id": note_row["subject_id"],
            "person_name": note_row["person_name"],
            "person_email": note_row["person_email"],
            "note_kind": note_row["note_kind"],
            "applies_to": note_row["applies_to"],
            "note": note_row["note"],
            "source": note_row["source"],
            "metadata": note_row["metadata"],
            "created_at": note_row["created_at"],
        }
        for note_row in subject_notes
    ]
