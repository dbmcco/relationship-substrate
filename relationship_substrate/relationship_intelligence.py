from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from uuid import UUID
from uuid import uuid4
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator

from relationship_substrate.dossiers import get_person_dossier
from relationship_substrate.freshness import relationship_freshness
from relationship_substrate.model_registry import DEFAULT_COGNITION_PRESETS_PATH, resolve_model_route


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


def _relationship_state_json_schema() -> dict[str, Any]:
    schema = RelationshipStateProposal.model_json_schema()
    schema["additionalProperties"] = False
    return schema


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
            row = _insert_relationship_state(
                cur,
                person_id=person_id,
                parsed=parsed,
                evidence_refs=evidence_refs,
                supersedes_id=supersedes_id,
            )
        conn.commit()
    return _relationship_state_payload(row)


def _insert_relationship_state(
    cur: psycopg.Cursor,
    *,
    person_id: UUID,
    parsed: RelationshipStateProposal,
    evidence_refs: list[dict[str, str]],
    supersedes_id: UUID | None,
) -> tuple:
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
    if row is None:
        raise RuntimeError("relationship_state insert returned no row")
    return row


def _relationship_state_payload(row: tuple) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "state_kind": row[1],
        "summary": row[2],
        "rationale": row[3],
        "evidence_refs": row[4],
        "supersedes_id": str(row[5]) if row[5] else None,
        "created_at": row[6].isoformat() if row[6] else None,
    }


PostJson = Callable[..., dict[str, Any]]


def _default_post_json(
    *,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = Request(url=url, data=data, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"model request failed with status {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"model request failed: {exc}") from exc
    return json.loads(body)


def _extract_json_content(response_payload: dict[str, Any]) -> dict[str, Any]:
    choices = response_payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("model response did not contain choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ValueError("model response did not contain a message payload")
    content = message.get("content")
    if isinstance(content, str):
        return json.loads(content)
    if isinstance(content, list):
        text_parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                text_value = part.get("text")
                if isinstance(text_value, str):
                    text_parts.append(text_value)
        if text_parts:
            return json.loads("".join(text_parts))
    raise ValueError("model response content was not parseable JSON text")


def propose_relationship_state_live(
    database_url: str,
    *,
    email: str,
    route_key: str,
    service_name: str = "relationship-substrate",
    registry_path: str = DEFAULT_COGNITION_PRESETS_PATH,
    evidence_limit: int = 10,
    post_json: PostJson = _default_post_json,
) -> dict[str, Any]:
    normalized_email = email.strip().lower()
    packet = prepare_relationship_intelligence_packet(
        database_url,
        email=normalized_email,
        evidence_limit=evidence_limit,
    )
    route = resolve_model_route(
        route_key=route_key,
        service_name=service_name,
        registry_path=registry_path,
    )
    headers = {"Content-Type": "application/json"}
    if route.api_key:
        headers["Authorization"] = f"Bearer {route.api_key}"
    request_payload: dict[str, Any] = {
        "model": route.model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You produce relationship_state proposals only. "
                    "Return JSON matching the provided schema and cite supplied evidence_refs."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(packet, sort_keys=True),
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "relationship_state_proposal",
                "strict": True,
                "schema": _relationship_state_json_schema(),
            },
        },
    }
    if route.max_tokens_default is not None:
        request_payload["max_tokens"] = route.max_tokens_default

    response_payload = post_json(
        url=route.endpoint_url,
        headers=headers,
        payload=request_payload,
        timeout_seconds=route.timeout_seconds,
    )
    proposal_raw = _extract_json_content(response_payload)
    try:
        parsed = RelationshipStateProposal.model_validate(proposal_raw)
    except ValueError as exc:
        raise ValueError(f"invalid relationship_state proposal from model route {route_key}: {exc}") from exc

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            person_id = _person_row(cur, email=normalized_email)[0]
            linked_evidence_refs = [
                _linked_evidence_ref(cur, email=normalized_email, evidence_ref=evidence_ref)
                for evidence_ref in parsed.evidence_refs
            ]
            proposal_key = f"relationship_state_proposal:{normalized_email}:{uuid4().hex}"
            cur.execute(
                """
                INSERT INTO relationship_substrate.source_event (
                  source_name,
                  source_event_type,
                  source_event_key,
                  source_payload,
                  source_posture,
                  provenance_status,
                  trust_role
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, source_event_type, source_event_key, observed_at
                """,
                (
                    "relationship_substrate",
                    "relationship_state_model_proposal",
                    proposal_key,
                    Jsonb(
                        {
                            "email": normalized_email,
                            "person_id": str(person_id),
                            "model_route": {
                                "route_key": route.route_key,
                                "surface": route.surface,
                                "provider": route.provider,
                                "model": route.model,
                                "credential_alias": route.credential_alias,
                                "credential_env_var": route.credential_env_var,
                            },
                            "proposal": parsed.model_dump(),
                            "packet": packet,
                        }
                    ),
                    "derived_interpretation",
                    "model_proposal",
                    "model-authored interpreted relationship_state proposal",
                ),
            )
            proposal_event_row = cur.fetchone()
            if proposal_event_row is None:
                raise RuntimeError("proposal source_event insert returned no row")

            cur.execute(
                """
                INSERT INTO relationship_substrate.evidence_ref (
                  source_event_id, ref_type, ref_value, metadata
                )
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (
                    proposal_event_row[0],
                    "relationship_state_proposal",
                    proposal_key,
                    Jsonb(
                        {
                            "email": normalized_email,
                            "route_key": route.route_key,
                            "service_name": service_name,
                        }
                    ),
                ),
            )
            proposal_ref_row = cur.fetchone()
            if proposal_ref_row is None:
                raise RuntimeError("proposal evidence_ref insert returned no row")

            supersedes_id = UUID(parsed.supersedes_id) if parsed.supersedes_id else None
            relationship_state_row = _insert_relationship_state(
                cur,
                person_id=person_id,
                parsed=parsed,
                evidence_refs=linked_evidence_refs,
                supersedes_id=supersedes_id,
            )

            journal_evidence_refs = [
                *linked_evidence_refs,
                {"id": str(proposal_ref_row[0]), "ref_type": "relationship_state_proposal"},
            ]
            cur.execute(
                """
                INSERT INTO relationship_substrate.state_journal_entry (
                  entity_type, entity_id, change_kind, summary, evidence_refs
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, entity_type, entity_id, change_kind, summary, evidence_refs, created_at
                """,
                (
                    "relationship_state",
                    relationship_state_row[0],
                    "model_proposal_committed",
                    parsed.summary,
                    Jsonb(journal_evidence_refs),
                ),
            )
            journal_row = cur.fetchone()
            if journal_row is None:
                raise RuntimeError("state_journal_entry insert returned no row")
        conn.commit()

    return {
        "model_route": {
            "route_key": route.route_key,
            "surface": route.surface,
            "provider": route.provider,
            "model": route.model,
            "service_name": service_name,
            "registry_path": registry_path,
            "credential_alias": route.credential_alias,
            "credential_env_var": route.credential_env_var,
        },
        "proposal_event": {
            "source_event_id": str(proposal_event_row[0]),
            "source_event_type": proposal_event_row[1],
            "source_event_key": proposal_event_row[2],
            "observed_at": proposal_event_row[3].isoformat() if proposal_event_row[3] else None,
            "evidence_ref_id": str(proposal_ref_row[0]),
        },
        "relationship_state": _relationship_state_payload(relationship_state_row),
        "journal_entry": {
            "id": str(journal_row[0]),
            "entity_type": journal_row[1],
            "entity_id": str(journal_row[2]),
            "change_kind": journal_row[3],
            "summary": journal_row[4],
            "evidence_refs": journal_row[5],
            "created_at": journal_row[6].isoformat() if journal_row[6] else None,
        },
    }
