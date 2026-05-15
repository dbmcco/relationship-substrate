from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import uuid4

from relationship_substrate.config import Settings
from relationship_substrate.contracts import SourceEventIn, SourcePosture
from relationship_substrate.db import run_migrations
from relationship_substrate.materialize import materialize_msgvault_correspondence
from relationship_substrate.network_ask import prepare_ask_network_packet
from relationship_substrate.operations import (
    evaluate_non_ui_workflow,
    run_autonomous_backfill,
    select_correspondence_seed_emails,
    substrate_status,
)
from relationship_substrate.organizations import upsert_organization_enrichment
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


def test_evaluate_non_ui_workflow_validates_packet_recommendations_persistence_and_feedback(
    database_url,
):
    run_migrations(database_url)
    run_id = uuid4().hex
    unique_count = 1_600_000 + int(run_id[:6], 16)
    domain = f"non-ui-eval-{run_id}.example"
    email = f"consultant@{domain}"
    event = SourceEventIn(
        source_name="msgvault",
        source_event_type="correspondence_message",
        source_event_key=f"msgvault:correspondence:{email}:eval-1",
        source_payload={
            "id": "eval-1",
            "relationship_email": email,
            "from_email": email,
            "sent_at": "2026-05-01T12:00:00Z",
            "subject": "Eval seed",
            "snippet": "Evidence for non-UI eval.",
        },
        source_posture=SourcePosture.DIRECT_INTERACTION,
        provenance_status="msgvault_message",
        trust_role="direct email correspondence evidence",
    )
    source_event_id = upsert_source_event(database_url, event)
    evidence_ref_id = str(
        upsert_evidence_ref(
            database_url,
            source_event_id=source_event_id,
            ref_type="msgvault_message",
            ref_value=f"{email}:eval-1",
            metadata={"relationship_email": email},
        )
    )
    materialize_msgvault_correspondence(database_url)
    upsert_organization_enrichment(
        database_url,
        company_name=domain,
        company_type="small_consulting_firm",
        employee_count_min=unique_count,
        employee_count_max=unique_count,
        consultant_count_estimate=unique_count,
        source_name="test_fixture",
        provenance_status="test",
    )
    packet = prepare_ask_network_packet(
        database_url,
        goal="Find consultants at small firms.",
        actual_employee_count_min=unique_count,
        actual_employee_count_max=unique_count,
        consultant_count_min=unique_count,
        consultant_count_max=unique_count,
        limit=1,
        research_context={"sources": [{"id": "eval-research", "url": "https://example.com/eval"}]},
    )
    recommendation = {
        "person_email": email,
        "priority": "model-ranked-high",
        "goal_fit_rationale": "Model-authored goal fit.",
        "relationship_rationale": "Model-authored relationship rationale.",
        "relationship_risk_or_caution": "Model-authored caution.",
        "best_angle": "Model-authored angle.",
        "next_action": "Model-authored next action.",
        "draft_email": {"subject": "Model subject", "body": "Model body"},
        "cited_evidence_refs": [evidence_ref_id],
        "cited_research_refs": ["eval-research"],
    }

    report = evaluate_non_ui_workflow(
        database_url,
        packet=packet,
        recommendations=[recommendation],
        feedback_person_email=email,
        feedback_kind="eval_decision",
        feedback={"decision": "reviewed", "note": "Eval feedback persisted."},
    )

    assert report["eval_stage"] == "non_ui_end_to_end_eval"
    assert report["ok"] is True
    assert report["packet_record"]["id"]
    assert report["feedback_record"]["id"]
    checks = {check["id"]: check for check in report["checks"]}
    assert all(check["passed"] for check in checks.values())
    assert checks["tone_state_readiness"]["detail"] == "Tone-state worklist exposes missing candidates."


def test_eval_non_ui_workflow_cli_reads_json_inputs(monkeypatch, tmp_path, capsys):
    from relationship_substrate import cli

    packet_path = tmp_path / "packet.json"
    recommendations_path = tmp_path / "recommendations.json"
    feedback_path = tmp_path / "feedback.json"
    packet_path.write_text(json.dumps({"ask_stage": "network_relationship_packet"}), encoding="utf-8")
    recommendations_path.write_text(json.dumps([{"person_email": "person@example.com"}]), encoding="utf-8")
    feedback_path.write_text(json.dumps({"decision": "reviewed"}), encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_eval(database_url: str, **kwargs: object) -> dict[str, object]:
        captured["database_url"] = database_url
        captured.update(kwargs)
        return {"eval_stage": "non_ui_end_to_end_eval", "ok": True}

    monkeypatch.setattr(cli, "run_migrations", lambda database_url: None)
    monkeypatch.setattr(cli, "evaluate_non_ui_workflow", fake_eval)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "relationship-substrate",
            "--database-url",
            "postgresql://localhost:5432/relationship_substrate_ops_test",
            "eval-non-ui-workflow",
            "--ask-packet",
            str(packet_path),
            "--model-proposal",
            str(recommendations_path),
            "--feedback",
            str(feedback_path),
            "--feedback-person-email",
            "person@example.com",
            "--feedback-kind",
            "eval_decision",
        ],
    )

    assert cli.main() == 0
    assert captured["packet"] == {"ask_stage": "network_relationship_packet"}
    assert captured["recommendations"] == [{"person_email": "person@example.com"}]
    assert captured["feedback"] == {"decision": "reviewed"}
    assert captured["feedback_person_email"] == "person@example.com"
    assert captured["feedback_kind"] == "eval_decision"
    assert '"ok": true' in capsys.readouterr().out


def test_run_autonomous_backfill_writes_operational_artifacts(database_url, tmp_path):
    run_migrations(database_url)

    report = run_autonomous_backfill(
        Settings(database_url=database_url),
        output_dir=tmp_path / "autonomous",
        max_iterations=1,
        sleep_seconds=0,
        skip_embeddings=True,
    )

    assert report["ok"] is True
    assert report["iterations_completed"] == 1
    iteration = report["iterations"][0]
    assert iteration["materialization"]["exact_emails"]["source"] == "next_up"
    assert Path(iteration["artifacts"]["status"]).exists()
    assert Path(iteration["artifacts"]["ask_network_packet"]).exists()
    assert Path(iteration["artifacts"]["tone_state_worklist"]).exists()
    assert report["final_status"]["status_stage"] == "relationship_substrate_status"


def test_run_autonomous_backfill_stops_when_embedding_queue_is_idle(database_url, tmp_path, monkeypatch):
    run_migrations(database_url)
    embedding_calls: list[int | None] = []

    def fake_embed_curated_contacts(
        database_url: str,
        *,
        embed_texts,
        provider_name: str,
        model: str | None,
        limit: int | None,
    ) -> dict[str, object]:
        embedding_calls.append(limit)
        if len(embedding_calls) == 1:
            return {
                "source": "next_up",
                "provider": provider_name,
                "model": model or "",
                "candidates": 1,
                "embedded": 1,
            }
        return {
            "source": "next_up",
            "provider": provider_name,
            "model": model or "",
            "candidates": 0,
            "embedded": 0,
        }

    monkeypatch.setattr(
        "relationship_substrate.operations.embed_curated_contacts",
        fake_embed_curated_contacts,
    )

    report = run_autonomous_backfill(
        Settings(database_url=database_url),
        output_dir=tmp_path / "autonomous",
        max_iterations=2,
        sleep_seconds=0,
        embed_texts=lambda texts: [[1.0, *([0.0] * 1535)] for _ in texts],
        embed_provider="test",
        embed_model="test-model",
        embed_limit=10,
    )

    assert report["iterations_completed"] == 2
    assert report["iterations"][0]["embeddings"]["embedded"] >= 1
    assert report["iterations"][1]["embeddings"]["candidates"] == 0
    assert embedding_calls == [10, 10]


def test_run_autonomous_backfill_cli_passes_bounds(monkeypatch, tmp_path, capsys):
    from relationship_substrate import cli

    captured: dict[str, object] = {}

    def fake_backfill(settings: Settings, **kwargs: object) -> dict[str, object]:
        captured["settings"] = settings
        captured.update(kwargs)
        return {"ok": True, "iterations_completed": 1}

    monkeypatch.setattr(cli, "run_autonomous_backfill", fake_backfill)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "relationship-substrate",
            "--database-url",
            "postgresql://localhost:5432/relationship_substrate_ops_test",
            "run-autonomous-backfill",
            "--output-dir",
            str(tmp_path / "auto"),
            "--max-iterations",
            "3",
            "--sleep-seconds",
            "2",
            "--embed-limit",
            "17",
            "--skip-embeddings",
        ],
    )

    assert cli.main() == 0
    assert isinstance(captured["settings"], Settings)
    assert captured["output_dir"] == tmp_path / "auto"
    assert captured["max_iterations"] == 3
    assert captured["sleep_seconds"] == 2
    assert captured["embed_limit"] == 17
    assert captured["skip_embeddings"] is True
    assert '"ok": true' in capsys.readouterr().out
