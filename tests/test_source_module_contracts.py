from __future__ import annotations

import json
from pathlib import Path

from relationship_substrate.contracts import (
    AffiliationRecord,
    InteractionRecord,
    ListSubjectNotesIn,
    ListSubjectNotesOut,
    OrganizationRecord,
    PersonRecord,
    RecordSubjectNoteIn,
    RelationshipSearchHit,
    SubjectNoteRecord,
    ToolActionContract,
)


ROOT = Path(__file__).resolve().parents[1]


def test_source_module_fixture_validates_public_relationship_records():
    fixture = json.loads(
        (ROOT / "examples/source_module/relationship_substrate_records.json").read_text()
    )
    records = fixture["records"]

    person = PersonRecord.model_validate(records["person"])
    organization = OrganizationRecord.model_validate(records["organization"])
    affiliation = AffiliationRecord.model_validate(records["affiliation"])
    interaction = InteractionRecord.model_validate(records["interaction"])
    subject_note = SubjectNoteRecord.model_validate(records["subject_note"])

    hit = RelationshipSearchHit(
        person=person,
        organization=organization,
        affiliations=[affiliation],
        interactions=[interaction],
        subject_note_context=[subject_note],
        evidence_refs=["fixture:message:ada-001"],
    )

    assert hit.subject_note_context[0].note_kind == "context_fit"


def test_subject_note_actions_use_canonical_source_owned_contract_names():
    fixture = json.loads(
        (ROOT / "examples/source_module/relationship_substrate_records.json").read_text()
    )

    record_action = fixture["record_subject_note"]
    list_action = fixture["list_subject_notes"]

    RecordSubjectNoteIn.model_validate(record_action["input"])
    ListSubjectNotesIn.model_validate(list_action["input"])
    output = ListSubjectNotesOut.model_validate(list_action["output"])

    assert record_action["effect_type"] == "source_owned_correction_write"
    assert record_action["requires_external_action_approval"] is False
    assert output.subject_note_context[0].note.startswith("Use this contact")


def test_source_module_fixture_declares_public_tool_action_names():
    fixture = json.loads(
        (ROOT / "examples/source_module/relationship_substrate_records.json").read_text()
    )
    actions = {
        action.tool_ref: action
        for action in (
            ToolActionContract.model_validate(item)
            for item in fixture["tool_actions"]
        )
    }

    assert set(actions) == {
        "tool.relationship_substrate.operating_picture",
        "tool.relationship_substrate.list_subject_notes",
        "tool.relationship_substrate.search_small_consulting_firm_contacts",
        "tool.relationship_substrate.search_history_backed_people",
        "tool.relationship_substrate.record_subject_note",
    }
    assert (
        actions["tool.relationship_substrate.record_subject_note"].effect_type
        == "source_owned_correction_write"
    )
    assert actions[
        "tool.relationship_substrate.search_small_consulting_firm_contacts"
    ].backing_tool_refs == ["tool.relationship_substrate.search_history_backed_people"]
    for action in actions.values():
        assert "subject_note_context_demote_explain_not_hide" in action.answer_contract_policy
        assert action.requires_external_action_approval is False
