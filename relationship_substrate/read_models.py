from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from relationship_substrate.freshness import relationship_freshness


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


def _relationship_payload(row: dict[str, Any], *, as_of: datetime) -> dict[str, Any]:
    freshness = relationship_freshness(row.get("last_interaction_at"), as_of=as_of)
    return {
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
            "freshness_state": freshness["state"],
            "days_since_last_interaction": freshness["days_since_last_interaction"],
            "freshness_basis": freshness["basis"],
        },
    }


def build_relationship_operating_picture(
    rows: list[dict[str, Any]],
    *,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    generated_at = as_of or datetime.now(UTC)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=UTC)
    now = generated_at.isoformat()
    return {
        "id": "relationship_operating_picture.braydon.v1",
        "subject_ref": "person.braydon",
        "generated_at": now,
        "system_of_record_ref": "relationship_substrate",
        "state_system_role": "state_system_interpretation",
        "relationships": [
            _relationship_payload(row, as_of=generated_at)
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
