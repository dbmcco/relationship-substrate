from __future__ import annotations

import json
import sys
from uuid import uuid4

import psycopg

from relationship_substrate.cli import main
from relationship_substrate.contracts import SourceEventIn, SourcePosture
from relationship_substrate.db import run_migrations
from relationship_substrate.materialize import materialize_msgvault_correspondence
from relationship_substrate.organizations import upsert_organization_enrichment
from relationship_substrate.repositories import upsert_evidence_ref, upsert_source_event
from relationship_substrate.research import research_context_from_snapshots, upsert_research_snapshot


def _run_cli(monkeypatch, capsys, *args: str) -> dict:
    monkeypatch.setattr(sys, "argv", ["relationship-substrate", *args])
    assert main() == 0
    return json.loads(capsys.readouterr().out)


def _relationship_evidence(database_url: str, *, email: str) -> str:
    event = SourceEventIn(
        source_name="msgvault",
        source_event_type="correspondence_message",
        source_event_key=f"msgvault:correspondence:{email}:research-snapshot-1",
        source_payload={
            "id": "research-snapshot-1",
            "relationship_email": email,
            "relationship_direction": "from_contact",
            "from_email": email,
            "from_name": "Research Snapshot Person",
            "sent_at": "2026-05-01T12:00:00Z",
            "subject": "Potential collaboration",
            "snippet": "Direct relationship evidence for research snapshot tests.",
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
        ref_value=f"{email}:research-snapshot-1",
        metadata={"relationship_email": email, "msgvault_message_id": "research-snapshot-1"},
    )
    materialize_msgvault_correspondence(database_url)
    return str(evidence_ref_id)


def test_migrations_create_research_snapshot_table(database_url):
    run_migrations(database_url)

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'relationship_substrate'
                AND table_name = 'research_snapshot'
                """
            )
            table_exists = cur.fetchone() is not None

    assert table_exists is True


def test_research_snapshot_context_exposes_citable_sources(database_url):
    run_migrations(database_url)
    subject = f"small consultancy query {uuid4().hex}"

    snapshot = upsert_research_snapshot(
        database_url,
        subject_type="query",
        subject=subject,
        summary="Recent external context for a small consultancy query.",
        confidence="medium",
        sources=[
            {
                "url": "https://example.com/source",
                "title": "Example source",
                "publisher": "Example",
            }
        ],
    )
    context = research_context_from_snapshots(database_url, subject=subject)

    assert context["snapshots"][0]["id"] == snapshot["id"]
    assert context["snapshots"][0]["subject"] == subject
    assert context["snapshots"][0]["retrieved_at"] == snapshot["retrieved_at"]
    assert context["snapshots"][0]["sources"][0]["id"] == snapshot["sources"][0]["id"]
    assert context["sources"][0]["id"] == snapshot["sources"][0]["id"]
    assert context["sources"][0]["snapshot_id"] == snapshot["id"]


def test_ask_network_cli_loads_research_snapshot_context_and_validates_recommendation(
    database_url,
    tmp_path,
    monkeypatch,
    capsys,
):
    run_migrations(database_url)
    run_id = uuid4().hex
    unique_count = 1_400_000 + int(run_id[:6], 16)
    domain = f"ask-research-{run_id}.example"
    email = f"consultant@{domain}"
    evidence_ref_id = _relationship_evidence(database_url, email=email)
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
    subject = f"ask-network research {run_id}"
    snapshot = upsert_research_snapshot(
        database_url,
        subject_type="query",
        subject=subject,
        summary="Snapshot-backed research context.",
        confidence="high",
        sources=[{"id": "snapshot-news", "url": "https://example.com/snapshot-news"}],
    )
    proposal_path = tmp_path / "recommendations.json"
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
        "cited_research_refs": ["snapshot-news"],
    }
    proposal_path.write_text(json.dumps([recommendation]), encoding="utf-8")

    packet = _run_cli(
        monkeypatch,
        capsys,
        "--database-url",
        database_url,
        "ask-network",
        "--goal",
        "Find consultants at small firms.",
        "--actual-employee-count-min",
        str(unique_count),
        "--actual-employee-count-max",
        str(unique_count),
        "--consultant-count-min",
        str(unique_count),
        "--consultant-count-max",
        str(unique_count),
        "--limit",
        "1",
        "--research-snapshot-subject",
        subject,
        "--model-proposal",
        str(proposal_path),
    )

    assert packet["research_context"]["snapshots"][0]["id"] == snapshot["id"]
    assert packet["research_context"]["snapshots"][0]["subject"] == subject
    assert packet["model_recommendation_validation"]["ranked_recommendations"] == [recommendation]
