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


def test_export_operating_picture_cli_outputs_json(capsys, monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["relationship-substrate", "export-operating-picture"],
    )

    assert main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["id"] == "relationship_operating_picture.braydon.v1"
    assert payload["relationships"] == []


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
