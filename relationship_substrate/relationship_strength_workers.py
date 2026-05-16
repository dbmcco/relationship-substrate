from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from relationship_substrate.contact_hygiene import is_automated_contact_email
from relationship_substrate.relationship_intelligence import (
    persist_relationship_state,
    prepare_relationship_strength_analysis_packet,
)
from relationship_substrate.tone_tenor_workers import (
    DEFAULT_OLLAMA_GENERATE_ENDPOINT,
    RepairProposal,
    _clean_text,
    _parse_json_object,
    _write_json,
    ollama_repair_relationship_proposal,
    validate_no_raw_private_leakage,
)


DEFAULT_RELATIONSHIP_STRENGTH_MODEL = "hermes3:8b"

GenerateProposal = Callable[[dict[str, Any]], str]


def parse_relationship_strength_proposal(content: str) -> dict[str, Any]:
    payload = _parse_json_object(content)
    evidence_refs = payload.get("evidence_refs") or []
    if isinstance(evidence_refs, list):
        evidence_refs = [
            {"id": evidence_ref.strip()} if isinstance(evidence_ref, str) else evidence_ref
            for evidence_ref in evidence_refs
        ]
    proposal = {
        "state_kind": "relationship_strength",
        "summary": _clean_text(payload.get("summary")),
        "rationale": _clean_text(payload.get("rationale")),
        "evidence_refs": evidence_refs,
        "supersedes_id": payload.get("supersedes_id"),
    }
    if not proposal["summary"]:
        raise ValueError("relationship strength proposal requires summary")
    if not proposal["rationale"]:
        raise ValueError("relationship strength proposal requires rationale")
    if not isinstance(proposal["evidence_refs"], list) or not proposal["evidence_refs"]:
        raise ValueError("relationship strength proposal requires evidence_refs")
    return proposal


def missing_relationship_strength_emails(database_url: str, *, limit: int = 25) -> list[str]:
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.primary_email
                FROM relationship_substrate.person p
                JOIN relationship_substrate.relationship_edge e
                  ON e.person_id = p.id
                WHERE p.primary_email IS NOT NULL
                AND COALESCE(e.interaction_count, 0) > 0
                AND EXISTS (
                  SELECT 1
                  FROM relationship_substrate.interaction i
                  JOIN relationship_substrate.evidence_ref er
                    ON er.source_event_id = i.source_event_id
                  WHERE i.metadata->>'sender_email' = p.primary_email
                  OR i.metadata->>'relationship_email' = p.primary_email
                  OR i.metadata->'attendee_emails' ? p.primary_email
                )
                AND NOT EXISTS (
                  SELECT 1
                  FROM relationship_substrate.relationship_state rs
                  WHERE rs.person_id = p.id
                  AND rs.state_kind = 'relationship_strength'
                )
                ORDER BY
                  COALESCE(e.interaction_count, 0) DESC,
                  e.last_interaction_at DESC NULLS LAST,
                  p.primary_email
                LIMIT %s
                """,
                (max(limit * 5, limit + 100),),
            )
            rows = cur.fetchall()
    emails = [row[0] for row in rows if not is_automated_contact_email(row[0])]
    return emails[:limit]


def _relationship_strength_prompt(packet: dict[str, Any]) -> str:
    return (
        "You are analyzing relationship strength from private relationship evidence.\n"
        "Return JSON only with keys: summary, rationale, evidence_refs, supersedes_id.\n"
        "Use state_kind relationship_strength implicitly; do not include extra keys.\n"
        "Interpret relationship strength from supplied mechanical facts and evidence: "
        "recency, duration, interaction volume, channel diversity, reciprocity, and directness.\n"
        "Every evidence_refs entry must be an object like {\"id\":\"supplied-evidence-id\"}.\n"
        "Do not quote raw message snippets, email addresses, URLs, or phone numbers.\n"
        "Do not recommend actions; only describe relationship strength grounded in evidence.\n\n"
        f"{json.dumps(packet, indent=2, sort_keys=True, default=str)}"
    )


def ollama_generate_relationship_strength(
    packet: dict[str, Any],
    *,
    model: str | None = None,
    endpoint: str | None = None,
    timeout_seconds: int = 180,
) -> str:
    model = model or os.environ.get(
        "RELATIONSHIP_SUBSTRATE_STRENGTH_MODEL",
        DEFAULT_RELATIONSHIP_STRENGTH_MODEL,
    )
    endpoint = endpoint or os.environ.get(
        "RELATIONSHIP_SUBSTRATE_OLLAMA_GENERATE_ENDPOINT",
        DEFAULT_OLLAMA_GENERATE_ENDPOINT,
    )
    payload = json.dumps(
        {
            "model": model,
            "prompt": _relationship_strength_prompt(packet),
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.2},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ollama relationship strength request failed: {exc}") from exc
    data = json.loads(raw)
    if data.get("error"):
        raise RuntimeError(f"Ollama relationship strength request failed: {data['error']}")
    return _clean_text(data.get("response"))


def run_relationship_strength_analysis(
    database_url: str,
    *,
    output_dir: Path,
    limit: int = 10,
    evidence_limit: int = 8,
    prior_state_limit: int = 3,
    apply: bool = False,
    model: str | None = None,
    generate_proposal: GenerateProposal | None = None,
    repair_proposal: RepairProposal | None = None,
) -> dict[str, Any]:
    using_default_generator = generate_proposal is None
    generate_proposal = generate_proposal or (lambda packet: ollama_generate_relationship_strength(packet, model=model))
    if repair_proposal is None and using_default_generator:
        repair_proposal = (
            lambda packet, raw_response, error: ollama_repair_relationship_proposal(
                packet,
                raw_response,
                error,
                state_kind="relationship_strength",
                model=model,
            )
        )
    run_started_at = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = output_dir / run_started_at
    emails = missing_relationship_strength_emails(database_url, limit=limit)
    packets: list[dict[str, Any]] = []
    proposals: list[dict[str, Any]] = []
    states: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    repaired = 0
    for email in emails:
        try:
            packet = prepare_relationship_strength_analysis_packet(
                database_url,
                emails=[email],
                evidence_limit=evidence_limit,
                prior_state_limit=prior_state_limit,
            )
            packets.append(packet)
            response = generate_proposal(packet)
            try:
                proposal = parse_relationship_strength_proposal(response)
                validate_no_raw_private_leakage(proposal, packet)
                state = persist_relationship_state(database_url, email=email, proposal=proposal) if apply else None
            except Exception as exc:
                if repair_proposal is None:
                    raise
                repair_response = repair_proposal(packet, response, str(exc))
                proposal = parse_relationship_strength_proposal(repair_response)
                validate_no_raw_private_leakage(proposal, packet)
                state = persist_relationship_state(database_url, email=email, proposal=proposal) if apply else None
                response = repair_response
                repaired += 1
            proposals.append({"email": email, "proposal": proposal, "raw_response": response})
            if state is not None:
                states.append(state)
        except Exception as exc:  # noqa: BLE001 - per-person failures are reportable work output.
            failures.append({"email": email, "error": str(exc)})
    artifacts = {
        "emails": _write_json(run_dir / "emails.json", emails),
        "packets": _write_json(run_dir / "strength_packets.json", packets),
        "proposals": _write_json(run_dir / "strength_proposals.json", proposals),
        "states": _write_json(run_dir / "persisted_states.json", states),
        "failures": _write_json(run_dir / "failures.json", failures),
    }
    report = {
        "ok": not failures,
        "run_started_at": run_started_at,
        "apply": apply,
        "model": model
        or os.environ.get("RELATIONSHIP_SUBSTRATE_STRENGTH_MODEL", DEFAULT_RELATIONSHIP_STRENGTH_MODEL),
        "selected": len(emails),
        "proposed": len(proposals),
        "applied": len(states),
        "failed": len(failures),
        "repaired": repaired,
        "failures": failures,
        "artifacts": artifacts,
        "output_dir": str(run_dir),
    }
    report["artifact"] = _write_json(run_dir / "relationship_strength_report.json", report)
    return report
