from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


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
                "relationship_state": "uninterpreted_interaction_evidence",
                "interpretation": (
                    "Mechanical interaction evidence is present. "
                    "Relationship health is not interpreted by this read model."
                ),
                "evidence_refs": [f"person:{row['person_id']}"],
                "metadata": {
                    "primary_email": row.get("primary_email"),
                    "interaction_count": row.get("interaction_count"),
                    "last_interaction_at": row.get("last_interaction_at"),
                    "source_posture": row.get("source_posture"),
                    "provenance_status": row.get("provenance_status"),
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
