from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from relationship_substrate.cli import main
from relationship_substrate.contracts import SourceEventIn, SourcePosture
from relationship_substrate.db import run_migrations
from relationship_substrate.materialize import materialize_exact_emails, materialize_msgvault_correspondence
from relationship_substrate.organizations import upsert_organization_enrichment
from relationship_substrate.outreach import (
    prepare_history_backed_outreach_proposal_packet,
    prepare_outreach_proposal_packet,
    validate_outreach_proposal,
)
from relationship_substrate.repositories import upsert_evidence_ref, upsert_source_event


def _selected_search_hit(
    database_url: str,
    *,
    email: str,
    title: str = "Principal Consultant",
    company: str = "Reviewable Outreach Advisors",
    full_name: str = "Reviewable Outreach Person",
) -> None:
    upsert_source_event(
        database_url,
        SourceEventIn(
            source_name="next_up",
            source_event_type="curated_contact",
            source_event_key=f"test-next-up:{email}",
            source_payload={
                "email": email,
                "full_name": full_name,
                "title": title,
                "company": company,
            },
            source_posture=SourcePosture.CURATED_EXPORT,
            provenance_status="test_curated_export",
            trust_role="identity/context seed",
        ),
    )
    materialize_exact_emails(database_url)


def _relationship_evidence(
    database_url: str,
    *,
    email: str,
    message_id: str = "1",
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
            "from_name": "Reviewable Outreach Person",
            "sent_at": "2026-05-01T12:00:00Z",
            "subject": "Potential collaboration",
            "snippet": "A relationship-backed note the model may cite.",
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
    materialize_msgvault_correspondence(database_url)
    return str(evidence_ref_id)


def _run_cli(monkeypatch, capsys, *args: str) -> dict:
    monkeypatch.setattr(sys, "argv", ["relationship-substrate", *args])
    assert main() == 0
    return json.loads(capsys.readouterr().out)


def test_prepare_outreach_proposal_packet_combines_search_dossier_intelligence_and_research(
    database_url,
):
    run_migrations(database_url)
    run_id = uuid4().hex
    email = f"outreach-{run_id}@example.com"
    _selected_search_hit(database_url, email=email)
    evidence_ref_id = _relationship_evidence(database_url, email=email)
    research_context = {
        "sources": [
            {
                "id": "company-news",
                "url": "https://example.com/company-news",
                "title": "Company launches a new advisory practice",
                "provenance": "external_research",
            }
        ],
        "notes": [{"source_id": "company-news", "text": "Recent context for the model."}],
    }

    packet = prepare_outreach_proposal_packet(
        database_url,
        emails=[email],
        research_context=research_context,
        evidence_limit=5,
    )

    assert packet["proposal_stage"] == "research_backed_outreach"
    assert packet["research_context"] == research_context
    assert packet["count"] == 1
    person_packet = packet["people"][0]
    assert person_packet["search_hit"]["email"] == email
    assert person_packet["dossier"]["person"]["primary_email"] == email
    assert person_packet["relationship_intelligence"]["person"]["primary_email"] == email
    assert person_packet["relationship_intelligence"]["evidence"][0]["id"] == evidence_ref_id
    assert packet["model_contract"]["owner"] == "model"
    assert "priority" in packet["model_contract"]["required_fields"]
    assert "fit score" in packet["model_contract"]["code_must_not"]


def test_validate_outreach_proposal_accepts_model_content_without_rewriting_it(database_url):
    run_migrations(database_url)
    email = f"validate-outreach-{uuid4().hex}@example.com"
    _selected_search_hit(database_url, email=email)
    evidence_ref_id = _relationship_evidence(database_url, email=email)
    packet = prepare_outreach_proposal_packet(
        database_url,
        emails=[email],
        research_context={"sources": [{"id": "research-1", "url": "https://example.com/source"}]},
    )
    proposal = {
        "person_email": email,
        "priority": "model-selected priority label",
        "relevance_rationale": "The model owns this qualitative relevance rationale.",
        "best_angle": "The model owns this angle.",
        "draft_email": {
            "subject": "Model-written subject",
            "body": "Model-written body with no code rewrite.",
        },
        "next_action": "Model-recommended next action.",
        "cited_evidence_refs": [evidence_ref_id],
        "cited_research_refs": ["research-1"],
    }

    validated = validate_outreach_proposal(packet, proposal)

    assert validated == proposal


def test_validate_outreach_proposal_rejects_uncited_or_unknown_refs(database_url):
    run_migrations(database_url)
    email = f"invalid-outreach-{uuid4().hex}@example.com"
    _selected_search_hit(database_url, email=email)
    _relationship_evidence(database_url, email=email)
    packet = prepare_outreach_proposal_packet(
        database_url,
        emails=[email],
        research_context={"sources": [{"id": "known-research", "url": "https://example.com/source"}]},
    )

    with pytest.raises(ValueError, match="cited_evidence_refs"):
        validate_outreach_proposal(
            packet,
            {
                "person_email": email,
                "priority": "model-selected priority label",
                "relevance_rationale": "Model rationale.",
                "best_angle": "Model angle.",
                "draft_email": {"subject": "Subject", "body": "Body"},
                "next_action": "Next action.",
                "cited_evidence_refs": ["missing-evidence"],
                "cited_research_refs": ["known-research"],
            },
        )

    with pytest.raises(ValueError, match="cited_research_refs"):
        validate_outreach_proposal(
            packet,
            {
                "person_email": email,
                "priority": "model-selected priority label",
                "relevance_rationale": "Model rationale.",
                "best_angle": "Model angle.",
                "draft_email": {"subject": "Subject", "body": "Body"},
                "next_action": "Next action.",
                "cited_evidence_refs": [],
                "cited_research_refs": ["missing-research"],
            },
        )


def test_prepare_outreach_proposal_cli_reads_research_context(database_url, tmp_path, monkeypatch, capsys):
    run_migrations(database_url)
    email = f"cli-outreach-{uuid4().hex}@example.com"
    _selected_search_hit(database_url, email=email)
    research_path = tmp_path / "research.json"
    research_path.write_text(
        json.dumps({"sources": [{"id": "cli-research", "url": "https://example.com/cli"}]}),
        encoding="utf-8",
    )

    packet = _run_cli(
        monkeypatch,
        capsys,
        "--database-url",
        database_url,
        "prepare-outreach-proposal",
        "--email",
        email,
        "--research-context",
        str(research_path),
        "--evidence-limit",
        "3",
    )

    assert packet["people"][0]["search_hit"]["email"] == email
    assert packet["research_context"]["sources"][0]["id"] == "cli-research"


def test_prepare_history_backed_outreach_packet_uses_history_search_and_tone_state(
    database_url,
):
    run_migrations(database_url)
    run_id = uuid4().hex
    domain = f"history-outreach-{run_id}.example"
    email = f"partner@{domain}"
    evidence_ref_id = _relationship_evidence(database_url, email=email)
    upsert_organization_enrichment(
        database_url,
        company_name=domain,
        company_type="small_consulting_firm",
        employee_count_min=12,
        employee_count_max=12,
        employee_count_label="test sourced team count",
        consultant_count_estimate=12,
        source_name="test_fixture",
        provenance_status="test",
    )

    packet = prepare_history_backed_outreach_proposal_packet(
        database_url,
        actual_employee_count_min=12,
        actual_employee_count_max=12,
        consultant_count_min=12,
        consultant_count_max=12,
        limit=1000,
        research_context={"sources": [{"id": "current-news", "url": "https://example.com/news"}]},
        evidence_limit=3,
    )

    person_packet = next(person for person in packet["people"] if person["email"] == email)
    assert packet["proposal_stage"] == "history_backed_research_outreach"
    assert person_packet["search_hit"]["domain"] == domain
    assert person_packet["relationship_intelligence"]["evidence"][0]["id"] == evidence_ref_id
    assert person_packet["relationship_tone_tenor"]["dossier_counts"]["evidence_refs"] >= 1
    assert packet["relationship_tone_model_contract"]["owner"] == "model"

    validated = validate_outreach_proposal(
        packet,
        {
            "person_email": email,
            "priority": "model-owned",
            "relevance_rationale": "Model rationale.",
            "best_angle": "Model angle.",
            "draft_email": {"subject": "Subject", "body": "Body"},
            "next_action": "Model action.",
            "cited_evidence_refs": [evidence_ref_id],
            "cited_research_refs": ["current-news"],
        },
    )
    assert validated["person_email"] == email


def test_prepare_history_backed_outreach_cli_reads_research_context(
    database_url,
    tmp_path,
    monkeypatch,
    capsys,
):
    run_migrations(database_url)
    run_id = uuid4().hex
    domain = f"history-cli-{run_id}.example"
    email = f"partner@{domain}"
    _relationship_evidence(database_url, email=email)
    upsert_organization_enrichment(
        database_url,
        company_name=domain,
        company_type="small_consulting_firm",
        employee_count_min=11,
        employee_count_max=11,
        consultant_count_estimate=11,
        source_name="test_fixture",
        provenance_status="test",
    )
    research_path = tmp_path / "research.json"
    research_path.write_text(
        json.dumps({"sources": [{"id": "cli-current-news", "url": "https://example.com/current"}]}),
        encoding="utf-8",
    )

    packet = _run_cli(
        monkeypatch,
        capsys,
        "--database-url",
        database_url,
        "prepare-history-backed-outreach-proposal",
        "--actual-employee-count-min",
        "11",
        "--actual-employee-count-max",
        "11",
        "--consultant-count-min",
        "11",
        "--consultant-count-max",
        "11",
        "--limit",
        "1000",
        "--research-context",
        str(research_path),
        "--evidence-limit",
        "3",
    )

    assert packet["research_context"]["sources"][0]["id"] == "cli-current-news"
    assert any(person["email"] == email for person in packet["people"])
