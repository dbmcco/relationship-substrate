from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from relationship_substrate.repositories import get_source_event, list_source_events


def _clean_email(value: object) -> str | None:
    if value is None:
        return None
    email = str(value).strip().lower()
    return email or None


def _email_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1]


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


def materialize_exact_emails(
    database_url: str,
    *,
    source_name: str = "next_up",
    skipped_domains: set[str] | None = None,
) -> dict[str, int | str]:
    events = list_source_events(
        database_url,
        source_name=source_name,
        source_event_type="curated_contact",
    )
    skipped_domains = skipped_domains or set()
    stats = {
        "source": source_name,
        "events_seen": len(events),
        "materialized": 0,
        "skipped_missing_email": 0,
        "skipped_domain": 0,
    }
    for event in events:
        email = _clean_email(event["source_payload"].get("email"))
        if email is None:
            stats["skipped_missing_email"] += 1
            continue
        if _email_domain(email) in skipped_domains:
            stats["skipped_domain"] += 1
            continue
        materialize_curated_contact(database_url, event["id"])
        stats["materialized"] += 1
    return stats


def _sender_display_name(email: str) -> str:
    return email.split("@", 1)[0].replace(".", " ").replace("_", " ").strip() or email


def _parse_calendar_time(value: object) -> datetime | None:
    if isinstance(value, dict):
        value = value.get("dateTime") or value.get("date")
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = (
        datetime.fromisoformat(text)
        if "T" in text
        else datetime.combine(date.fromisoformat(text), datetime.min.time())
    )
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _attendee_email(attendee: object) -> str | None:
    if not isinstance(attendee, dict):
        return None
    return _clean_email(attendee.get("email"))


def _attendee_name(attendee: dict, email: str) -> str:
    name = str(attendee.get("displayName") or attendee.get("display_name") or "").strip()
    return name or _sender_display_name(email)


def materialize_calendar_events(
    database_url: str,
    *,
    self_aliases: set[str],
    skipped_domains: set[str],
) -> dict[str, int | str]:
    events = list_source_events(
        database_url,
        source_name="calendar",
        source_event_type="calendar_event",
    )
    stats = {
        "source": "calendar",
        "events_seen": len(events),
        "materialized_events": 0,
        "attendees_materialized": 0,
        "skipped_self": 0,
        "skipped_domain": 0,
        "skipped_missing_email": 0,
        "skipped_existing": 0,
    }
    for event in events:
        payload = event["source_payload"]
        occurred_at = _parse_calendar_time(payload.get("start"))
        attendees = payload.get("attendees") if isinstance(payload.get("attendees"), list) else []
        materialized_attendees: list[str] = []
        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM relationship_substrate.interaction
                    WHERE source_event_id = %s
                    """,
                    (event["id"],),
                )
                if cur.fetchone() is not None:
                    stats["skipped_existing"] += 1
                    continue
                for attendee in attendees:
                    email = _attendee_email(attendee)
                    if email is None:
                        stats["skipped_missing_email"] += 1
                        continue
                    if email in self_aliases or (isinstance(attendee, dict) and attendee.get("self") is True):
                        stats["skipped_self"] += 1
                        continue
                    if _email_domain(email) in skipped_domains:
                        stats["skipped_domain"] += 1
                        continue
                    cur.execute(
                        """
                        INSERT INTO relationship_substrate.person (
                          display_name, primary_email, source_posture, provenance_status, metadata
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (primary_email)
                        DO UPDATE SET
                          display_name = COALESCE(NULLIF(EXCLUDED.display_name, ''), relationship_substrate.person.display_name),
                          source_posture = EXCLUDED.source_posture,
                          provenance_status = EXCLUDED.provenance_status,
                          metadata = relationship_substrate.person.metadata || EXCLUDED.metadata,
                          updated_at = now()
                        RETURNING id
                        """,
                        (
                            _attendee_name(attendee, email),
                            email,
                            event["source_posture"],
                            event["provenance_status"],
                            Jsonb({"trust_role": "calendar attendee evidence"}),
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
                        DO UPDATE SET
                          person_id = EXCLUDED.person_id,
                          source_posture = EXCLUDED.source_posture,
                          provenance_status = EXCLUDED.provenance_status
                        """,
                        (person_id, email, event["source_posture"], event["provenance_status"]),
                    )
                    cur.execute(
                        """
                        INSERT INTO relationship_substrate.relationship_edge (
                          person_id, first_interaction_at, last_interaction_at, interaction_count, metadata
                        )
                        VALUES (%s, %s, %s, 1, %s)
                        ON CONFLICT (person_id)
                        DO UPDATE SET
                          first_interaction_at = LEAST(
                            COALESCE(
                              relationship_substrate.relationship_edge.first_interaction_at,
                              EXCLUDED.first_interaction_at
                            ),
                            COALESCE(
                              EXCLUDED.first_interaction_at,
                              relationship_substrate.relationship_edge.first_interaction_at
                            )
                          ),
                          last_interaction_at = GREATEST(
                            COALESCE(
                              relationship_substrate.relationship_edge.last_interaction_at,
                              EXCLUDED.last_interaction_at
                            ),
                            COALESCE(
                              EXCLUDED.last_interaction_at,
                              relationship_substrate.relationship_edge.last_interaction_at
                            )
                          ),
                          interaction_count = relationship_substrate.relationship_edge.interaction_count + 1,
                          metadata = relationship_substrate.relationship_edge.metadata || jsonb_build_object(
                            'calendar_interaction_count',
                            COALESCE((relationship_substrate.relationship_edge.metadata->>'calendar_interaction_count')::int, 0) + 1,
                            'source',
                            'calendar_event'
                          )
                        """,
                        (
                            person_id,
                            occurred_at,
                            occurred_at,
                            Jsonb({"source": "calendar_event", "calendar_interaction_count": 1}),
                        ),
                    )
                    materialized_attendees.append(email)
                    stats["attendees_materialized"] += 1
                cur.execute(
                    """
                    INSERT INTO relationship_substrate.interaction (
                      source_event_id, interaction_type, occurred_at, subject, metadata
                    )
                    VALUES (%s, 'calendar_event', %s, %s, %s)
                    """,
                    (
                        event["id"],
                        occurred_at,
                        payload.get("summary"),
                        Jsonb(
                            {
                                "attendee_emails": materialized_attendees,
                                "aggregate": True,
                                "source": "calendar_export",
                            }
                        ),
                    ),
                )
                stats["materialized_events"] += 1
            conn.commit()
    return stats


def materialize_msgvault_sender(database_url: str, source_event_id: UUID) -> UUID:
    event = get_source_event(database_url, source_event_id)
    payload = event["source_payload"]
    email = _clean_email(payload.get("email"))
    if email is None:
        raise ValueError("msgvault sender profile requires an email")
    message_count = int(payload.get("message_count") or 0)

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO relationship_substrate.person (
                  display_name, primary_email, source_posture, provenance_status, metadata
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (primary_email)
                DO UPDATE SET
                  source_posture = EXCLUDED.source_posture,
                  provenance_status = EXCLUDED.provenance_status,
                  metadata = relationship_substrate.person.metadata || EXCLUDED.metadata,
                  updated_at = now()
                RETURNING id
                """,
                (
                    payload.get("display_name") or _sender_display_name(email),
                    email,
                    event["source_posture"],
                    event["provenance_status"],
                    Jsonb({"trust_role": "direct email aggregate"}),
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
                DO UPDATE SET
                  person_id = EXCLUDED.person_id,
                  source_posture = EXCLUDED.source_posture,
                  provenance_status = EXCLUDED.provenance_status
                """,
                (person_id, email, event["source_posture"], event["provenance_status"]),
            )
            cur.execute(
                """
                INSERT INTO relationship_substrate.interaction (
                  source_event_id, interaction_type, metadata
                )
                VALUES (%s, 'email_sender_profile', %s)
                ON CONFLICT (source_event_id)
                DO UPDATE SET metadata = EXCLUDED.metadata
                """,
                (
                    source_event_id,
                    Jsonb(
                        {
                            "aggregate": True,
                            "message_count": message_count,
                            "sender_email": email,
                        }
                    ),
                ),
            )
            cur.execute(
                """
                INSERT INTO relationship_substrate.relationship_edge (
                  person_id, interaction_count, metadata
                )
                VALUES (%s, %s, %s)
                ON CONFLICT (person_id)
                DO UPDATE SET
                  interaction_count = EXCLUDED.interaction_count,
                  metadata = relationship_substrate.relationship_edge.metadata || EXCLUDED.metadata
                """,
                (
                    person_id,
                    message_count,
                    Jsonb({"source": "msgvault_sender_profile"}),
                ),
            )
        conn.commit()
    return person_id


def materialize_msgvault_senders(database_url: str) -> dict[str, int | str]:
    events = list_source_events(
        database_url,
        source_name="msgvault",
        source_event_type="sender_profile",
    )
    stats = {
        "source": "msgvault",
        "events_seen": len(events),
        "materialized": 0,
        "skipped_missing_email": 0,
    }
    for event in events:
        if _clean_email(event["source_payload"].get("email")) is None:
            stats["skipped_missing_email"] += 1
            continue
        materialize_msgvault_sender(database_url, event["id"])
        stats["materialized"] += 1
    return stats
