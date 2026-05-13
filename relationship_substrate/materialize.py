from __future__ import annotations

from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from relationship_substrate.repositories import get_source_event, list_source_events


def _clean_email(value: object) -> str | None:
    if value is None:
        return None
    email = str(value).strip().lower()
    return email or None


def _display_name(payload: dict) -> str:
    full_name = str(payload.get("full_name") or "").strip()
    if full_name:
        return full_name
    first = str(payload.get("first_name") or "").strip()
    last = str(payload.get("last_name") or "").strip()
    name = " ".join(part for part in [first, last] if part)
    return name or payload.get("email") or "Unknown person"


def materialize_curated_contact(database_url: str, source_event_id: UUID) -> UUID:
    event = get_source_event(database_url, source_event_id)
    payload = event["source_payload"]
    email = _clean_email(payload.get("email"))
    if email is None:
        raise ValueError("curated contact requires an email for v1 materialization")

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO relationship_substrate.person (
                  display_name, primary_email, source_posture, provenance_status, metadata
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (primary_email)
                DO UPDATE SET display_name = EXCLUDED.display_name, updated_at = now()
                RETURNING id
                """,
                (
                    _display_name(payload),
                    email,
                    event["source_posture"],
                    event["provenance_status"],
                    Jsonb({"trust_role": "identity/context seed"}),
                ),
            )
            person_id = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO relationship_substrate.contact_channel (
                  person_id, channel_type, channel_value, source_posture, provenance_status
                )
                VALUES (%s, 'email', %s, %s, %s)
                ON CONFLICT (channel_type, channel_value)
                DO UPDATE SET person_id = EXCLUDED.person_id
                """,
                (person_id, email, event["source_posture"], event["provenance_status"]),
            )
        conn.commit()
    return person_id


def materialize_exact_emails(database_url: str, *, source_name: str = "next_up") -> dict[str, int | str]:
    events = list_source_events(
        database_url,
        source_name=source_name,
        source_event_type="curated_contact",
    )
    stats = {
        "source": source_name,
        "events_seen": len(events),
        "materialized": 0,
        "skipped_missing_email": 0,
    }
    for event in events:
        if _clean_email(event["source_payload"].get("email")) is None:
            stats["skipped_missing_email"] += 1
            continue
        materialize_curated_contact(database_url, event["id"])
        stats["materialized"] += 1
    return stats
