from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from relationship_substrate.outreach import prepare_history_backed_outreach_proposal_packet


ASK_NETWORK_CONTRACT_VERSION = 1


class AskNetworkRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person_email: str = Field(min_length=1)
    priority: str = Field(min_length=1)
    goal_fit_rationale: str = Field(min_length=1)
    relationship_rationale: str = Field(min_length=1)
    relationship_risk_or_caution: str = Field(min_length=1)
    best_angle: str = Field(min_length=1)
    next_action: str = Field(min_length=1)
    draft_email: dict[str, Any] = Field(min_length=1)
    cited_evidence_refs: list[str] = Field(default_factory=list)
    cited_research_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _requires_at_least_one_citation(self) -> "AskNetworkRecommendation":
        if not self.cited_evidence_refs and not self.cited_research_refs:
            raise ValueError("ask-network recommendation must cite evidence or research refs")
        return self


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


def _evidence_ref_ids(relationship_intelligence: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for evidence in relationship_intelligence.get("evidence", []):
        ref_id = str(evidence.get("id") or "").strip()
        if ref_id:
            refs.append(ref_id)
    return refs


def _available_evidence_refs(packet: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    for person in packet.get("people", []):
        for ref in (person.get("model_inputs") or {}).get("candidate_evidence_refs", []):
            normalized_ref = str(ref or "").strip()
            if normalized_ref:
                refs.add(normalized_ref)
        relationship_intelligence = person.get("relationship_intelligence") or {}
        for evidence in relationship_intelligence.get("evidence", []):
            ref_id = str(evidence.get("id") or "").strip()
            if ref_id:
                refs.add(ref_id)
            ref_type = str(evidence.get("ref_type") or "").strip()
            ref_value = str(evidence.get("ref_value") or "").strip()
            if ref_type and ref_value:
                refs.add(f"{ref_type}:{ref_value}")
    return refs


def _organization_context(search_hit: dict[str, Any]) -> dict[str, Any]:
    enrichment = search_hit.get("organization_enrichment") or {}
    return {
        "name": search_hit.get("company"),
        "domain": search_hit.get("domain"),
        "company_type": enrichment.get("company_type"),
        "actual_employee_count_min": enrichment.get("employee_count_min"),
        "actual_employee_count_max": enrichment.get("employee_count_max"),
        "employee_count_label": enrichment.get("employee_count_label"),
        "consultant_count_estimate": enrichment.get("consultant_count_estimate"),
        "source_name": enrichment.get("source_name"),
        "source_url": enrichment.get("source_url"),
        "provenance_status": enrichment.get("provenance_status"),
    }


def _evidence_summary(person_packet: dict[str, Any]) -> dict[str, Any]:
    relationship_intelligence = person_packet.get("relationship_intelligence") or {}
    mechanical_facts = relationship_intelligence.get("mechanical_relationship_facts") or {}
    relationship_tone_tenor = person_packet.get("relationship_tone_tenor") or {}
    search_hit = person_packet.get("search_hit") or {}
    relationship = search_hit.get("relationship") or {}
    evidence_refs = _evidence_ref_ids(relationship_intelligence)
    return {
        "evidence_ref_count": len(evidence_refs),
        "latest_interaction_at": mechanical_facts.get("last_interaction_at")
        or relationship.get("last_interaction_at"),
        "email_message_count": int(
            mechanical_facts.get("email_message_count")
            or relationship.get("email_interaction_count")
            or 0
        ),
        "calendar_interaction_count": int(
            mechanical_facts.get("calendar_interaction_count")
            or relationship.get("calendar_interaction_count")
            or 0
        ),
        "has_direct_relationship_evidence": bool(evidence_refs),
        "has_prior_tone_state": bool(relationship_tone_tenor.get("prior_tone_tenor_states") or []),
        "has_organization_enrichment": bool(search_hit.get("organization_enrichment")),
    }


def _packet_readiness(
    *,
    evidence_summary: dict[str, Any],
    research_refs: set[str],
    refresh_actions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    refresh_actions = refresh_actions or []
    missing: list[str] = []
    if not evidence_summary["has_direct_relationship_evidence"]:
        missing.append("relationship_evidence")
    if not evidence_summary["has_organization_enrichment"]:
        missing.append("organization_enrichment")
    if not evidence_summary["has_prior_tone_state"]:
        missing.append("relationship_tone_tenor_state")
    if not research_refs:
        missing.append("research_context")

    ready_for_model_ranking = (
        evidence_summary["has_direct_relationship_evidence"]
        and evidence_summary["has_organization_enrichment"]
    )
    ready_for_outreach_drafting = (
        ready_for_model_ranking
        and evidence_summary["has_prior_tone_state"]
        and bool(research_refs)
    )
    warnings = [f"missing:{item}" for item in missing]
    return {
        "ready_for_model_ranking": ready_for_model_ranking,
        "ready_for_outreach_drafting": ready_for_outreach_drafting,
        "warnings": warnings,
        "missing": missing,
        "stale": [],
        "refresh_actions": refresh_actions,
    }


def _model_inputs(
    *,
    goal: str,
    relationship_intelligence: dict[str, Any],
    research_refs: set[str],
) -> dict[str, Any]:
    return {
        "goal": goal,
        "candidate_evidence_refs": _evidence_ref_ids(relationship_intelligence),
        "candidate_research_refs": sorted(research_refs),
        "model_may_judge": [
            "goal relevance",
            "relationship strength and tenor",
            "outreach priority",
            "best angle",
            "risk or caution",
            "next action",
            "draft copy",
        ],
        "model_must_cite": [
            "relationship evidence refs for relationship claims",
            "research refs for external/current claims",
        ],
    }


def _roll_up_readiness(people: list[dict[str, Any]]) -> dict[str, Any]:
    if not people:
        return {
            "ready_for_model_ranking": False,
            "ready_for_outreach_drafting": False,
            "warnings": ["missing:candidates"],
            "missing": ["candidates"],
            "stale": [],
            "refresh_actions": [],
        }
    missing = sorted(
        {
            item
            for person in people
            for item in (person.get("packet_readiness") or {}).get("missing", [])
        }
    )
    stale = sorted(
        {
            item
            for person in people
            for item in (person.get("packet_readiness") or {}).get("stale", [])
        }
    )
    refresh_actions = [
        action
        for person in people
        for action in (person.get("packet_readiness") or {}).get("refresh_actions", [])
    ]
    return {
        "ready_for_model_ranking": all(
            (person.get("packet_readiness") or {}).get("ready_for_model_ranking")
            for person in people
        ),
        "ready_for_outreach_drafting": all(
            (person.get("packet_readiness") or {}).get("ready_for_outreach_drafting")
            for person in people
        ),
        "warnings": [f"missing:{item}" for item in missing] + [f"stale:{item}" for item in stale],
        "missing": missing,
        "stale": stale,
        "refresh_actions": refresh_actions,
    }


def _model_contract() -> dict[str, Any]:
    return {
        "owner": "model",
        "purpose": "Produce reviewable network recommendations and draft-only outreach proposals.",
        "required_fields": [
            "person_email",
            "priority",
            "goal_fit_rationale",
            "relationship_rationale",
            "relationship_risk_or_caution",
            "best_angle",
            "next_action",
            "draft_email",
            "cited_evidence_refs",
            "cited_research_refs",
        ],
        "code_owns": [
            "explicit request constraints",
            "history-backed search",
            "relationship evidence assembly",
            "organization enrichment preservation",
            "readiness reporting",
            "schema and citation validation",
        ],
        "model_owns": [
            "goal relevance judgment",
            "relationship strength interpretation",
            "tone and tenor interpretation",
            "priority label",
            "outreach angle",
            "draft copy",
            "next-action recommendation",
        ],
        "code_must_not": (
            "No hidden semantic filters, deterministic relationship quality scores, "
            "tone classifiers, or hardcoded outreach copy."
        ),
        "citation_requirement": (
            "Relationship claims must cite supplied evidence refs. "
            "External/current claims must cite supplied research refs."
        ),
    }


def _base_history_packet(
    database_url: str,
    *,
    actual_employee_count_min: int | None,
    actual_employee_count_max: int | None,
    consultant_count_min: int | None,
    consultant_count_max: int | None,
    limit: int,
    research_context: Any,
    evidence_limit: int,
    prior_state_limit: int,
) -> dict[str, Any]:
    return prepare_history_backed_outreach_proposal_packet(
        database_url,
        actual_employee_count_min=actual_employee_count_min,
        actual_employee_count_max=actual_employee_count_max,
        consultant_count_min=consultant_count_min,
        consultant_count_max=consultant_count_max,
        limit=limit,
        research_context=research_context,
        evidence_limit=evidence_limit,
        prior_state_limit=prior_state_limit,
    )


def _decorate_people(
    base_people: list[dict[str, Any]],
    *,
    goal: str,
    research_refs: set[str],
    refresh_actions_by_email: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    refresh_actions_by_email = refresh_actions_by_email or {}
    people: list[dict[str, Any]] = []
    for base_person in base_people:
        email = base_person["email"]
        relationship_intelligence = base_person["relationship_intelligence"]
        evidence_summary = _evidence_summary(base_person)
        packet_readiness = _packet_readiness(
            evidence_summary=evidence_summary,
            research_refs=research_refs,
            refresh_actions=refresh_actions_by_email.get(email, []),
        )
        people.append(
            {
                **base_person,
                "packet_readiness": packet_readiness,
                "evidence_summary": evidence_summary,
                "organization_context": _organization_context(base_person["search_hit"]),
                "model_inputs": _model_inputs(
                    goal=goal,
                    relationship_intelligence=relationship_intelligence,
                    research_refs=research_refs,
                ),
            }
        )
    return people


def prepare_ask_network_packet(
    database_url: str,
    *,
    goal: str,
    actual_employee_count_min: int | None = None,
    actual_employee_count_max: int | None = None,
    consultant_count_min: int | None = None,
    consultant_count_max: int | None = None,
    limit: int = 10,
    research_context: Any | None = None,
    evidence_limit: int = 10,
    prior_state_limit: int = 3,
    refresh_missing_evidence: Callable[..., dict[str, Any]] | None = None,
    refresh_evidence_limit: int = 50,
) -> dict[str, Any]:
    research_context = research_context if research_context is not None else {}
    research_refs = _research_refs(research_context)
    base_packet = _base_history_packet(
        database_url,
        actual_employee_count_min=actual_employee_count_min,
        actual_employee_count_max=actual_employee_count_max,
        consultant_count_min=consultant_count_min,
        consultant_count_max=consultant_count_max,
        limit=limit,
        research_context=research_context,
        evidence_limit=evidence_limit,
        prior_state_limit=prior_state_limit,
    )
    people = _decorate_people(base_packet["people"], goal=goal, research_refs=research_refs)

    refresh_actions_by_email: dict[str, list[dict[str, Any]]] = {}
    if refresh_missing_evidence is not None:
        missing_evidence_emails = [
            person["email"]
            for person in people
            if not person["evidence_summary"]["has_direct_relationship_evidence"]
        ]
        for email in missing_evidence_emails:
            refresh_actions_by_email.setdefault(email, []).append(
                {
                    "type": "msgvault_correspondence",
                    "email": email,
                    "limit": refresh_evidence_limit,
                    "result": refresh_missing_evidence(email=email, limit=refresh_evidence_limit),
                }
            )
        if missing_evidence_emails:
            base_packet = _base_history_packet(
                database_url,
                actual_employee_count_min=actual_employee_count_min,
                actual_employee_count_max=actual_employee_count_max,
                consultant_count_min=consultant_count_min,
                consultant_count_max=consultant_count_max,
                limit=limit,
                research_context=research_context,
                evidence_limit=evidence_limit,
                prior_state_limit=prior_state_limit,
            )
            people = _decorate_people(
                base_packet["people"],
                goal=goal,
                research_refs=research_refs,
                refresh_actions_by_email=refresh_actions_by_email,
            )

    return {
        "ask_stage": "network_relationship_packet",
        "contract_version": ASK_NETWORK_CONTRACT_VERSION,
        "query": {
            "goal": goal,
            "search_mode": "history_backed",
            "constraints": {
                "actual_employee_count_min": actual_employee_count_min,
                "actual_employee_count_max": actual_employee_count_max,
                "consultant_count_min": consultant_count_min,
                "consultant_count_max": consultant_count_max,
                "known_people_at_company_min": None,
                "known_people_at_company_max": None,
                "semantic_query": None,
                "semantic_provider": None,
                "embedding_model": None,
            },
            "limits": {
                "candidate_limit": limit,
                "evidence_limit": evidence_limit,
                "prior_state_limit": prior_state_limit,
                "refresh_evidence_limit": refresh_evidence_limit if refresh_missing_evidence else None,
            },
        },
        "readiness": _roll_up_readiness(people),
        "count": len(people),
        "people": people,
        "research_context": research_context,
        "model_contract": _model_contract(),
        "relationship_tone_model_contract": base_packet["relationship_tone_model_contract"],
    }


def _check(check_id: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"id": check_id, "passed": bool(passed), "detail": detail}


def evaluate_ask_network_packet(packet: dict[str, Any]) -> dict[str, Any]:
    people = packet.get("people") or []
    limit = ((packet.get("query") or {}).get("limits") or {}).get("candidate_limit")
    checks = [
        _check(
            "packet_contract",
            packet.get("ask_stage") == "network_relationship_packet"
            and packet.get("contract_version") == ASK_NETWORK_CONTRACT_VERSION
            and isinstance(packet.get("query"), dict)
            and isinstance(packet.get("readiness"), dict),
            "Packet exposes the ask-network stage, contract version, query, and readiness.",
        ),
        _check(
            "candidate_count_within_limit",
            isinstance(limit, int) and int(packet.get("count") or 0) <= limit,
            "Returned candidate count does not exceed the requested limit.",
        ),
        _check(
            "organization_size_evidence",
            bool(people)
            and all(
                (person.get("organization_context") or {}).get("actual_employee_count_min") is not None
                and (person.get("organization_context") or {}).get("actual_employee_count_max") is not None
                for person in people
            ),
            "Every candidate has actual organization size evidence from enrichment.",
        ),
        _check(
            "relationship_evidence",
            bool(people)
            and all(
                int((person.get("evidence_summary") or {}).get("evidence_ref_count") or 0) > 0
                for person in people
            ),
            "Every candidate has direct relationship evidence refs.",
        ),
        _check(
            "readiness_warnings_visible",
            bool((packet.get("readiness") or {}).get("warnings") or (packet.get("readiness") or {}).get("missing"))
            or bool((packet.get("readiness") or {}).get("ready_for_outreach_drafting")),
            "Readiness warnings are visible unless the packet is outreach-ready.",
        ),
        _check(
            "no_code_generated_draft",
            "draft_email" not in packet
            and all("draft_email" not in person for person in people),
            "Code did not generate draft outreach inside the ask-network packet.",
        ),
    ]
    return {
        "eval_stage": "ask_network_contract_eval",
        "ok": all(check["passed"] for check in checks),
        "checks": checks,
        "packet": packet,
    }


def validate_ask_network_recommendations(
    packet: dict[str, Any],
    recommendations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    packet_emails = {
        str(person.get("email") or "").strip().lower()
        for person in packet.get("people", [])
    }
    evidence_refs = _available_evidence_refs(packet)
    research_refs = _research_refs(packet.get("research_context"))
    validated: list[dict[str, Any]] = []
    for recommendation in recommendations:
        try:
            parsed = AskNetworkRecommendation.model_validate(recommendation)
        except ValueError as exc:
            raise ValueError(f"invalid ask-network recommendation: {exc}") from exc

        if parsed.person_email.strip().lower() not in packet_emails:
            raise ValueError("person_email is not present in the ask-network packet")

        missing_evidence_refs = [
            ref for ref in parsed.cited_evidence_refs if ref not in evidence_refs
        ]
        if missing_evidence_refs:
            raise ValueError(f"cited_evidence_refs not supplied by packet: {missing_evidence_refs}")

        missing_research_refs = [
            ref for ref in parsed.cited_research_refs if ref not in research_refs
        ]
        if missing_research_refs:
            raise ValueError(f"cited_research_refs not supplied by packet: {missing_research_refs}")

        validated.append(parsed.model_dump(mode="json"))
    return validated
