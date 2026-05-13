from __future__ import annotations

from datetime import UTC, datetime

from relationship_substrate.freshness import relationship_freshness
from relationship_substrate.read_models import build_relationship_operating_picture


AS_OF = datetime(2026, 5, 13, tzinfo=UTC)


def test_relationship_freshness_buckets_are_mechanical():
    assert relationship_freshness(None, as_of=AS_OF) == {
        "state": "unknown",
        "days_since_last_interaction": None,
        "basis": "no_materialized_interaction",
    }
    assert relationship_freshness("2026-05-01T12:00:00+00:00", as_of=AS_OF)["state"] == "recent"
    assert relationship_freshness("2026-03-01T12:00:00+00:00", as_of=AS_OF)["state"] == "active"
    assert relationship_freshness("2025-12-01T12:00:00+00:00", as_of=AS_OF)["state"] == "stale"
    assert relationship_freshness("2024-01-01T12:00:00+00:00", as_of=AS_OF)["state"] == "dormant"


def test_operating_picture_includes_mechanical_freshness_metadata():
    picture = build_relationship_operating_picture(
        [
            {
                "person_id": "person-1",
                "display_name": "Jane Doe",
                "primary_email": "jane@example.com",
                "interaction_count": 1,
                "last_interaction_at": "2026-05-01T12:00:00+00:00",
                "source_posture": "direct_interaction",
                "provenance_status": "calendar_export",
            }
        ],
        as_of=AS_OF,
    )

    metadata = picture["relationships"][0]["metadata"]

    assert metadata["freshness_state"] == "recent"
    assert metadata["days_since_last_interaction"] == 12
    assert metadata["freshness_basis"] == "last_materialized_interaction_at"
