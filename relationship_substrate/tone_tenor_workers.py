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
    prepare_relationship_tone_tenor_analysis_packet,
)


DEFAULT_TONE_TENOR_MODEL = "hermes3:8b"
DEFAULT_OLLAMA_GENERATE_ENDPOINT = "http://localhost:11434/api/generate"

GenerateProposal = Callable[[dict[str, Any]], str]
RepairProposal = Callable[[dict[str, Any], str, str], str]


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _write_json(path: Path, payload: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")
    return str(path)


def _parse_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("model response did not contain a JSON object")


def parse_tone_tenor_proposal(content: str) -> dict[str, Any]:
    payload = _parse_json_object(content)
    evidence_refs = payload.get("evidence_refs") or []
    if isinstance(evidence_refs, list):
        evidence_refs = [
            {"id": evidence_ref.strip()} if isinstance(evidence_ref, str) else evidence_ref
            for evidence_ref in evidence_refs
        ]
    proposal = {
        "state_kind": "relationship_tone_tenor",
        "summary": _clean_text(payload.get("summary")),
        "rationale": _clean_text(payload.get("rationale")),
        "evidence_refs": evidence_refs,
        "supersedes_id": payload.get("supersedes_id"),
    }
    if not proposal["summary"]:
        raise ValueError("tone/tenor proposal requires summary")
    if not proposal["rationale"]:
        raise ValueError("tone/tenor proposal requires rationale")
    if not isinstance(proposal["evidence_refs"], list) or not proposal["evidence_refs"]:
        raise ValueError("tone/tenor proposal requires evidence_refs")
    return proposal


def _private_text_fragments(packet: dict[str, Any]) -> list[str]:
    fragments: list[str] = []
    for person_entry in packet.get("people") or []:
        for key in ("email",):
            value = _clean_text(person_entry.get(key))
            if len(value) >= 12:
                fragments.append(value)
        person = person_entry.get("person") or {}
        value = _clean_text(person.get("primary_email"))
        if len(value) >= 12:
            fragments.append(value)
        for channel in person_entry.get("contact_channels") or []:
            value = _clean_text(channel.get("channel_value"))
            if len(value) >= 12:
                fragments.append(value)
        intelligence = person_entry.get("relationship_intelligence") or {}
        for evidence in intelligence.get("evidence") or []:
            snippet = _clean_text(evidence.get("snippet"))
            if len(snippet) >= 20:
                fragments.append(snippet)
    return fragments


def validate_no_raw_private_leakage(proposal: dict[str, Any], packet: dict[str, Any]) -> None:
    public_text = "\n".join(
        [
            _clean_text(proposal.get("summary")),
            _clean_text(proposal.get("rationale")),
        ]
    ).casefold()
    for fragment in _private_text_fragments(packet):
        if fragment.casefold() in public_text:
            raise ValueError("tone/tenor proposal leaks raw private evidence")


def missing_tone_tenor_emails(database_url: str, *, limit: int = 25) -> list[str]:
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
                  AND rs.state_kind = 'relationship_tone_tenor'
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


def _tone_tenor_prompt(packet: dict[str, Any]) -> str:
    return (
        "You are analyzing relationship tone and tenor from private evidence supplied below.\n"
        "Return JSON only with keys: summary, rationale, evidence_refs, supersedes_id.\n"
        "Use state_kind relationship_tone_tenor implicitly; do not include extra keys.\n"
        "Every evidence_refs entry must be an object like {\"id\":\"supplied-evidence-id\"}.\n"
        "Do not quote raw message snippets, email addresses, URLs, or phone numbers.\n"
        "Do not recommend actions; only describe tone/tenor grounded in evidence.\n\n"
        f"{json.dumps(packet, indent=2, sort_keys=True, default=str)}"
    )


def _repair_prompt(
    *,
    state_kind: str,
    packet: dict[str, Any],
    raw_response: str,
    error: str,
) -> str:
    return (
        "Repair a model proposal for a private relationship intelligence system.\n"
        "Return JSON only with keys: summary, rationale, evidence_refs, supersedes_id.\n"
        f"Use state_kind {state_kind} implicitly; do not include extra keys.\n"
        "Every evidence_refs entry must be an object like {\"id\":\"supplied-evidence-id\"} "
        "and must cite only an id from supplied evidence.\n"
        "Do not quote raw message snippets, email addresses, URLs, or phone numbers.\n"
        "Do not invent evidence. Do not recommend actions.\n\n"
        f"Validation error:\n{error}\n\n"
        f"Invalid proposal:\n{raw_response}\n\n"
        f"Original evidence packet:\n{json.dumps(packet, indent=2, sort_keys=True, default=str)}"
    )


def ollama_repair_relationship_proposal(
    packet: dict[str, Any],
    raw_response: str,
    error: str,
    *,
    state_kind: str,
    model: str | None = None,
    endpoint: str | None = None,
    timeout_seconds: int = 180,
) -> str:
    model = model or os.environ.get("RELATIONSHIP_SUBSTRATE_TONE_MODEL", DEFAULT_TONE_TENOR_MODEL)
    endpoint = endpoint or os.environ.get("RELATIONSHIP_SUBSTRATE_OLLAMA_GENERATE_ENDPOINT", DEFAULT_OLLAMA_GENERATE_ENDPOINT)
    payload = json.dumps(
        {
            "model": model,
            "prompt": _repair_prompt(
                state_kind=state_kind,
                packet=packet,
                raw_response=raw_response,
                error=error,
            ),
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1},
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
        raise RuntimeError(f"Ollama relationship proposal repair failed: {exc}") from exc
    data = json.loads(raw)
    if data.get("error"):
        raise RuntimeError(f"Ollama relationship proposal repair failed: {data['error']}")
    return _clean_text(data.get("response"))


def ollama_generate_tone_tenor(
    packet: dict[str, Any],
    *,
    model: str | None = None,
    endpoint: str | None = None,
    timeout_seconds: int = 180,
) -> str:
    model = model or os.environ.get("RELATIONSHIP_SUBSTRATE_TONE_MODEL", DEFAULT_TONE_TENOR_MODEL)
    endpoint = endpoint or os.environ.get("RELATIONSHIP_SUBSTRATE_OLLAMA_GENERATE_ENDPOINT", DEFAULT_OLLAMA_GENERATE_ENDPOINT)
    payload = json.dumps(
        {
            "model": model,
            "prompt": _tone_tenor_prompt(packet),
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
        raise RuntimeError(f"Ollama tone/tenor request failed: {exc}") from exc
    data = json.loads(raw)
    if data.get("error"):
        raise RuntimeError(f"Ollama tone/tenor request failed: {data['error']}")
    return _clean_text(data.get("response"))


def run_relationship_tone_tenor_analysis(
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
    generate_proposal = generate_proposal or (lambda packet: ollama_generate_tone_tenor(packet, model=model))
    if repair_proposal is None and using_default_generator:
        repair_proposal = (
            lambda packet, raw_response, error: ollama_repair_relationship_proposal(
                packet,
                raw_response,
                error,
                state_kind="relationship_tone_tenor",
                model=model,
            )
        )
    run_started_at = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = output_dir / run_started_at
    emails = missing_tone_tenor_emails(database_url, limit=limit)
    packets: list[dict[str, Any]] = []
    proposals: list[dict[str, Any]] = []
    states: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    repaired = 0
    for email in emails:
        try:
            packet = prepare_relationship_tone_tenor_analysis_packet(
                database_url,
                emails=[email],
                evidence_limit=evidence_limit,
                prior_state_limit=prior_state_limit,
            )
            packets.append(packet)
            response = generate_proposal(packet)
            try:
                proposal = parse_tone_tenor_proposal(response)
                validate_no_raw_private_leakage(proposal, packet)
                state = persist_relationship_state(database_url, email=email, proposal=proposal) if apply else None
            except Exception as exc:
                if repair_proposal is None:
                    raise
                repair_response = repair_proposal(packet, response, str(exc))
                proposal = parse_tone_tenor_proposal(repair_response)
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
        "packets": _write_json(run_dir / "tone_packets.json", packets),
        "proposals": _write_json(run_dir / "tone_proposals.json", proposals),
        "states": _write_json(run_dir / "persisted_states.json", states),
        "failures": _write_json(run_dir / "failures.json", failures),
    }
    report = {
        "ok": not failures,
        "run_started_at": run_started_at,
        "apply": apply,
        "model": model or os.environ.get("RELATIONSHIP_SUBSTRATE_TONE_MODEL", DEFAULT_TONE_TENOR_MODEL),
        "selected": len(emails),
        "proposed": len(proposals),
        "applied": len(states),
        "failed": len(failures),
        "repaired": repaired,
        "failures": failures,
        "artifacts": artifacts,
        "output_dir": str(run_dir),
    }
    report["artifact"] = _write_json(run_dir / "tone_tenor_report.json", report)
    return report
