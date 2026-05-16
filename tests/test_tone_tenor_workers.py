from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import psycopg

from relationship_substrate.contracts import SourceEventIn, SourcePosture
from relationship_substrate.db import run_migrations
from relationship_substrate.materialize import materialize_msgvault_correspondence
from relationship_substrate.repositories import upsert_evidence_ref, upsert_source_event
from relationship_substrate.tone_tenor_workers import (
    missing_tone_tenor_emails,
    parse_tone_tenor_proposal,
    run_relationship_tone_tenor_analysis,
    validate_no_raw_private_leakage,
)


def _insert_correspondence_evidence(
    database_url: str,
    *,
    email: str,
    message_id: str = "1",
    snippet: str = "Thanks for the thoughtful follow-up; happy to keep this moving.",
) -> str:
    event = SourceEventIn(
        source_name="msgvault",
        source_event_type="correspondence_message",
        source_event_key=f"msgvault:correspondence:{email}:{message_id}",
        source_payload={
            "id": message_id,
            "relationship_email": email,
            "relationship_direction": "from_contact",
            "from_email": email,
            "from_name": "Tone Worker Person",
            "sent_at": "2026-05-01T12:00:00Z",
            "subject": "Follow-up",
            "snippet": snippet,
        },
        source_posture=SourcePosture.DIRECT_INTERACTION,
        provenance_status="msgvault_message",
        trust_role="direct email correspondence evidence",
    )
    source_event_id = upsert_source_event(database_url, event)
    evidence_ref_id = upsert_evidence_ref(
        database_url,
        source_event_id=source_event_id,
        ref_type="msgvault_message",
        ref_value=f"{email}:{message_id}",
        metadata={"relationship_email": email, "msgvault_message_id": message_id},
    )
    return str(evidence_ref_id)


def test_missing_tone_tenor_emails_returns_people_with_interactions(database_url):
    run_migrations(database_url)
    email = f"missing-tone-{uuid4().hex}@example.com"
    _insert_correspondence_evidence(database_url, email=email)
    materialize_msgvault_correspondence(database_url)

    emails = missing_tone_tenor_emails(database_url, limit=100000)

    assert email in emails


def test_parse_tone_tenor_proposal_extracts_fenced_json():
    proposal = parse_tone_tenor_proposal(
        """
        ```json
        {
          "summary": "Warm, direct, professionally constructive.",
          "rationale": "The supplied evidence shows prompt, collaborative language.",
          "evidence_refs": [{"id": "evidence-1"}]
        }
        ```
        """
    )

    assert proposal == {
        "state_kind": "relationship_tone_tenor",
        "summary": "Warm, direct, professionally constructive.",
        "rationale": "The supplied evidence shows prompt, collaborative language.",
        "evidence_refs": [{"id": "evidence-1"}],
        "supersedes_id": None,
    }


def test_parse_tone_tenor_proposal_normalizes_string_evidence_ids():
    proposal = parse_tone_tenor_proposal(
        json.dumps(
            {
                "summary": "Warm and direct.",
                "rationale": "Grounded in supplied evidence.",
                "evidence_refs": ["evidence-1"],
            }
        )
    )

    assert proposal["evidence_refs"] == [{"id": "evidence-1"}]


def test_run_relationship_tone_tenor_analysis_persists_valid_model_proposals(database_url, tmp_path):
    run_migrations(database_url)
    email = f"tone-worker-{uuid4().hex}@example.com"
    evidence_ref_id = _insert_correspondence_evidence(database_url, email=email)
    materialize_msgvault_correspondence(database_url)
    calls: list[dict] = []

    def fake_model(packet: dict) -> str:
        calls.append(packet)
        return json.dumps(
            {
                "summary": "Warm, responsive, and professionally direct.",
                "rationale": "The model cites the supplied follow-up evidence.",
                "evidence_refs": [{"id": evidence_ref_id}],
            }
        )

    report = run_relationship_tone_tenor_analysis(
        database_url,
        output_dir=tmp_path / "tone",
        limit=100000,
        apply=True,
        generate_proposal=fake_model,
    )

    assert report["applied"] >= 1
    assert any(call["people"][0]["email"] == email for call in calls)
    assert Path(report["artifact"]).exists()
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT summary, rationale, evidence_refs
                FROM relationship_substrate.relationship_state rs
                JOIN relationship_substrate.person p ON p.id = rs.person_id
                WHERE p.primary_email = %s
                AND rs.state_kind = 'relationship_tone_tenor'
                """,
                (email,),
            )
            row = cur.fetchone()
            assert row[0] == "Warm, responsive, and professionally direct."
            assert "supplied follow-up evidence" in row[1]
            assert row[2] == [{"id": evidence_ref_id}]


def test_validate_no_raw_private_leakage_rejects_exact_snippets():
    snippet = "This is a private raw sentence that must not be stored in the relationship summary."
    proposal = {
        "summary": snippet,
        "rationale": "The model should not store raw message text.",
    }
    packet = {
        "people": [
            {
                "relationship_intelligence": {
                    "evidence": [
                        {
                            "id": "evidence-1",
                            "snippet": snippet,
                        }
                    ]
                }
            }
        ]
    }

    try:
        validate_no_raw_private_leakage(proposal, packet)
    except ValueError as exc:
        assert "raw private evidence" in str(exc)
    else:
        raise AssertionError("expected raw private evidence leakage to be rejected")


def test_run_relationship_tone_tenor_analysis_cli_passes_bounds(database_url, monkeypatch, tmp_path, capsys):
    from relationship_substrate import cli

    captured: dict[str, object] = {}

    def fake_runner(database_url: str, **kwargs: object) -> dict[str, object]:
        captured["database_url"] = database_url
        captured.update(kwargs)
        return {"ok": True, "applied": 1}

    monkeypatch.setattr(cli, "run_relationship_tone_tenor_analysis", fake_runner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "relationship-substrate",
            "--database-url",
            database_url,
            "run-relationship-tone-analysis",
            "--output-dir",
            str(tmp_path / "tone"),
            "--limit",
            "3",
            "--evidence-limit",
            "4",
            "--model",
            "test-model",
            "--apply",
        ],
    )

    assert cli.main() == 0
    assert captured["database_url"] == database_url
    assert captured["output_dir"] == tmp_path / "tone"
    assert captured["limit"] == 3
    assert captured["evidence_limit"] == 4
    assert captured["model"] == "test-model"
    assert captured["apply"] is True
    assert '"applied": 1' in capsys.readouterr().out
