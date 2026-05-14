from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from relationship_substrate.dossiers import get_person_dossier
from relationship_substrate.relationship_intelligence import (
    prepare_relationship_intelligence_packet,
    prepare_relationship_tone_tenor_analysis_packet,
)
from relationship_substrate.search import search_history_backed_people, search_people


class OutreachProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person_email: str = Field(min_length=1)
    priority: str = Field(min_length=1)
    relevance_rationale: str = Field(min_length=1)
    best_angle: str = Field(min_length=1)
    draft_email: dict[str, Any] = Field(min_length=1)
    next_action: str = Field(min_length=1)
    cited_evidence_refs: list[str] = Field(default_factory=list)
    cited_research_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _requires_at_least_one_citation(self) -> "OutreachProposal":
        if not self.cited_evidence_refs and not self.cited_research_refs:
            raise ValueError("outreach proposal must cite evidence or research refs")
        return self


def _network_search_hit_for_email(database_url: str, *, email: str) -> dict[str, Any]:
    normalized_email = email.strip().lower()
    for hit in search_people(database_url, role_keywords=[], limit=10000):
        if hit["email"] == normalized_email:
            return hit
    raise ValueError(f"network-search hit not found for email: {normalized_email}")


def _model_contract() -> dict[str, Any]:
    return {
        "owner": "model",
        "purpose": "Produce reviewable outreach proposals only; do not send messages or commit relationship state.",
        "required_fields": [
            "person_email",
            "priority",
            "relevance_rationale",
            "best_angle",
            "draft_email",
            "next_action",
            "cited_evidence_refs",
            "cited_research_refs",
        ],
        "code_owns": [
            "search hit assembly",
            "relationship dossier assembly",
            "relationship intelligence evidence assembly",
            "external research provenance preservation",
            "schema and citation validation",
            "CLI JSON output",
        ],
        "model_owns": [
            "qualitative relevance judgment",
            "priority label",
            "tone and angle",
            "email copy",
            "next-action recommendation",
        ],
        "code_must_not": "No deterministic tone classifier, keyword fit score, hardcoded outreach copy, or hidden fit score.",
        "citation_requirement": (
            "Every cited_evidence_refs value must match a supplied relationship evidence ref id. "
            "Every cited_research_refs value must match a supplied research source id or URL."
        ),
    }


def prepare_outreach_proposal_packet(
    database_url: str,
    *,
    emails: list[str],
    research_context: Any | None = None,
    evidence_limit: int = 10,
) -> dict[str, Any]:
    people: list[dict[str, Any]] = []
    for email in emails:
        normalized_email = email.strip().lower()
        people.append(
            {
                "email": normalized_email,
                "search_hit": _network_search_hit_for_email(database_url, email=normalized_email),
                "dossier": get_person_dossier(database_url, email=normalized_email),
                "relationship_intelligence": prepare_relationship_intelligence_packet(
                    database_url,
                    email=normalized_email,
                    evidence_limit=evidence_limit,
                ),
            }
        )
    return {
        "proposal_stage": "research_backed_outreach",
        "count": len(people),
        "people": people,
        "research_context": research_context if research_context is not None else {},
        "model_contract": _model_contract(),
    }


def prepare_history_backed_outreach_proposal_packet(
    database_url: str,
    *,
    actual_employee_count_min: int | None = None,
    actual_employee_count_max: int | None = None,
    consultant_count_min: int | None = None,
    consultant_count_max: int | None = None,
    limit: int = 10,
    research_context: Any | None = None,
    evidence_limit: int = 10,
    prior_state_limit: int = 3,
) -> dict[str, Any]:
    search_hits = search_history_backed_people(
        database_url,
        actual_employee_count_min=actual_employee_count_min,
        actual_employee_count_max=actual_employee_count_max,
        consultant_count_min=consultant_count_min,
        consultant_count_max=consultant_count_max,
        limit=limit,
    )
    emails = [hit["email"] for hit in search_hits]
    tone_packet = prepare_relationship_tone_tenor_analysis_packet(
        database_url,
        emails=emails,
        evidence_limit=evidence_limit,
        prior_state_limit=prior_state_limit,
    )
    tone_by_email = {person["email"]: person for person in tone_packet["people"]}
    people = [
        {
            "email": hit["email"],
            "search_hit": hit,
            "relationship_intelligence": tone_by_email[hit["email"]]["relationship_intelligence"],
            "relationship_tone_tenor": {
                "person": tone_by_email[hit["email"]]["person"],
                "relationship_edge": tone_by_email[hit["email"]]["relationship_edge"],
                "contact_channels": tone_by_email[hit["email"]]["contact_channels"],
                "dossier_counts": tone_by_email[hit["email"]]["dossier_counts"],
                "prior_tone_tenor_states": tone_by_email[hit["email"]]["prior_tone_tenor_states"],
            },
        }
        for hit in search_hits
    ]
    return {
        "proposal_stage": "history_backed_research_outreach",
        "query": {
            "actual_employee_count_min": actual_employee_count_min,
            "actual_employee_count_max": actual_employee_count_max,
            "consultant_count_min": consultant_count_min,
            "consultant_count_max": consultant_count_max,
            "limit": limit,
        },
        "count": len(people),
        "people": people,
        "research_context": research_context if research_context is not None else {},
        "model_contract": _model_contract(),
        "relationship_tone_model_contract": tone_packet["model_contract"],
    }


def _available_evidence_refs(packet: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for person_packet in packet.get("people", []):
        relationship_intelligence = person_packet.get("relationship_intelligence") or {}
        for evidence in relationship_intelligence.get("evidence", []):
            ref_id = str(evidence.get("id") or "").strip()
            if ref_id:
                refs.add(ref_id)
            ref_type = str(evidence.get("ref_type") or "").strip()
            ref_value = str(evidence.get("ref_value") or "").strip()
            if ref_type and ref_value:
                refs.add(f"{ref_type}:{ref_value}")
        dossier = person_packet.get("dossier") or {}
        for evidence_ref in dossier.get("evidence_refs", []):
            ref_id = str(evidence_ref.get("id") or "").strip()
            if ref_id:
                refs.add(ref_id)
            ref_type = str(evidence_ref.get("ref_type") or "").strip()
            ref_value = str(evidence_ref.get("ref_value") or "").strip()
            if ref_type and ref_value:
                refs.add(f"{ref_type}:{ref_value}")
    return refs


def _research_refs(value: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, dict):
        for key in ("id", "url", "source_url"):
            ref = str(value.get(key) or "").strip()
            if ref:
                refs.add(ref)
        for child in value.values():
            refs.update(_research_refs(child))
    elif isinstance(value, list):
        for child in value:
            refs.update(_research_refs(child))
    return refs


def validate_outreach_proposal(
    packet: dict[str, Any],
    proposal: dict[str, Any],
) -> dict[str, Any]:
    try:
        parsed = OutreachProposal.model_validate(proposal)
    except ValueError as exc:
        raise ValueError(f"invalid outreach proposal: {exc}") from exc

    packet_emails = {str(person.get("email") or "").strip().lower() for person in packet.get("people", [])}
    if parsed.person_email.strip().lower() not in packet_emails:
        raise ValueError("person_email is not present in the outreach proposal packet")

    evidence_refs = _available_evidence_refs(packet)
    missing_evidence_refs = [ref for ref in parsed.cited_evidence_refs if ref not in evidence_refs]
    if missing_evidence_refs:
        raise ValueError(f"cited_evidence_refs not supplied by packet: {missing_evidence_refs}")

    research_refs = _research_refs(packet.get("research_context"))
    missing_research_refs = [ref for ref in parsed.cited_research_refs if ref not in research_refs]
    if missing_research_refs:
        raise ValueError(f"cited_research_refs not supplied by packet: {missing_research_refs}")

    return parsed.model_dump(mode="json")
