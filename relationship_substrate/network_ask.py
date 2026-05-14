from __future__ import annotations

from typing import Any

from relationship_substrate.outreach import prepare_history_backed_outreach_proposal_packet


ASK_NETWORK_CONTRACT_VERSION = 1


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
) -> dict[str, Any]:
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
        "refresh_actions": [],
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
) -> dict[str, Any]:
    research_context = research_context if research_context is not None else {}
    research_refs = _research_refs(research_context)
    base_packet = prepare_history_backed_outreach_proposal_packet(
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
    people: list[dict[str, Any]] = []
    for base_person in base_packet["people"]:
        relationship_intelligence = base_person["relationship_intelligence"]
        evidence_summary = _evidence_summary(base_person)
        packet_readiness = _packet_readiness(
            evidence_summary=evidence_summary,
            research_refs=research_refs,
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
            },
        },
        "readiness": _roll_up_readiness(people),
        "count": len(people),
        "people": people,
        "research_context": research_context,
        "model_contract": _model_contract(),
        "relationship_tone_model_contract": base_packet["relationship_tone_model_contract"],
    }
