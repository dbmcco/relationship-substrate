from __future__ import annotations

import json
import sys
from uuid import uuid4

from relationship_substrate.cli import main
from relationship_substrate.contracts import SourceEventIn, SourcePosture
from relationship_substrate.db import run_migrations
from relationship_substrate.materialize import materialize_msgvault_correspondence
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
        source_event_key=f"msgvault:correspondence:{email}:ask-network-1",
        source_payload={
            "id": "ask-network-1",
            "relationship_email": email,
            "relationship_direction": "from_contact",
            "from_email": email,
            "from_name": "Ask Network Person",
            "sent_at": "2026-05-01T12:00:00Z",
            "subject": "Potential collaboration",
            "snippet": "Direct relationship evidence for the ask-network packet.",
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
        ref_value=f"{email}:ask-network-1",
        metadata={"relationship_email": email, "msgvault_message_id": "ask-network-1"},
    )
    materialize_msgvault_correspondence(database_url)
    return str(evidence_ref_id)


def test_ask_network_cli_returns_contract_packet_without_model_judgment(
    database_url,
    monkeypatch,
    capsys,
):
    run_migrations(database_url)
    run_id = uuid4().hex
    domain = f"ask-network-{run_id}.example"
    email = f"consultant@{domain}"
    evidence_ref_id = _relationship_evidence(database_url, email=email)
    upsert_organization_enrichment(
        database_url,
        company_name=domain,
        company_type="small_medcoms_consultancy",
        employee_count_min=10,
        employee_count_max=10,
        employee_count_label="test sourced team count",
        consultant_count_estimate=10,
        source_name="test_fixture",
        source_url="https://example.com/small-consultancy",
        provenance_status="test",
    )

    packet = _run_cli(
        monkeypatch,
        capsys,
        "--database-url",
        database_url,
        "ask-network",
        "--goal",
        "Give me five people who are consultants, who are at firms that have around ten people on staff.",
        "--actual-employee-count-min",
        "8",
        "--actual-employee-count-max",
        "15",
        "--consultant-count-min",
        "8",
        "--consultant-count-max",
        "20",
        "--limit",
        "1000",
        "--evidence-limit",
        "3",
    )

    assert packet["ask_stage"] == "network_relationship_packet"
    assert packet["contract_version"] == 1
    assert packet["query"]["goal"].startswith("Give me five people")
    assert packet["query"]["search_mode"] == "history_backed"
    assert packet["query"]["constraints"]["actual_employee_count_min"] == 8
    assert packet["query"]["constraints"]["actual_employee_count_max"] == 15
    assert packet["readiness"]["ready_for_model_ranking"] is True
    assert packet["readiness"]["ready_for_outreach_drafting"] is False
    assert "research_context" in packet["readiness"]["missing"]
    assert packet["count"] >= 1

    person_packet = next(person for person in packet["people"] if person["email"] == email)
    assert person_packet["search_hit"]["domain"] == domain
    assert person_packet["relationship_intelligence"]["evidence"][0]["id"] == evidence_ref_id
    assert person_packet["evidence_summary"]["has_direct_relationship_evidence"] is True
    assert person_packet["evidence_summary"]["has_organization_enrichment"] is True
    assert person_packet["organization_context"] == {
        "name": domain,
        "domain": domain,
        "company_type": "small_medcoms_consultancy",
        "actual_employee_count_min": 10,
        "actual_employee_count_max": 10,
        "employee_count_label": "test sourced team count",
        "consultant_count_estimate": 10,
        "source_name": "test_fixture",
        "source_url": "https://example.com/small-consultancy",
        "provenance_status": "test",
    }
    assert person_packet["packet_readiness"]["ready_for_outreach_drafting"] is False
    assert "relationship_tone_tenor_state" in person_packet["packet_readiness"]["missing"]
    assert person_packet["model_inputs"]["goal"] == packet["query"]["goal"]
    assert evidence_ref_id in person_packet["model_inputs"]["candidate_evidence_refs"]
    assert "draft_email" not in person_packet
