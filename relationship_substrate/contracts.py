from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SourcePosture(StrEnum):
    DIRECT_INTERACTION = "direct_interaction"
    CURATED_EXPORT = "curated_export"
    ENRICHMENT = "enrichment"
    DERIVED_INTERPRETATION = "derived_interpretation"


class SourceEventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_name: str = Field(min_length=1)
    source_event_type: str = Field(min_length=1)
    source_event_key: str = Field(min_length=1)
    source_payload: dict[str, Any]
    source_posture: SourcePosture
    provenance_status: str = Field(min_length=1)
    trust_role: str = Field(min_length=1)


class RelationshipRecordKind(StrEnum):
    PERSON = "person"
    ORGANIZATION = "organization"
    AFFILIATION = "affiliation"
    INTERACTION = "interaction"
    SUBJECT_NOTE = "subject_note"


class SubjectType(StrEnum):
    PERSON = "person"
    ORGANIZATION = "organization"


class PersonRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_kind: Literal[RelationshipRecordKind.PERSON] = RelationshipRecordKind.PERSON
    id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    primary_email: str | None = None
    source_posture: SourcePosture
    provenance_status: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class OrganizationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_kind: Literal[RelationshipRecordKind.ORGANIZATION] = RelationshipRecordKind.ORGANIZATION
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    domain: str | None = None
    source_posture: SourcePosture
    provenance_status: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AffiliationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_kind: Literal[RelationshipRecordKind.AFFILIATION] = RelationshipRecordKind.AFFILIATION
    id: str = Field(min_length=1)
    person_id: str = Field(min_length=1)
    organization_id: str = Field(min_length=1)
    role_or_title: str | None = None
    source_posture: SourcePosture
    provenance_status: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class InteractionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_kind: Literal[RelationshipRecordKind.INTERACTION] = RelationshipRecordKind.INTERACTION
    id: str = Field(min_length=1)
    person_id: str = Field(min_length=1)
    interaction_type: str = Field(min_length=1)
    occurred_at: str | None = None
    subject: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SubjectNoteRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_kind: Literal[RelationshipRecordKind.SUBJECT_NOTE] = RelationshipRecordKind.SUBJECT_NOTE
    id: str = Field(min_length=1)
    subject_type: SubjectType
    subject_id: str = Field(min_length=1)
    note_kind: str = Field(min_length=1)
    note: str = Field(min_length=1)
    applies_to: str | None = None
    source: str = Field(default="user_correction", min_length=1)
    source_ref: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    supersedes_id: str | None = None
    created_at: str | None = None


class RecordSubjectNoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_type: SubjectType
    subject_ref: str = Field(min_length=1)
    note_kind: str = Field(min_length=1)
    note: str = Field(min_length=1)
    applies_to: str | None = None
    source: str = Field(default="user_correction", min_length=1)
    source_ref: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    supersedes_id: str | None = None


class ListSubjectNotesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_type: SubjectType | None = None
    subject_ref: str | None = None
    note_kind: str | None = None
    limit: int = Field(default=50, ge=1, le=200)


class ListSubjectNotesOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int = Field(ge=0)
    subject_note_context: list[SubjectNoteRecord] = Field(default_factory=list)


class RelationshipSearchHit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person: PersonRecord
    organization: OrganizationRecord | None = None
    affiliations: list[AffiliationRecord] = Field(default_factory=list)
    interactions: list[InteractionRecord] = Field(default_factory=list)
    subject_note_context: list[SubjectNoteRecord] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class ToolActionContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    tool_ref: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    effect_type: Literal["read_only", "source_owned_correction_write", "external_side_effect"]
    backing_tool_refs: list[str] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
    optional_fields: list[str] = Field(default_factory=list)
    answer_contract_policy: list[str] = Field(default_factory=list)
    requires_external_action_approval: bool = False
