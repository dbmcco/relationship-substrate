from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

from relationship_substrate.config import Settings
from relationship_substrate.contracts import SourceEventIn, SourcePosture
from relationship_substrate.db import run_migrations
from relationship_substrate.materialize import materialize_msgvault_correspondence
from relationship_substrate.operations import select_correspondence_seed_emails, substrate_status
from relationship_substrate.repositories import upsert_evidence_ref, upsert_source_event


def test_select_correspondence_seed_emails_applies_msgvault_skip_rules():
    rows = [
        {"email": "braydon@intempio.com", "message_count": 1000},
        {"email": "Anne@Intempio.com", "message_count": 900},
        {"email": "events@example.com", "message_count": 800},
        {"email": "groups-noreply@linkedin.com", "message_count": 750},
        {"email": "calendar-notification@google.com", "message_count": 725},
        {"email": "person@example.com", "message_count": 700},
        {"email": "person@example.com", "message_count": 600},
        {"email": "advisor@example.org", "message_count": 500},
    ]

    assert select_correspondence_seed_emails(
        rows,
        limit=2,
        self_aliases={"braydon@intempio.com"},
        skipped_domains={"intempio.com"},
        skipped_system_localparts={"events"},
        skipped_system_prefixes={"calendar-notification", "groups-noreply"},
    ) == ["person@example.com", "advisor@example.org"]


def test_run_network_pipeline_cli_passes_operational_inputs(monkeypatch, tmp_path, capsys):
    from relationship_substrate import cli

    captured: dict[str, object] = {}

    def fake_run_network_pipeline(settings: Settings, **kwargs: object) -> dict[str, object]:
        captured["settings"] = settings
        captured.update(kwargs)
        return {"ok": True, "output_dir": str(kwargs["output_dir"])}

    monkeypatch.setattr(cli, "run_network_pipeline", fake_run_network_pipeline)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "relationship-substrate",
            "--database-url",
            "postgresql://localhost:5432/relationship_substrate_ops_test",
            "run-network-pipeline",
            "--next-up-path",
            str(tmp_path / "next_up"),
            "--calendar-path",
            str(tmp_path / "calendar.json"),
            "--output-dir",
            str(tmp_path / "out"),
            "--sender-limit",
            "7",
            "--correspondence-from-senders",
            "2",
            "--correspondence-message-limit",
            "3",
            "--embed-limit",
            "11",
            "--skip-embeddings",
        ],
    )

    assert cli.main() == 0

    assert isinstance(captured["settings"], Settings)
    assert captured["settings"].database_url == "postgresql://localhost:5432/relationship_substrate_ops_test"
    assert captured["next_up_paths"] == [Path(tmp_path / "next_up")]
    assert captured["calendar_paths"] == [Path(tmp_path / "calendar.json")]
    assert captured["output_dir"] == Path(tmp_path / "out")
    assert captured["sender_limit"] == 7
    assert captured["correspondence_from_senders"] == 2
    assert captured["correspondence_message_limit"] == 3
    assert captured["embed_limit"] == 11
    assert captured["skip_embeddings"] is True
    assert '"ok": true' in capsys.readouterr().out


def test_substrate_status_reports_operational_health(database_url):
    run_migrations(database_url)
    email = f"status-{uuid4().hex}@example.com"
    event = SourceEventIn(
        source_name="msgvault",
        source_event_type="correspondence_message",
        source_event_key=f"msgvault:correspondence:{email}:status-1",
        source_payload={
            "id": "status-1",
            "relationship_email": email,
            "from_email": email,
            "sent_at": "2026-05-01T12:00:00Z",
            "subject": "Status seed",
            "snippet": "Evidence for status reporting.",
        },
        source_posture=SourcePosture.DIRECT_INTERACTION,
        provenance_status="msgvault_message",
        trust_role="direct email correspondence evidence",
    )
    source_event_id = upsert_source_event(database_url, event)
    upsert_evidence_ref(
        database_url,
        source_event_id=source_event_id,
        ref_type="msgvault_message",
        ref_value=f"{email}:status-1",
        metadata={"relationship_email": email},
    )
    materialize_msgvault_correspondence(database_url)

    status = substrate_status(database_url)

    assert status["status_stage"] == "relationship_substrate_status"
    assert status["counts"]["source_event"] >= 1
    assert status["sources"]["msgvault"]["total"] >= 1
    assert status["embeddings"]["people"]["missing"] >= 1
    assert status["tone_state"]["missing_people_count"] >= 1
    assert "relationship_tone_tenor_state" in status["actionable_queues"]


def test_substrate_status_cli_outputs_health_report(monkeypatch, capsys):
    from relationship_substrate import cli

    monkeypatch.setattr(
        cli,
        "substrate_status",
        lambda database_url, **kwargs: {
            "status_stage": "relationship_substrate_status",
            "database_url": database_url,
            "actionable_queues": {},
        },
    )
    monkeypatch.setattr(cli, "run_migrations", lambda database_url: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "relationship-substrate",
            "--database-url",
            "postgresql://localhost:5432/relationship_substrate_ops_test",
            "substrate-status",
        ],
    )

    assert cli.main() == 0
    assert '"relationship_substrate_status"' in capsys.readouterr().out
