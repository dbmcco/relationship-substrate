from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from relationship_substrate.contracts import SourceEventIn, SourcePosture
from relationship_substrate.db import run_migrations
from relationship_substrate.dossiers import get_person_dossier
from relationship_substrate.materialize import materialize_msgvault_correspondence
from relationship_substrate.relationship_intelligence import (
    prepare_relationship_tone_tenor_analysis_packet,
    prepare_relationship_intelligence_packet,
    propose_relationship_state_live,
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


def test_prepare_relationship_tone_tenor_analysis_packet_batches_people_with_prior_tone_states(database_url):
    run_migrations(database_url)
    run_id = uuid4().hex
    email = f"tone-packet-{run_id}@example.com"
    evidence_ref_id = _insert_correspondence_evidence(
        database_url,
        email=email,
        message_id="1",
        subject="Follow-up note",
        snippet="Appreciate your thoughtful feedback and direct communication.",
    )
    materialize_msgvault_correspondence(database_url)
    persist_relationship_state(
        database_url,
        email=email,
        proposal={
            "state_kind": "relationship_tone_tenor",
            "summary": "Tone state that should be included.",
            "rationale": "Evidence-backed model interpretation.",
            "evidence_refs": [{"id": evidence_ref_id}],
        },
    )
    persist_relationship_state(
        database_url,
        email=email,
        proposal={
            "state_kind": "relationship_next_action",
            "summary": "Different state kind should not be included.",
            "rationale": "Not part of tone/tenor history.",
            "evidence_refs": [{"id": evidence_ref_id}],
        },
    )

    packet = prepare_relationship_tone_tenor_analysis_packet(
        database_url,
        emails=[email],
        evidence_limit=5,
        prior_state_limit=1,
    )

    assert packet["analysis_stage"] == "relationship_tone_tenor"
    assert packet["count"] == 1
    assert packet["model_contract"]["owner"] == "model"
    assert "deterministic tone classifier" in packet["model_contract"]["code_must_not"]
    person_packet = packet["people"][0]
    assert person_packet["email"] == email
    assert person_packet["relationship_intelligence"]["person"]["primary_email"] == email
    assert person_packet["relationship_intelligence"]["evidence"][0]["id"] == evidence_ref_id
    assert len(person_packet["prior_tone_tenor_states"]) == 1
    assert person_packet["prior_tone_tenor_states"][0]["state_kind"] == "relationship_tone_tenor"


def _write_registry(path: Path) -> None:
    path.write_text(
        """
[credentials.rel_sub_openai]
provider = "openai"
source = "env"
env_var = "REL_SUB_TEST_API_KEY"

[provider_credential_defaults]
openai = "rel_sub_openai"

[provider_surfaces.rel_sub_openai_surface]
provider = "openai"
base_url = "https://models.example.test/v1"
api_key_env = "REL_SUB_TEST_API_KEY"
start_timeout_seconds = 12

[service_credential_assignments."relationship-substrate"]
openai = "rel_sub_openai"

[model_routes."relationship_substrate.relationship_state_proposal"]
owner = "relationship-substrate"
surface = "rel_sub_openai_surface"
provider = "openai"
model = "gpt-test"
max_tokens_default = 700
""".strip()
        + "\n",
        encoding="utf-8",
    )


def test_propose_relationship_state_live_records_proposal_and_journal(database_url, tmp_path, monkeypatch):
    run_migrations(database_url)
    email = f"live-model-{uuid4().hex}@example.com"
    evidence_ref_id = _insert_correspondence_evidence(
        database_url,
        email=email,
        message_id="live-1",
        subject="Live model evidence",
        snippet="Evidence used by the model proposal path.",
    )
    materialize_msgvault_correspondence(database_url)

    registry_path = tmp_path / "cognition-presets.toml"
    _write_registry(registry_path)
    monkeypatch.setenv("REL_SUB_TEST_API_KEY", "test-secret")
    captured: dict[str, object] = {}

    def fake_post_json(*, url: str, headers: dict[str, str], payload: dict[str, object], timeout_seconds: float):
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        captured["timeout_seconds"] = timeout_seconds
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            "{"
                            '"state_kind":"relationship_tone_tenor",'
                            '"summary":"Model-owned summary from live call.",'
                            '"rationale":"Model rationale grounded in provided evidence.",'
                            f'"evidence_refs":[{{"id":"{evidence_ref_id}"}}]'
                            "}"
                        )
                    }
                }
            ]
        }

    result = propose_relationship_state_live(
        database_url,
        email=email,
        route_key="relationship_substrate.relationship_state_proposal",
        registry_path=str(registry_path),
        post_json=fake_post_json,
    )

    assert result["relationship_state"]["state_kind"] == "relationship_tone_tenor"
    assert result["relationship_state"]["evidence_refs"] == [{"id": evidence_ref_id}]
    assert result["proposal_event"]["source_event_type"] == "relationship_state_model_proposal"
    assert result["journal_entry"]["change_kind"] == "model_proposal_committed"
    assert captured["url"] == "https://models.example.test/v1/chat/completions"
    assert captured["headers"] == {"Authorization": "Bearer test-secret", "Content-Type": "application/json"}
    assert captured["timeout_seconds"] == 12.0

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT source_event_type, source_posture, provenance_status, trust_role, source_payload
                FROM relationship_substrate.source_event
                WHERE id = %s
                """,
                (result["proposal_event"]["source_event_id"],),
            )
            proposal_row = cur.fetchone()
            cur.execute(
                """
                SELECT entity_type, entity_id, change_kind, summary, evidence_refs
                FROM relationship_substrate.state_journal_entry
                WHERE id = %s
                """,
                (result["journal_entry"]["id"],),
            )
            journal_row = cur.fetchone()

    assert proposal_row is not None
    assert proposal_row[0] == "relationship_state_model_proposal"
    assert proposal_row[1] == "derived_interpretation"
    assert proposal_row[2] == "model_proposal"
    assert proposal_row[3] == "model-authored interpreted relationship_state proposal"
    assert proposal_row[4]["model_route"]["route_key"] == "relationship_substrate.relationship_state_proposal"
    assert proposal_row[4]["proposal"]["summary"] == "Model-owned summary from live call."
    assert journal_row is not None
    assert journal_row[0] == "relationship_state"
    assert str(journal_row[1]) == result["relationship_state"]["id"]
    assert journal_row[2] == "model_proposal_committed"
    assert journal_row[3] == "Model-owned summary from live call."
    assert any(ref.get("ref_type") == "relationship_state_proposal" for ref in journal_row[4])


def test_propose_relationship_state_live_fails_when_registry_credential_is_missing(
    database_url,
    tmp_path,
    monkeypatch,
):
    run_migrations(database_url)
    email = f"live-model-missing-key-{uuid4().hex}@example.com"
    _insert_correspondence_evidence(
        database_url,
        email=email,
        message_id="live-2",
        subject="Missing credential evidence",
        snippet="Evidence for missing credential test.",
    )
    materialize_msgvault_correspondence(database_url)
    registry_path = tmp_path / "cognition-presets.toml"
    _write_registry(registry_path)
    monkeypatch.delenv("REL_SUB_TEST_API_KEY", raising=False)

    with pytest.raises(ValueError, match="missing configured credential env var"):
        propose_relationship_state_live(
            database_url,
            email=email,
            route_key="relationship_substrate.relationship_state_proposal",
            registry_path=str(registry_path),
        )
