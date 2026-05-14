from __future__ import annotations

from uuid import uuid4

import pytest

from relationship_substrate.contracts import SourceEventIn, SourcePosture
from relationship_substrate.db import run_migrations
from relationship_substrate.dossiers import get_person_dossier
from relationship_substrate.materialize import materialize_msgvault_correspondence
from relationship_substrate.relationship_intelligence import (
    prepare_relationship_intelligence_packet,
    persist_relationship_state,
)
from relationship_substrate.repositories import upsert_evidence_ref, upsert_source_event


def _insert_correspondence_evidence(
    database_url: str,
    *,
    email: str,
    message_id: str,
    subject: str,
    snippet: str,
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
            "from_name": "Tone Person",
            "sent_at": "2026-05-01T12:00:00Z",
            "subject": subject,
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


def test_prepare_relationship_intelligence_packet_exposes_evidence_without_interpreting_tone(
    database_url,
):
    run_migrations(database_url)
    email = f"tone-{uuid4().hex}@example.com"
    _insert_correspondence_evidence(
        database_url,
        email=email,
        message_id="1",
        subject="Project check-in",
        snippet="Thanks for the thoughtful notes; let's keep this moving next week.",
    )
    materialize_msgvault_correspondence(database_url)

    packet = prepare_relationship_intelligence_packet(database_url, email=email)

    assert packet["person"]["primary_email"] == email
    assert packet["mechanical_relationship_facts"]["interaction_count"] == 1
    assert packet["mechanical_relationship_facts"]["email_message_count"] == 1
    assert packet["evidence"][0]["ref_type"] == "msgvault_message"
    assert packet["evidence"][0]["subject"] == "Project check-in"
    assert "thoughtful notes" in packet["evidence"][0]["snippet"]
    assert "tone" not in packet["mechanical_relationship_facts"]
    assert "tenor" not in packet["mechanical_relationship_facts"]


def test_persist_relationship_state_rejects_model_proposal_without_evidence(database_url):
    run_migrations(database_url)
    email = f"no-evidence-{uuid4().hex}@example.com"
    _insert_correspondence_evidence(
        database_url,
        email=email,
        message_id="1",
        subject="Evidence seed",
        snippet="A source message exists for the person.",
    )
    materialize_msgvault_correspondence(database_url)

    with pytest.raises(ValueError, match="evidence_refs"):
        persist_relationship_state(
            database_url,
            email=email,
            proposal={
                "state_kind": "relationship_tone_tenor",
                "summary": "Model-owned tone summary.",
                "rationale": "Model-owned rationale.",
                "evidence_refs": [],
            },
        )


def test_persist_relationship_state_requires_evidence_refs_for_that_person(database_url):
    run_migrations(database_url)
    email = f"linked-evidence-{uuid4().hex}@example.com"
    other_email = f"other-evidence-{uuid4().hex}@example.com"
    _insert_correspondence_evidence(
        database_url,
        email=email,
        message_id="1",
        subject="Primary evidence",
        snippet="A source message for the primary person.",
    )
    other_ref_id = _insert_correspondence_evidence(
        database_url,
        email=other_email,
        message_id="1",
        subject="Other evidence",
        snippet="A source message for someone else.",
    )
    materialize_msgvault_correspondence(database_url)

    with pytest.raises(ValueError, match="not linked"):
        persist_relationship_state(
            database_url,
            email=email,
            proposal={
                "state_kind": "relationship_tone_tenor",
                "summary": "Model-owned tone summary.",
                "rationale": "Model-owned rationale.",
                "evidence_refs": [{"id": other_ref_id}],
            },
        )


def test_persisted_relationship_state_is_evidence_backed_and_visible_in_dossier(database_url):
    run_migrations(database_url)
    email = f"visible-state-{uuid4().hex}@example.com"
    evidence_ref_id = _insert_correspondence_evidence(
        database_url,
        email=email,
        message_id="1",
        subject="Warm intro follow-up",
        snippet="The model will own interpretation of this excerpt.",
    )
    materialize_msgvault_correspondence(database_url)

    state = persist_relationship_state(
        database_url,
        email=email,
        proposal={
            "state_kind": "relationship_tone_tenor",
            "summary": "Model-proposed tone/tenor summary.",
            "rationale": "Model cites the supplied evidence and owns the interpretation.",
            "evidence_refs": [{"id": evidence_ref_id}],
        },
    )
    dossier = get_person_dossier(database_url, email=email)

    assert state["state_kind"] == "relationship_tone_tenor"
    assert state["evidence_refs"] == [{"id": evidence_ref_id}]
    assert dossier["relationship_states"][0]["id"] == state["id"]
    assert dossier["relationship_states"][0]["summary"] == "Model-proposed tone/tenor summary."
    assert dossier["relationship_states"][0]["evidence_refs"] == [{"id": evidence_ref_id}]
