from __future__ import annotations

import json
import sys
from uuid import uuid4

import psycopg
import pytest

from relationship_substrate.cli import main
from relationship_substrate.db import run_migrations
from relationship_substrate.network_feedback import list_network_feedback, record_network_feedback
from relationship_substrate.network_packets import persist_ask_network_packet


def _run_cli(monkeypatch, capsys, *args: str) -> dict:
    monkeypatch.setattr(sys, "argv", ["relationship-substrate", *args])
    assert main() == 0
    return json.loads(capsys.readouterr().out)


def _saved_packet(database_url: str, *, email: str | None = None) -> dict:
    email = email or f"feedback-{uuid4().hex}@example.com"
    packet = {
        "ask_stage": "network_relationship_packet",
        "contract_version": 1,
        "query": {
            "goal": "Find consultants at small firms.",
            "search_mode": "history_backed",
            "constraints": {},
            "limits": {"candidate_limit": 1},
        },
        "readiness": {
            "ready_for_model_ranking": True,
            "ready_for_outreach_drafting": False,
            "warnings": [],
            "missing": [],
            "stale": [],
            "refresh_actions": [],
        },
        "count": 1,
        "people": [
            {
                "email": email,
                "search_hit": {"email": email},
                "packet_readiness": {},
                "evidence_summary": {"evidence_ref_count": 1},
                "organization_context": {"domain": "example.com"},
                "model_inputs": {
                    "candidate_evidence_refs": ["evidence-1"],
                    "candidate_research_refs": ["research-1"],
                },
            }
        ],
        "research_context": {"sources": [{"id": "research-1"}]},
        "model_recommendation_validation": {
            "valid": True,
            "ranked_recommendations": [
                {
                    "person_email": email,
                    "priority": "model-ranked-high",
                    "goal_fit_rationale": "Model rationale.",
                    "relationship_rationale": "Model relationship rationale.",
                    "relationship_risk_or_caution": "Model caution.",
                    "best_angle": "Model angle.",
                    "next_action": "Model action.",
                    "draft_email": {"subject": "Subject", "body": "Body"},
                    "cited_evidence_refs": ["evidence-1"],
                    "cited_research_refs": ["research-1"],
                }
            ],
        },
    }
    return persist_ask_network_packet(database_url, packet)


def test_migrations_create_network_feedback_table(database_url):
    run_migrations(database_url)

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'relationship_substrate'
                AND table_name = 'network_feedback'
                """
            )
            table_exists = cur.fetchone() is not None

    assert table_exists is True


def test_record_network_feedback_links_to_packet_and_person(database_url):
    run_migrations(database_url)
    email = f"person-{uuid4().hex}@example.com"
    packet = _saved_packet(database_url, email=email)

    feedback = record_network_feedback(
        database_url,
        packet_id=packet["id"],
        feedback_kind="recommendation_review",
        feedback={
            "useful": True,
            "preferred_angle": "Follow up on the workshop thread.",
            "next_action_status": "save_for_review",
        },
        person_email=email,
    )
    feedback_rows = list_network_feedback(database_url, packet_id=packet["id"])

    assert feedback["packet_id"] == packet["id"]
    assert feedback["person_email"] == email
    assert feedback["feedback_kind"] == "recommendation_review"
    assert feedback["feedback"]["useful"] is True
    assert feedback_rows == [feedback]


def test_record_network_feedback_rejects_person_not_in_packet(database_url):
    run_migrations(database_url)
    packet = _saved_packet(database_url)

    with pytest.raises(ValueError, match="person_email is not present"):
        record_network_feedback(
            database_url,
            packet_id=packet["id"],
            feedback_kind="recommendation_review",
            feedback={"useful": False, "rejected_premise": "Wrong person."},
            person_email="missing@example.com",
        )


def test_network_feedback_cli_records_and_lists_feedback(database_url, tmp_path, monkeypatch, capsys):
    run_migrations(database_url)
    email = f"cli-{uuid4().hex}@example.com"
    packet = _saved_packet(database_url, email=email)
    feedback_path = tmp_path / "feedback.json"
    feedback_payload = {
        "useful": False,
        "edited_draft": {"subject": "Edited subject", "body": "Edited body"},
        "caution_note": "Wait until there is a better reason to reach out.",
    }
    feedback_path.write_text(json.dumps(feedback_payload), encoding="utf-8")

    recorded = _run_cli(
        monkeypatch,
        capsys,
        "--database-url",
        database_url,
        "record-network-feedback",
        "--packet-id",
        packet["id"],
        "--person-email",
        email,
        "--kind",
        "draft_review",
        "--feedback",
        str(feedback_path),
    )
    listed = _run_cli(
        monkeypatch,
        capsys,
        "--database-url",
        database_url,
        "list-network-feedback",
        "--packet-id",
        packet["id"],
    )

    assert recorded["feedback"]["edited_draft"]["subject"] == "Edited subject"
    assert listed["count"] == 1
    assert listed["feedback"][0]["id"] == recorded["id"]
