from __future__ import annotations

from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator

from relationship_substrate.dossiers import get_person_dossier
from relationship_substrate.freshness import relationship_freshness


class RelationshipStateProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state_kind: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    evidence_refs: list[dict[str, Any]] = Field(min_length=1)
    supersedes_id: str | None = None

    @field_validator("evidence_refs")
    @classmethod
    def _requires_addressable_evidence_refs(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for evidence_ref in value:
            has_id = bool(str(evidence_ref.get("id") or "").strip())
            has_natural_key = bool(str(evidence_ref.get("ref_type") or "").strip()) and bool(
                str(evidence_ref.get("ref_value") or "").strip()
            )
            if not has_id and not has_natural_key:
                raise ValueError("each evidence_refs entry must include id or ref_type/ref_value")
        return value


def _person_row(cur: psycopg.Cursor, *, email: str) -> tuple:
    normalized_email = email.strip().lower()
    cur.execute(
        """
        SELECT id, display_name, primary_email
        FROM relationship_substrate.person
        WHERE primary_email = %s
        """,
        (normalized_email,),
    )
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"person not found for email: {normalized_email}")
    return row


def _mechanical_relationship_facts(row: tuple | None) -> dict[str, Any]:
    if row is None:
        return {
            "interaction_count": 0,
            "first_interaction_at": None,
            "last_interaction_at": None,
            "calendar_interaction_count": 0,
            "email_message_count": 0,
            "freshness": relationship_freshness(None),
            "metadata": {},
        }
    metadata = row[3] or {}
    last_interaction_at = row[2].isoformat() if row[2] else None
    return {
        "interaction_count": row[0],
        "first_interaction_at": row[1].isoformat() if row[1] else None,
        "last_interaction_at": last_interaction_at,
        "calendar_interaction_count": int(metadata.get("calendar_interaction_count") or 0),
        "email_message_count": int(metadata.get("email_message_count") or 0),
        "freshness": relationship_freshness(last_interaction_at),
        "metadata": metadata,
    }


def _snippet(source_payload: dict[str, Any], interaction_metadata: dict[str, Any]) -> str | None:
    for key in ("snippet", "body", "text", "description"):
        value = interaction_metadata.get(key)
        if value is None:
            value = source_payload.get(key)
        text = str(value or "").strip()
        if text:
            return text
    return None


def _evidence(row: tuple) -> dict[str, Any]:
    source_payload = row[9] or {}
    interaction_metadata = row[8] or {}
    return {
        "id": str(row[0]),
        "source_event_id": str(row[1]),
        "ref_type": row[2],
        "ref_value": row[3],
        "metadata": row[4],
        "occurred_at": row[5].isoformat() if row[5] else None,
        "interaction_type": row[6],
        "subject": row[7],
        "snippet": _snippet(source_payload, interaction_metadata),
        "source_name": row[10],
        "source_event_type": row[11],
        "source_event_key": row[12],
    }


def prepare_relationship_intelligence_packet(
    database_url: str,
    *,
    email: str,
    evidence_limit: int = 10,
) -> dict[str, Any]:
    normalized_email = email.strip().lower()
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            person_id, display_name, primary_email = _person_row(cur, email=normalized_email)
            cur.execute(
                """
                SELECT interaction_count, first_interaction_at, last_interaction_at, metadata
                FROM relationship_substrate.relationship_edge
                WHERE person_id = %s
                """,
                (person_id,),
            )
            edge_row = cur.fetchone()
            cur.execute(
                """
                SELECT
                  er.id,
                  er.source_event_id,
                  er.ref_type,
                  er.ref_value,
                  er.metadata,
                  i.occurred_at,
                  i.interaction_type,
                  i.subject,
                  i.metadata,
                  se.source_payload,
                  se.source_name,
                  se.source_event_type,
                  se.source_event_key
                FROM relationship_substrate.interaction i
                JOIN relationship_substrate.evidence_ref er
                  ON er.source_event_id = i.source_event_id
                JOIN relationship_substrate.source_event se
                  ON se.id = er.source_event_id
                WHERE i.metadata->>'sender_email' = %s
                OR i.metadata->>'relationship_email' = %s
                OR i.metadata->'attendee_emails' ? %s
                ORDER BY i.occurred_at DESC NULLS LAST, er.ref_type, er.ref_value
                LIMIT %s
                """,
                (normalized_email, normalized_email, normalized_email, evidence_limit),
            )
            evidence_rows = cur.fetchall()
    return {
        "person": {
            "id": str(person_id),
            "display_name": display_name,
            "primary_email": primary_email,
        },
        "mechanical_relationship_facts": _mechanical_relationship_facts(edge_row),
        "evidence": [_evidence(row) for row in evidence_rows],
        "relationship_state_contract": {
            "owner": "model",
            "required_fields": ["state_kind", "summary", "rationale", "evidence_refs"],
            "evidence_ref_requirement": "Every relationship_state must cite supplied evidence refs.",
        },
    }


def _tone_tenor_model_contract() -> dict[str, Any]:
    return {
        "owner": "model",
        "purpose": (
            "Produce evidence-backed relationship tone/tenor proposals only; "
            "do not mutate persisted state in this stage."
        ),
        "required_fields": [
            "person_email",
            "state_kind",
            "summary",
            "rationale",
            "evidence_refs",
            "supersedes_id",
        ],
        "code_owns": [
            "person dossier retrieval",
            "relationship evidence assembly",
            "mechanical relationship facts",
            "prior relationship_state retrieval",
            "packet schema",
            "CLI JSON output",
        ],
        "model_owns": [
            "qualitative tone interpretation",
            "qualitative tenor interpretation",
            "summary wording",
            "rationale wording",
            "supersedes choice",
        ],
        "code_must_not": (
            "No deterministic tone classifier, hidden fit score, "
            "or hardcoded semantic interpretation."
        ),
        "citation_requirement": "Every proposal must cite supplied evidence refs.",
    }


def _relationship_strength_model_contract() -> dict[str, Any]:
    return {
        "owner": "model",
        "purpose": (
            "Produce evidence-backed relationship strength proposals only; "
            "do not mutate persisted state in this stage."
        ),
        "required_fields": [
            "person_email",
            "state_kind",
            "summary",
            "rationale",
            "evidence_refs",
            "supersedes_id",
        ],
        "code_owns": [
            "person dossier retrieval",
            "relationship evidence assembly",
            "mechanical relationship facts",
            "prior relationship_state retrieval",
            "packet schema",
            "CLI JSON output",
        ],
        "model_owns": [
            "relationship strength interpretation",
            "confidence interpretation",
            "age and freshness interpretation",
            "reciprocity and engagement interpretation",
            "summary wording",
            "rationale wording",
            "supersedes choice",
        ],
        "code_must_not": (
            "No deterministic relationship score, hidden weighting formula, "
            "or hardcoded semantic interpretation."
        ),
        "citation_requirement": "Every proposal must cite supplied evidence refs.",
    }


def prepare_relationship_tone_tenor_analysis_packet(
    database_url: str,
    *,
    emails: list[str],
    evidence_limit: int = 10,
    prior_state_limit: int = 3,
) -> dict[str, Any]:
    people: list[dict[str, Any]] = []
    for email in emails:
        normalized_email = email.strip().lower()
        dossier = get_person_dossier(database_url, email=normalized_email)
        relationship_intelligence = prepare_relationship_intelligence_packet(
            database_url,
            email=normalized_email,
            evidence_limit=evidence_limit,
        )
        prior_states = [
            state
            for state in dossier.get("relationship_states", [])
            if state.get("state_kind") == "relationship_tone_tenor"
        ][:prior_state_limit]
        people.append(
            {
                "email": normalized_email,
                "person": dossier.get("person"),
                "relationship_edge": dossier.get("relationship_edge"),
                "contact_channels": dossier.get("contact_channels", []),
                "dossier_counts": {
                    "interactions": len(dossier.get("interactions", [])),
                    "evidence_refs": len(dossier.get("evidence_refs", [])),
                    "source_events": len(dossier.get("source_events", [])),
                    "identity_candidates": len(dossier.get("identity_candidates", [])),
                    "relationship_states": len(dossier.get("relationship_states", [])),
                },
                "relationship_intelligence": relationship_intelligence,
                "prior_tone_tenor_states": prior_states,
            }
        )
    return {
        "analysis_stage": "relationship_tone_tenor",
        "count": len(people),
        "people": people,
        "model_contract": _tone_tenor_model_contract(),
    }


def prepare_relationship_strength_analysis_packet(
    database_url: str,
    *,
    emails: list[str],
    evidence_limit: int = 10,
    prior_state_limit: int = 3,
) -> dict[str, Any]:
    people: list[dict[str, Any]] = []
    for email in emails:
        normalized_email = email.strip().lower()
        dossier = get_person_dossier(database_url, email=normalized_email)
        relationship_intelligence = prepare_relationship_intelligence_packet(
            database_url,
            email=normalized_email,
            evidence_limit=evidence_limit,
        )
        prior_states = [
            state
            for state in dossier.get("relationship_states", [])
            if state.get("state_kind") == "relationship_strength"
        ][:prior_state_limit]
        people.append(
            {
                "email": normalized_email,
                "person": dossier.get("person"),
                "relationship_edge": dossier.get("relationship_edge"),
                "contact_channels": dossier.get("contact_channels", []),
                "dossier_counts": {
                    "interactions": len(dossier.get("interactions", [])),
                    "evidence_refs": len(dossier.get("evidence_refs", [])),
                    "source_events": len(dossier.get("source_events", [])),
                    "identity_candidates": len(dossier.get("identity_candidates", [])),
                    "relationship_states": len(dossier.get("relationship_states", [])),
                },
                "relationship_intelligence": relationship_intelligence,
                "prior_relationship_strength_states": prior_states,
            }
        )
    return {
        "analysis_stage": "relationship_strength",
        "count": len(people),
        "people": people,
        "model_contract": _relationship_strength_model_contract(),
    }


def _linked_evidence_ref(
    cur: psycopg.Cursor,
    *,
    email: str,
    evidence_ref: dict[str, Any],
) -> dict[str, str]:
    params: list[Any] = []
    if evidence_ref.get("id"):
        evidence_filter = "er.id = %s"
        params.append(UUID(str(evidence_ref["id"])))
    else:
        evidence_filter = "er.ref_type = %s AND er.ref_value = %s"
        params.extend([evidence_ref["ref_type"], evidence_ref["ref_value"]])
    params.extend([email, email, email])
    cur.execute(
        f"""
        SELECT er.id
        FROM relationship_substrate.evidence_ref er
        JOIN relationship_substrate.interaction i
          ON i.source_event_id = er.source_event_id
        WHERE {evidence_filter}
        AND (
          i.metadata->>'sender_email' = %s
          OR i.metadata->>'relationship_email' = %s
          OR i.metadata->'attendee_emails' ? %s
        )
        """,
        params,
    )
    row = cur.fetchone()
    if row is None:
        raise ValueError("evidence_ref is not linked to the requested person")
    return {"id": str(row[0])}


def persist_relationship_state(
    database_url: str,
    *,
    email: str,
    proposal: dict[str, Any],
) -> dict[str, Any]:
    normalized_email = email.strip().lower()
    try:
        parsed = RelationshipStateProposal.model_validate(proposal)
    except ValueError as exc:
        raise ValueError(f"invalid relationship_state proposal: {exc}") from exc

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            person_id = _person_row(cur, email=normalized_email)[0]
            evidence_refs = [
                _linked_evidence_ref(cur, email=normalized_email, evidence_ref=evidence_ref)
                for evidence_ref in parsed.evidence_refs
            ]
            supersedes_id = UUID(parsed.supersedes_id) if parsed.supersedes_id else None
            cur.execute(
                """
                INSERT INTO relationship_substrate.relationship_state (
                  person_id, state_kind, summary, rationale, evidence_refs, supersedes_id
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, state_kind, summary, rationale, evidence_refs, supersedes_id, created_at
                """,
                (
                    person_id,
                    parsed.state_kind,
                    parsed.summary,
                    parsed.rationale,
                    Jsonb(evidence_refs),
                    supersedes_id,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    if row is None:
        raise RuntimeError("relationship_state insert returned no row")
    return {
        "id": str(row[0]),
        "state_kind": row[1],
        "summary": row[2],
        "rationale": row[3],
        "evidence_refs": row[4],
        "supersedes_id": str(row[5]) if row[5] else None,
        "created_at": row[6].isoformat() if row[6] else None,
    }
