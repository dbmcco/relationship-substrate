import json
import sys

from relationship_substrate.cli import main
from relationship_substrate.read_models import build_relationship_operating_picture


def test_operating_picture_shape_from_rows():
    rows = [
        {
            "person_id": "person-1",
            "display_name": "Jane Doe",
            "primary_email": "jane@example.com",
            "interaction_count": 4,
            "last_interaction_at": "2026-05-01T12:00:00Z",
            "source_posture": "direct_interaction",
            "provenance_status": "msgvault",
        }
    ]

    picture = build_relationship_operating_picture(rows)

    assert picture["state_system_role"] == "state_system_interpretation"
    assert picture["relationships"][0]["name"] == "Jane Doe"
    assert picture["relationships"][0]["evidence_refs"] == ["person:person-1"]


def test_export_operating_picture_cli_uses_db_backed_rows_by_default(capsys, monkeypatch):
    called: dict[str, object] = {}

    def _fake_operating_picture_from_db(database_url: str, *, limit: int) -> dict[str, object]:
        called["database_url"] = database_url
        called["limit"] = limit
        return {
            "id": "relationship_operating_picture.user.v1",
            "relationships": [
                {
                    "id": "relationship.person-1",
                    "name": "Jane Doe",
                    "metadata": {
                        "provenance_status": "msgvault_message",
                        "unresolved_identity_candidates": 2,
                    },
                }
            ],
        }

    monkeypatch.setattr("relationship_substrate.cli.operating_picture_from_db", _fake_operating_picture_from_db)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "relationship-substrate",
            "--database-url",
            "postgresql://localhost:5432/relationship_substrate_test",
            "export-operating-picture",
            "--limit",
            "7",
        ],
    )

    assert main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["id"] == "relationship_operating_picture.user.v1"
    assert payload["relationships"][0]["metadata"]["provenance_status"] == "msgvault_message"
    assert payload["relationships"][0]["metadata"]["unresolved_identity_candidates"] == 2
    assert called == {
        "database_url": "postgresql://localhost:5432/relationship_substrate_test",
        "limit": 7,
    }


def test_operating_picture_distinguishes_curated_rows_without_interactions():
    picture = build_relationship_operating_picture(
        [
            {
                "person_id": "person-1",
                "display_name": "Jane Doe",
                "primary_email": "jane@example.com",
                "interaction_count": 0,
                "last_interaction_at": None,
                "source_posture": "curated_export",
                "provenance_status": "unknown_upstream",
            }
        ]
    )

    relationship = picture["relationships"][0]

    assert relationship["relationship_state"] == "uninterpreted_identity_seed"
    assert "No direct interaction evidence" in relationship["interpretation"]
