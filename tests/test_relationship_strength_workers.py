from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import psycopg

from relationship_substrate.contracts import SourceEventIn, SourcePosture
from relationship_substrate.db import run_migrations
from relationship_substrate.materialize import materialize_msgvault_correspondence
from relationship_substrate.relationship_strength_workers import (
    missing_relationship_strength_emails,
    parse_relationship_strength_proposal,
    run_relationship_strength_analysis,
)
from relationship_substrate.repositories import upsert_evidence_ref, upsert_source_event


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
        source_event_key=f"msgvault:strength:{email}:{message_id}",
        source_payload={
            "id": message_id,
            "relationship_email": email,
            "relationship_direction": "from_contact",
            "from_email": email,
            "from_name": "Strength Worker Person",
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


def test_missing_relationship_strength_emails_returns_people_with_interactions(database_url):
    run_migrations(database_url)
    email = f"missing-strength-{uuid4().hex}@example.com"
    _insert_correspondence_evidence(database_url, email=email)
    materialize_msgvault_correspondence(database_url)

    emails = missing_relationship_strength_emails(database_url, limit=100000)

    assert email in emails


def test_missing_relationship_strength_emails_skips_automated_contacts(database_url):
    run_migrations(database_url)
    human_email = f"human-strength-{uuid4().hex}@example.com"
    automated_emails = [
        "invitations@linkedin.com",
        f"drive-shares-noreply-{uuid4().hex}@google.com",
        f"p2p-helpdesk.noreply-{uuid4().hex}@novartis.com",
        f"email@emails-{uuid4().hex}.example.com",
    ]
    _insert_correspondence_evidence(database_url, email=human_email)
    for automated_email in automated_emails:
        _insert_correspondence_evidence(database_url, email=automated_email)
    materialize_msgvault_correspondence(database_url)

    emails = missing_relationship_strength_emails(database_url, limit=100000)

    assert human_email in emails
    assert not set(automated_emails) & set(emails)


def test_parse_relationship_strength_proposal_normalizes_string_evidence_ids():
    proposal = parse_relationship_strength_proposal(
        json.dumps(
            {
                "summary": "Strong, current relationship with repeated direct interaction.",
                "rationale": "Grounded in supplied mechanical facts and evidence.",
                "evidence_refs": ["evidence-1"],
            }
        )
    )

    assert proposal == {
        "state_kind": "relationship_strength",
        "summary": "Strong, current relationship with repeated direct interaction.",
        "rationale": "Grounded in supplied mechanical facts and evidence.",
        "evidence_refs": [{"id": "evidence-1"}],
        "supersedes_id": None,
    }


def test_run_relationship_strength_analysis_persists_valid_model_proposals(database_url, tmp_path):
    run_migrations(database_url)
    email = f"strength-worker-{uuid4().hex}@example.com"
    evidence_ref_id = _insert_correspondence_evidence(database_url, email=email)
    materialize_msgvault_correspondence(database_url)
    calls: list[dict] = []

    def fake_model(packet: dict) -> str:
        calls.append(packet)
        return json.dumps(
            {
                "summary": "Strong and current relationship with direct recent engagement.",
                "rationale": "The model cites supplied correspondence evidence and mechanical facts.",
                "evidence_refs": [{"id": evidence_ref_id}],
            }
        )

    report = run_relationship_strength_analysis(
        database_url,
        output_dir=tmp_path / "strength",
        limit=100000,
        apply=True,
        generate_proposal=fake_model,
    )

    assert report["applied"] >= 1
    assert any(call["analysis_stage"] == "relationship_strength" for call in calls)
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
                AND rs.state_kind = 'relationship_strength'
                """,
                (email,),
            )
            row = cur.fetchone()
            assert row[0] == "Strong and current relationship with direct recent engagement."
            assert "mechanical facts" in row[1]
            assert row[2] == [{"id": evidence_ref_id}]


def test_run_relationship_strength_analysis_repairs_invalid_model_proposals(database_url, tmp_path):
    run_migrations(database_url)
    email = f"strength-repair-{uuid4().hex}@example.com"
    evidence_ref_id = _insert_correspondence_evidence(database_url, email=email)
    materialize_msgvault_correspondence(database_url)
    repair_calls: list[dict] = []

    def bad_model(packet: dict) -> str:
        return json.dumps(
            {
                "summary": "Strong and current.",
                "rationale": "Missing evidence refs should trigger repair.",
                "evidence_refs": [],
            }
        )

    def repair_model(packet: dict, raw_response: str, error: str) -> str:
        repair_calls.append({"packet": packet, "raw_response": raw_response, "error": error})
        return json.dumps(
            {
                "summary": "Strong and current.",
                "rationale": "The repaired proposal cites supplied evidence.",
                "evidence_refs": [{"id": evidence_ref_id}],
            }
        )

    report = run_relationship_strength_analysis(
        database_url,
        output_dir=tmp_path / "strength",
        limit=100000,
        apply=True,
        generate_proposal=bad_model,
        repair_proposal=repair_model,
    )

    assert report["applied"] >= 1
    assert repair_calls
    assert "requires evidence_refs" in repair_calls[0]["error"]


def test_run_relationship_strength_analysis_cli_passes_bounds(database_url, monkeypatch, tmp_path, capsys):
    from relationship_substrate import cli

    captured: dict[str, object] = {}

    def fake_runner(database_url: str, **kwargs: object) -> dict[str, object]:
        captured["database_url"] = database_url
        captured.update(kwargs)
        return {"ok": True, "applied": 1}

    monkeypatch.setattr(cli, "run_relationship_strength_analysis", fake_runner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "relationship-substrate",
            "--database-url",
            database_url,
            "run-relationship-strength-analysis",
            "--output-dir",
            str(tmp_path / "strength"),
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
    assert captured["output_dir"] == tmp_path / "strength"
    assert captured["limit"] == 3
    assert captured["evidence_limit"] == 4
    assert captured["model"] == "test-model"
    assert captured["apply"] is True
    assert '"applied": 1' in capsys.readouterr().out
