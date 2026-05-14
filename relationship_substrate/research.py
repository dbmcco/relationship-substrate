from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _normalize_sources(*, snapshot_id: str | None, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, source in enumerate(sources, start=1):
        source_id = _clean_text(source.get("id"))
        if not source_id and snapshot_id:
            source_id = f"{snapshot_id}:source:{index}"
        elif not source_id:
            source_id = f"source:{index}"
        normalized.append({**source, "id": source_id})
    return normalized


def _row_to_snapshot(row: tuple) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "subject_type": row[1],
        "subject": row[2],
        "retrieved_at": row[3].isoformat() if row[3] else None,
        "summary": row[4],
        "confidence": row[5],
        "sources": row[6] or [],
        "metadata": row[7] or {},
        "created_at": row[8].isoformat() if row[8] else None,
    }


def upsert_research_snapshot(
    database_url: str,
    *,
    subject_type: str,
    subject: str,
    summary: str,
    confidence: str,
    sources: list[dict[str, Any]],
    retrieved_at: datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    clean_subject_type = _clean_text(subject_type)
    clean_subject = _clean_text(subject)
    clean_summary = _clean_text(summary)
    clean_confidence = _clean_text(confidence)
    if not clean_subject_type:
        raise ValueError("subject_type is required")
    if not clean_subject:
        raise ValueError("subject is required")
    if not clean_summary:
        raise ValueError("summary is required")
    if not clean_confidence:
        raise ValueError("confidence is required")
    retrieved_at = retrieved_at or datetime.now(tz=UTC)
    metadata = metadata or {}
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO relationship_substrate.research_snapshot (
                  subject_type, subject, retrieved_at, summary, confidence, sources, metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    clean_subject_type,
                    clean_subject,
                    retrieved_at,
                    clean_summary,
                    clean_confidence,
                    Jsonb(_normalize_sources(snapshot_id=None, sources=sources)),
                    Jsonb(metadata),
                ),
            )
            snapshot_id = str(cur.fetchone()[0])
            normalized_sources = _normalize_sources(snapshot_id=snapshot_id, sources=sources)
            cur.execute(
                """
                UPDATE relationship_substrate.research_snapshot
                SET sources = %s
                WHERE id = %s
                RETURNING
                  id, subject_type, subject, retrieved_at, summary, confidence,
                  sources, metadata, created_at
                """,
                (Jsonb(normalized_sources), snapshot_id),
            )
            row = cur.fetchone()
        conn.commit()
    if row is None:
        raise RuntimeError("research_snapshot insert returned no row")
    return _row_to_snapshot(row)


def list_research_snapshots(
    database_url: str,
    *,
    subject: str,
    subject_type: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    filters = ["lower(subject) = lower(%s)"]
    params: list[Any] = [subject]
    if subject_type is not None:
        filters.append("subject_type = %s")
        params.append(subject_type)
    params.append(limit)
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                  id, subject_type, subject, retrieved_at, summary, confidence,
                  sources, metadata, created_at
                FROM relationship_substrate.research_snapshot
                WHERE {" AND ".join(filters)}
                ORDER BY retrieved_at DESC, created_at DESC
                LIMIT %s
                """,
                params,
            )
            rows = cur.fetchall()
    return [_row_to_snapshot(row) for row in rows]


def research_context_from_snapshots(
    database_url: str,
    *,
    subject: str,
    subject_type: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    snapshots = list_research_snapshots(
        database_url,
        subject=subject,
        subject_type=subject_type,
        limit=limit,
    )
    sources: list[dict[str, Any]] = []
    for snapshot in snapshots:
        for source in snapshot.get("sources", []):
            sources.append(
                {
                    **source,
                    "snapshot_id": snapshot["id"],
                    "snapshot_subject": snapshot["subject"],
                    "snapshot_retrieved_at": snapshot["retrieved_at"],
                }
            )
    return {
        "snapshots": snapshots,
        "sources": sources,
    }
