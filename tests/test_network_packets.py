from __future__ import annotations

import json
import sys
from uuid import uuid4

import psycopg

from relationship_substrate.cli import main
from relationship_substrate.contracts import SourceEventIn, SourcePosture
from relationship_substrate.db import run_migrations
from relationship_substrate.materialize import materialize_msgvault_correspondence
from relationship_substrate.network_ask import prepare_ask_network_packet, validate_ask_network_recommendations
from relationship_substrate.network_packets import get_network_packet, persist_ask_network_packet
from relationship_substrate.organizations import upsert_organization_enrichment
from relationship_substrate.repositories import upsert_evidence_ref, upsert_source_event


def _run_cli(monkeypatch, capsys, *args: str) -> dict:
    monkeypatch.setattr(sys, "argv", ["relationship-substrate", *args])
    assert main() == 0
    return json.loads(capsys.readouterr().out)


def _relationship_evidence(database_url: str, *, email: str) -> str:
    event = SourceEventIn(
        source_name="msgvault",
        source_event_type="correspondence_message",
        source_event_key=f"msgvault:correspondence:{email}:network-packet-1",
        source_payload={
            "id": "network-packet-1",
            "relationship_email": email,
            "relationship_direction": "from_contact",
            "from_email": email,
            "from_name": "Network Packet Person",
            "sent_at": "2026-05-01T12:00:00Z",
            "subject": "Potential collaboration",
            "snippet": "Direct relationship evidence for packet persistence tests.",
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
        ref_value=f"{email}:network-packet-1",
        metadata={"relationship_email": email, "msgvault_message_id": "network-packet-1"},
    )
    materialize_msgvault_correspondence(database_url)
    return str(evidence_ref_id)


def _packet(database_url: str) -> tuple[dict, dict]:
    run_id = uuid4().hex
    unique_count = 1_500_000 + int(run_id[:6], 16)
    domain = f"network-packet-{run_id}.example"
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
    packet = prepare_ask_network_packet(
        database_url,
        goal="Find consultants at small firms.",
        actual_employee_count_min=unique_count,
        actual_employee_count_max=unique_count,
        consultant_count_min=unique_count,
        consultant_count_max=unique_count,
        limit=1,
        research_context={"sources": [{"id": "packet-news", "url": "https://example.com/news"}]},
        evidence_limit=3,
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
        "cited_research_refs": ["packet-news"],
    }
    packet["model_recommendation_validation"] = {
        "valid": True,
        "ranked_recommendations": validate_ask_network_recommendations(packet, [recommendation]),
    }
    return packet, recommendation


def test_migrations_create_network_packet_table(database_url):
    run_migrations(database_url)

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'relationship_substrate'
                AND table_name = 'network_packet'
                """
            )
            table_exists = cur.fetchone() is not None

    assert table_exists is True


def test_persist_ask_network_packet_stores_summary_refs_and_model_recommendations(database_url):
    run_migrations(database_url)
    packet, recommendation = _packet(database_url)

    record = persist_ask_network_packet(database_url, packet)
    saved = get_network_packet(database_url, packet_id=record["id"])

    assert saved["id"] == record["id"]
    assert saved["packet_kind"] == "ask_network"
    assert saved["contract_version"] == 1
    assert saved["query"] == packet["query"]
    assert saved["readiness"] == packet["readiness"]
    assert saved["model_recommendations"] == [recommendation]
    assert saved["packet_summary"]["people"][0]["email"] == recommendation["person_email"]
    assert saved["source_refs"]["people"][0]["evidence_refs"] == recommendation["cited_evidence_refs"]
    assert "relationship_intelligence" not in saved["packet_summary"]["people"][0]


def test_ask_network_cli_can_save_and_show_packet(database_url, tmp_path, monkeypatch, capsys):
    run_migrations(database_url)
    packet, recommendation = _packet(database_url)
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(json.dumps([recommendation]), encoding="utf-8")
    research_path = tmp_path / "research.json"
    research_path.write_text(
        json.dumps({"sources": [{"id": "packet-news", "url": "https://example.com/news"}]}),
        encoding="utf-8",
    )
    person = packet["people"][0]
    enrichment = person["organization_context"]

    output = _run_cli(
        monkeypatch,
        capsys,
        "--database-url",
        database_url,
        "ask-network",
        "--goal",
        packet["query"]["goal"],
        "--actual-employee-count-min",
        str(enrichment["actual_employee_count_min"]),
        "--actual-employee-count-max",
        str(enrichment["actual_employee_count_max"]),
        "--consultant-count-min",
        str(enrichment["consultant_count_estimate"]),
        "--consultant-count-max",
        str(enrichment["consultant_count_estimate"]),
        "--limit",
        "1",
        "--research-context",
        str(research_path),
        "--model-proposal",
        str(proposal_path),
        "--save-packet",
    )

    saved = _run_cli(
        monkeypatch,
        capsys,
        "--database-url",
        database_url,
        "show-network-packet",
        "--id",
        output["packet_record"]["id"],
    )

    assert output["packet_record"]["packet_kind"] == "ask_network"
    assert saved["model_recommendations"] == [recommendation]
