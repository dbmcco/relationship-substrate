from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def _relationship_state(row: dict[str, Any]) -> str:
    if int(row.get("interaction_count") or 0) > 0:
        return "uninterpreted_interaction_evidence"
    return "uninterpreted_identity_seed"


def _interpretation(row: dict[str, Any]) -> str:
    if int(row.get("interaction_count") or 0) > 0:
        return (
            "Mechanical interaction evidence is present. "
            "Relationship health is not interpreted by this read model."
        )
    return (
        "No direct interaction evidence has been materialized for this row. "
        "This is an identity/context seed, not a relationship-health claim."
    )


def build_relationship_operating_picture(rows: list[dict[str, Any]]) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    return {
        "id": "relationship_operating_picture.braydon.v1",
        "subject_ref": "person.braydon",
        "generated_at": now,
        "system_of_record_ref": "relationship_substrate",
        "state_system_role": "state_system_interpretation",
        "relationships": [
            {
                "id": f"relationship.{row['person_id']}",
                "name": row["display_name"],
                "relationship_state": _relationship_state(row),
                "interpretation": _interpretation(row),
                "evidence_refs": [f"person:{row['person_id']}"],
                "metadata": {
                    "primary_email": row.get("primary_email"),
                    "interaction_count": row.get("interaction_count"),
                    "last_interaction_at": row.get("last_interaction_at"),
                    "source_posture": row.get("source_posture"),
                    "provenance_status": row.get("provenance_status"),
                    "unresolved_identity_candidates": row.get("unresolved_identity_candidates", 0),
                    "calendar_interaction_count": row.get("calendar_interaction_count", 0),
                },
            }
            for row in rows
        ],
        "opportunities": [],
        "open_loops": [],
        "recent_changes": [],
        "evidence_refs": [f"person:{row['person_id']}" for row in rows],
        "freshness": {
            "as_of": now,
            "stale_after": now,
            "watermark_refs": [],
        },
    }
