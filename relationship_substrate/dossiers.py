from __future__ import annotations

from typing import Any

import psycopg

from relationship_substrate.freshness import relationship_freshness


def _person(row: tuple) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "display_name": row[1],
        "primary_email": row[2],
        "source_posture": row[3],
        "provenance_status": row[4],
        "metadata": row[5],
    }


def _relationship_edge(row: tuple | None) -> dict[str, Any]:
    if row is None:
        return {
            "interaction_count": 0,
            "first_interaction_at": None,
            "last_interaction_at": None,
            "calendar_interaction_count": 0,
            "freshness": relationship_freshness(None),
            "metadata": {},
        }
    metadata = row[3] or {}
    last_interaction_at = row[2].isoformat() if row[2] else None
    return {
        "interaction_count": row[0],
        "first_interaction_at": row[1].isoformat() if row[1] else None,
        "last_interaction_at": last_interaction_at,
        "calendar_interaction_count": int(metadata.get("calendar_interaction_count") or 0),
        "freshness": relationship_freshness(last_interaction_at),
        "metadata": metadata,
    }


def _contact_channel(row: tuple) -> dict[str, Any]:
    return {
        "channel_type": row[0],
        "channel_value": row[1],
        "source_posture": row[2],
        "provenance_status": row[3],
    }


def _interaction(row: tuple) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "source_event_id": str(row[1]),
        "interaction_type": row[2],
        "occurred_at": row[3].isoformat() if row[3] else None,
        "subject": row[4],
        "metadata": row[5],
    }


def _source_event(row: tuple) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "source_name": row[1],
        "source_event_type": row[2],
        "source_event_key": row[3],
        "source_payload": row[4],
        "source_posture": row[5],
        "provenance_status": row[6],
        "trust_role": row[7],
    }


def _evidence_ref(row: tuple) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "source_event_id": str(row[1]),
        "ref_type": row[2],
        "ref_value": row[3],
        "metadata": row[4],
    }


def _identity_candidate(row: tuple) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "status": row[1],
        "reason": row[2],
        "evidence": row[3],
        "source_identity": {
            "id": str(row[4]),
            "identity_type": row[5],
            "identity_value": row[6],
            "display_name": row[7],
        },
        "candidate": {
            "type": row[8],
            "id": str(row[9]) if row[9] else None,
            "display_name": row[10],
            "primary_email": row[11],
        },
    }


def get_person_dossier(database_url: str, *, email: str) -> dict[str, Any]:
    normalized_email = email.strip().lower()
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, display_name, primary_email, source_posture, provenance_status, metadata
                FROM relationship_substrate.person
                WHERE primary_email = %s
                """,
                (normalized_email,),
            )
            person_row = cur.fetchone()
            if person_row is None:
                raise ValueError(f"person not found for email: {normalized_email}")
            person_id = person_row[0]

            cur.execute(
                """
                SELECT channel_type, channel_value, source_posture, provenance_status
                FROM relationship_substrate.contact_channel
                WHERE person_id = %s
                ORDER BY channel_type, channel_value
                """,
                (person_id,),
            )
            contact_rows = cur.fetchall()

            cur.execute(
                """
                SELECT interaction_count, first_interaction_at, last_interaction_at, metadata
                FROM relationship_substrate.relationship_edge
                WHERE person_id = %s
                """,
                (person_id,),
            )
            edge_row = cur.fetchone()

            cur.execute(
                """
                SELECT id, source_event_id, interaction_type, occurred_at, subject, metadata
                FROM relationship_substrate.interaction
                WHERE metadata->>'sender_email' = %s
                OR metadata->'attendee_emails' ? %s
                ORDER BY occurred_at DESC NULLS LAST, id
                """,
                (normalized_email, normalized_email),
            )
            interaction_rows = cur.fetchall()
            source_event_ids = [row[1] for row in interaction_rows]

            source_event_rows = []
            evidence_ref_rows = []
            if source_event_ids:
                cur.execute(
                    """
                    SELECT
                      id,
                      source_name,
                      source_event_type,
                      source_event_key,
                      source_payload,
                      source_posture,
                      provenance_status,
                      trust_role
                    FROM relationship_substrate.source_event
                    WHERE id = ANY(%s)
                    ORDER BY observed_at DESC, source_event_key
                    """,
                    (source_event_ids,),
                )
                source_event_rows = cur.fetchall()
                cur.execute(
                    """
                    SELECT id, source_event_id, ref_type, ref_value, metadata
                    FROM relationship_substrate.evidence_ref
                    WHERE source_event_id = ANY(%s)
                    ORDER BY ref_type, ref_value
                    """,
                    (source_event_ids,),
                )
                evidence_ref_rows = cur.fetchall()

            cur.execute(
                """
                SELECT
                  ic.id,
                  ic.status,
                  ic.reason,
                  ic.evidence,
                  si.id,
                  si.identity_type,
                  si.identity_value,
                  si.display_name,
                  ic.candidate_type,
                  ic.candidate_id,
                  p.display_name,
                  p.primary_email
                FROM relationship_substrate.identity_candidate ic
                JOIN relationship_substrate.source_identity si
                  ON si.id = ic.source_identity_id
                LEFT JOIN relationship_substrate.person p
                  ON p.id = ic.candidate_id
                WHERE ic.candidate_id = %s
                OR si.metadata->>'person_id' = %s
                ORDER BY ic.status, ic.created_at DESC
                """,
                (person_id, str(person_id)),
            )
            identity_candidate_rows = cur.fetchall()

    return {
        "person": _person(person_row),
        "contact_channels": [_contact_channel(row) for row in contact_rows],
        "relationship_edge": _relationship_edge(edge_row),
        "interactions": [_interaction(row) for row in interaction_rows],
        "source_events": [_source_event(row) for row in source_event_rows],
        "evidence_refs": [_evidence_ref(row) for row in evidence_ref_rows],
        "identity_candidates": [_identity_candidate(row) for row in identity_candidate_rows],
    }
