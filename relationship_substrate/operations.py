from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse, urlunparse

import psycopg
from psycopg import sql

from relationship_substrate.adapters.calendar import iter_calendar_export_paths, iter_calendar_json_events
from relationship_substrate.adapters.msgvault import MsgvaultAdapter
from relationship_substrate.adapters.next_up import iter_next_up_events
from relationship_substrate.config import Settings
from relationship_substrate.contracts import SourceEventIn, SourcePosture
from relationship_substrate.db import run_migrations
from relationship_substrate.embeddings import (
    embed_curated_contacts,
    embed_missing_organizations,
    embed_missing_people,
)
from relationship_substrate.identity import generate_identity_candidates
from relationship_substrate.materialize import (
    materialize_calendar_events,
    materialize_exact_emails,
    materialize_msgvault_correspondence,
    materialize_msgvault_senders,
)
from relationship_substrate.network_ask import (
    evaluate_ask_network_packet,
    prepare_ask_network_packet,
    tone_state_worklist_from_ask_packet,
    validate_ask_network_recommendations,
)
from relationship_substrate.network_feedback import record_network_feedback
from relationship_substrate.network_packets import persist_ask_network_packet
from relationship_substrate.organizations import history_backed_organization_worklist
from relationship_substrate.repositories import (
    identity_candidate_counts,
    operating_picture_rows,
    substrate_counts,
    upsert_evidence_ref,
    upsert_source_event,
)
from relationship_substrate.search import DEFAULT_ROLE_KEYWORDS, search_history_backed_people, search_people


EmbedTexts = Callable[[list[str]], list[list[float]]]

DEFAULT_NORTH_STAR_SEMANTIC_QUERY = (
    "consulting background in medcoms medical communications business consulting "
    "supply chain pharma small consulting team"
)


def _json_default(value: object) -> str:
    return str(value)


def _write_json(path: Path, payload: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=_json_default) + "\n")
    return str(path)


def _email_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1] if "@" in email else ""


def _is_system_sender(
    email: str,
    *,
    skipped_system_localparts: set[str],
    skipped_system_prefixes: set[str],
) -> bool:
    localpart = email.split("@", 1)[0]
    normalized_localpart = localpart.replace(".", "-").replace("_", "-").lower()
    return localpart in skipped_system_localparts or normalized_localpart in skipped_system_localparts or any(
        normalized_localpart.startswith(prefix) for prefix in skipped_system_prefixes
    )


def select_correspondence_seed_emails(
    rows: list[dict[str, object]],
    *,
    limit: int,
    self_aliases: set[str],
    skipped_domains: set[str],
    skipped_system_localparts: set[str],
    skipped_system_prefixes: set[str],
) -> list[str]:
    """Select top msgvault correspondence seeds mechanically from sender profile rows."""
    selected: list[str] = []
    seen: set[str] = set()
    for row in rows:
        email = str(row.get("email") or "").strip().lower()
        if not email or email in seen:
            continue
        seen.add(email)
        if email in self_aliases:
            continue
        if _email_domain(email) in skipped_domains:
            continue
        if _is_system_sender(
            email,
            skipped_system_localparts=skipped_system_localparts,
            skipped_system_prefixes=skipped_system_prefixes,
        ):
            continue
        selected.append(email)
        if len(selected) >= limit:
            break
    return selected


def ensure_database_exists(database_url: str) -> dict[str, object]:
    parsed = urlparse(database_url)
    dbname = parsed.path.lstrip("/")
    if parsed.scheme not in {"postgresql", "postgres"} or not dbname:
        return {"checked": False, "created": False, "reason": "not_a_named_postgres_database"}
    maintenance_url = urlunparse(parsed._replace(path="/postgres"))
    with psycopg.connect(maintenance_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
            exists = cur.fetchone() is not None
            if not exists:
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
    return {"checked": True, "created": not exists, "database": dbname}


def _ingest_next_up(database_url: str, path: Path) -> dict[str, int | str]:
    events_seen = 0
    events_upserted = 0
    for event in iter_next_up_events(path):
        events_seen += 1
        upsert_source_event(database_url, event)
        events_upserted += 1
    return {
        "source": "next_up",
        "path": str(path),
        "events_seen": events_seen,
        "events_upserted": events_upserted,
    }


def _ingest_calendar(database_url: str, path: Path) -> dict[str, int | str]:
    files_seen = 0
    events_seen = 0
    events_upserted = 0
    for export_path in iter_calendar_export_paths(path):
        files_seen += 1
        for event in iter_calendar_json_events(export_path):
            events_seen += 1
            source_event_id = upsert_source_event(database_url, event)
            upsert_evidence_ref(
                database_url,
                source_event_id=source_event_id,
                ref_type="calendar_event",
                ref_value=event.source_event_key,
                metadata={"path": str(export_path)},
            )
            events_upserted += 1
    report = {
        "source": "calendar",
        "path": str(path),
        "events_seen": events_seen,
        "events_upserted": events_upserted,
    }
    if path.is_dir():
        report["files_seen"] = files_seen
    return report


def _ingest_msgvault_sender_rows(
    database_url: str,
    rows: list[dict[str, object]],
    *,
    self_aliases: set[str],
    skipped_domains: set[str],
    skipped_system_localparts: set[str],
    skipped_system_prefixes: set[str],
) -> dict[str, int | str]:
    stats = {
        "source": "msgvault",
        "events_seen": len(rows),
        "events_upserted": 0,
        "skipped_self": 0,
        "skipped_domain": 0,
        "skipped_system": 0,
        "skipped_missing_email": 0,
    }
    for row in rows:
        email = str(row.get("email") or "").strip().lower()
        if not email:
            stats["skipped_missing_email"] += 1
            continue
        if email in self_aliases:
            stats["skipped_self"] += 1
            continue
        if _email_domain(email) in skipped_domains:
            stats["skipped_domain"] += 1
            continue
        if _is_system_sender(
            email,
            skipped_system_localparts=skipped_system_localparts,
            skipped_system_prefixes=skipped_system_prefixes,
        ):
            stats["skipped_system"] += 1
            continue
        event = SourceEventIn(
            source_name="msgvault",
            source_event_type="sender_profile",
            source_event_key=f"msgvault:sender:{email}",
            source_payload={
                "email": email,
                "display_name": row.get("display_name"),
                "message_count": int(row.get("message_count") or 0),
                "total_size": int(row.get("total_size") or 0),
                "attachment_size": int(row.get("attachment_size") or 0),
            },
            source_posture=SourcePosture.DIRECT_INTERACTION,
            provenance_status="msgvault_profile",
            trust_role="direct email aggregate",
        )
        upsert_source_event(database_url, event)
        stats["events_upserted"] += 1
    return stats


def _ingest_msgvault_correspondence(
    settings: Settings,
    *,
    email: str,
    limit: int,
) -> dict[str, int | str]:
    normalized_email = email.strip().lower()
    rows = MsgvaultAdapter(settings).correspondence_messages(normalized_email, limit=limit)
    stats = {
        "source": "msgvault",
        "relationship_email": normalized_email,
        "events_seen": len(rows),
        "events_upserted": 0,
    }
    for row in rows:
        message_id = str(row.get("id") or row.get("source_message_id") or "").strip()
        if not message_id:
            continue
        event = SourceEventIn(
            source_name="msgvault",
            source_event_type="correspondence_message",
            source_event_key=f"msgvault:correspondence:{normalized_email}:{message_id}",
            source_payload=row,
            source_posture=SourcePosture.DIRECT_INTERACTION,
            provenance_status="msgvault_message",
            trust_role="direct email correspondence evidence",
        )
        source_event_id = upsert_source_event(settings.database_url, event)
        upsert_evidence_ref(
            settings.database_url,
            source_event_id=source_event_id,
            ref_type="msgvault_message",
            ref_value=f"{normalized_email}:{message_id}",
            metadata={
                "relationship_email": normalized_email,
                "msgvault_message_id": message_id,
                "source_message_id": row.get("source_message_id"),
                "source_conversation_id": row.get("source_conversation_id"),
            },
        )
        stats["events_upserted"] += 1
    return stats


def _identity_candidate_report(database_url: str) -> dict[str, int | str]:
    report = generate_identity_candidates(database_url)
    report.update(identity_candidate_counts(database_url))
    return report


def _count_table(cur: psycopg.Cursor, table: str) -> int:
    cur.execute(f"SELECT count(*)::int FROM relationship_substrate.{table}")
    return int(cur.fetchone()[0])


def substrate_status(
    database_url: str,
    *,
    organization_worklist_limit: int = 100,
    skipped_domains: set[str] | None = None,
    skipped_system_localparts: set[str] | None = None,
    skipped_system_prefixes: set[str] | None = None,
) -> dict[str, object]:
    counts = substrate_counts(database_url)
    optional_counts: dict[str, int] = {}
    sources: dict[str, dict[str, object]] = {}
    embeddings: dict[str, dict[str, int]] = {}
    tone_state: dict[str, int] = {}
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            for table in [
                "organization",
                "affiliation",
                "relationship_state",
                "research_snapshot",
                "network_packet",
                "network_feedback",
            ]:
                optional_counts[table] = _count_table(cur, table)
            cur.execute(
                """
                SELECT
                  source_name,
                  count(*)::int,
                  max(observed_at)
                FROM relationship_substrate.source_event
                GROUP BY source_name
                ORDER BY source_name
                """
            )
            sources = {
                row[0]: {
                    "total": int(row[1]),
                    "last_observed_at": row[2].isoformat() if row[2] else None,
                }
                for row in cur.fetchall()
            }
            cur.execute(
                """
                SELECT
                  count(*)::int,
                  count(content_embedding)::int
                FROM relationship_substrate.person
                """
            )
            person_total, person_embedded = cur.fetchone()
            cur.execute(
                """
                SELECT
                  count(*)::int,
                  count(content_embedding)::int
                FROM relationship_substrate.organization
                """
            )
            organization_total, organization_embedded = cur.fetchone()
            embeddings = {
                "people": {
                    "total": int(person_total),
                    "embedded": int(person_embedded),
                    "missing": max(int(person_total) - int(person_embedded), 0),
                },
                "organizations": {
                    "total": int(organization_total),
                    "embedded": int(organization_embedded),
                    "missing": max(int(organization_total) - int(organization_embedded), 0),
                },
            }
            cur.execute(
                """
                SELECT count(*)::int
                FROM relationship_substrate.person p
                JOIN relationship_substrate.relationship_edge e
                  ON e.person_id = p.id
                WHERE COALESCE(e.interaction_count, 0) > 0
                AND NOT EXISTS (
                  SELECT 1
                  FROM relationship_substrate.relationship_state rs
                  WHERE rs.person_id = p.id
                  AND rs.state_kind = 'relationship_tone_tenor'
                )
                """
            )
            missing_tone_people = int(cur.fetchone()[0])
            cur.execute(
                """
                SELECT count(*)::int
                FROM relationship_substrate.relationship_state
                WHERE state_kind = 'relationship_tone_tenor'
                """
            )
            persisted_tone_states = int(cur.fetchone()[0])
            tone_state = {
                "persisted_tone_tenor_states": persisted_tone_states,
                "missing_people_count": missing_tone_people,
            }

    organization_worklist = history_backed_organization_worklist(
        database_url,
        limit=organization_worklist_limit,
        skipped_domains=skipped_domains,
        skipped_system_localparts=skipped_system_localparts,
        skipped_system_prefixes=skipped_system_prefixes,
        missing_enrichment_only=True,
    )
    queues = {
        "organization_enrichment": {
            "count": len(organization_worklist),
            "sample": organization_worklist[:5],
        },
        "relationship_tone_tenor_state": {
            "count": tone_state["missing_people_count"],
        },
        "person_embeddings": {
            "count": embeddings["people"]["missing"],
        },
        "organization_embeddings": {
            "count": embeddings["organizations"]["missing"],
        },
    }
    return {
        "status_stage": "relationship_substrate_status",
        "database_url": database_url,
        "counts": {**counts, **optional_counts},
        "sources": sources,
        "embeddings": embeddings,
        "organization_enrichment": {
            "missing_worklist_count": len(organization_worklist),
            "missing_worklist_sample": organization_worklist[:5],
        },
        "research": {
            "snapshots": optional_counts["research_snapshot"],
        },
        "network_packets": {
            "packets": optional_counts["network_packet"],
            "feedback": optional_counts["network_feedback"],
        },
        "tone_state": tone_state,
        "actionable_queues": queues,
        "background_sync": {
            "command": "relationship-substrate run-network-pipeline",
            "bounded": True,
            "resumable": True,
        },
    }


def _check(check_id: str, passed: bool, detail: str) -> dict[str, object]:
    return {"id": check_id, "passed": bool(passed), "detail": detail}


def evaluate_non_ui_workflow(
    database_url: str,
    *,
    packet: dict[str, Any],
    recommendations: list[dict[str, Any]],
    feedback_person_email: str | None,
    feedback_kind: str,
    feedback: dict[str, Any],
) -> dict[str, object]:
    packet_eval = evaluate_ask_network_packet(packet)
    validated_recommendations = validate_ask_network_recommendations(packet, recommendations)
    packet_record = persist_ask_network_packet(database_url, packet)
    feedback_record = record_network_feedback(
        database_url,
        packet_id=packet_record["id"],
        person_email=feedback_person_email,
        feedback_kind=feedback_kind,
        feedback=feedback,
    )
    tone_worklist = tone_state_worklist_from_ask_packet(packet)
    status = substrate_status(database_url)
    people = packet.get("people") or []
    checks = [
        _check(
            "candidate_count",
            bool(people) and int(packet.get("count") or 0) == len(people),
            "Packet returns inspectable candidates.",
        ),
        _check(
            "actual_org_size_evidence",
            all(
                (person.get("organization_context") or {}).get("actual_employee_count_min") is not None
                and (person.get("organization_context") or {}).get("actual_employee_count_max") is not None
                for person in people
            ),
            "Every candidate has actual organization size evidence.",
        ),
        _check(
            "direct_relationship_evidence",
            all(
                int((person.get("evidence_summary") or {}).get("evidence_ref_count") or 0) > 0
                for person in people
            ),
            "Every candidate has direct relationship evidence.",
        ),
        _check(
            "research_refs",
            all(recommendation.get("cited_research_refs") for recommendation in validated_recommendations),
            "Model recommendations cite supplied research refs.",
        ),
        _check(
            "tone_state_readiness",
            tone_worklist["count"] > 0
            or all(
                (person.get("evidence_summary") or {}).get("has_prior_tone_state")
                for person in people
            ),
            "Tone-state worklist exposes missing candidates.",
        ),
        _check(
            "model_recommendation_validation",
            len(validated_recommendations) == len(recommendations),
            "Model recommendations validate against packet candidates and citations.",
        ),
        _check(
            "packet_persistence",
            bool(packet_record.get("id")),
            "Ask-network packet persisted.",
        ),
        _check(
            "feedback_persistence",
            bool(feedback_record.get("id")),
            "Network feedback persisted.",
        ),
        _check(
            "actionable_failures",
            bool((status.get("actionable_queues") or {})),
            "Substrate status exposes actionable queues.",
        ),
    ]
    return {
        "eval_stage": "non_ui_end_to_end_eval",
        "ok": packet_eval["ok"] and all(check["passed"] for check in checks),
        "checks": checks,
        "ask_network_eval": packet_eval,
        "validated_recommendations": validated_recommendations,
        "packet_record": packet_record,
        "feedback_record": feedback_record,
        "tone_state_worklist": tone_worklist,
        "substrate_status": status,
    }


def _materialize_existing(settings: Settings) -> dict[str, object]:
    return {
        "exact_emails": materialize_exact_emails(
            settings.database_url,
            source_name="next_up",
            skipped_domains=set(settings.skipped_sender_domains),
        ),
        "msgvault_senders": materialize_msgvault_senders(settings.database_url),
        "msgvault_correspondence": materialize_msgvault_correspondence(settings.database_url),
        "calendar_events": materialize_calendar_events(
            settings.database_url,
            self_aliases=set(settings.self_email_aliases),
            skipped_domains=set(settings.skipped_sender_domains),
        ),
    }


def _embed_existing_entities(
    database_url: str,
    *,
    embed_texts: EmbedTexts,
    embed_provider: str,
    embed_model: str | None,
    embed_limit: int | None,
) -> dict[str, object]:
    queues = {
        "curated_contacts": embed_curated_contacts(
            database_url,
            embed_texts=embed_texts,
            provider_name=embed_provider,
            model=embed_model,
            limit=embed_limit,
        ),
        "people": embed_missing_people(
            database_url,
            embed_texts=embed_texts,
            provider_name=embed_provider,
            model=embed_model,
            limit=embed_limit,
        ),
        "organizations": embed_missing_organizations(
            database_url,
            embed_texts=embed_texts,
            provider_name=embed_provider,
            model=embed_model,
            limit=embed_limit,
        ),
    }
    return {
        "source": "substrate_entities",
        "provider": embed_provider,
        "model": embed_model or "",
        "candidates": sum(int(result.get("candidates") or 0) for result in queues.values()),
        "embedded": sum(int(result.get("embedded") or 0) for result in queues.values()),
        "queues": queues,
    }


def run_autonomous_backfill(
    settings: Settings,
    *,
    output_dir: Path,
    max_iterations: int = 1,
    sleep_seconds: int = 0,
    skip_embeddings: bool = False,
    embed_texts: EmbedTexts | None = None,
    embed_provider: str = "ollama",
    embed_model: str | None = None,
    embed_limit: int | None = 500,
    organization_worklist_limit: int = 100,
    north_star_limit: int = 25,
    north_star_semantic_query: str = DEFAULT_NORTH_STAR_SEMANTIC_QUERY,
) -> dict[str, object]:
    if max_iterations < 1:
        raise ValueError("max_iterations must be at least 1")
    run_started_at = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = output_dir / run_started_at
    run_migrations(settings.database_url)
    iterations: list[dict[str, object]] = []
    final_status: dict[str, object] | None = None
    for index in range(max_iterations):
        iteration_started_at = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        iteration_dir = run_dir / f"iteration-{index + 1:03d}-{iteration_started_at}"
        artifacts: dict[str, str] = {}
        materialization = _materialize_existing(settings)
        embedding_result: dict[str, object] = {"skipped": True}
        semantic_query_embedding = None
        if not skip_embeddings and embed_texts is not None:
            embedding_result = _embed_existing_entities(
                settings.database_url,
                embed_texts=embed_texts,
                embed_provider=embed_provider,
                embed_model=embed_model,
                embed_limit=embed_limit,
            )
            semantic_query_embedding = embed_texts([north_star_semantic_query])[0]
        status = substrate_status(
            settings.database_url,
            organization_worklist_limit=organization_worklist_limit,
            skipped_domains=set(settings.skipped_sender_domains),
            skipped_system_localparts=set(settings.skipped_system_localparts),
            skipped_system_prefixes=set(settings.skipped_system_prefixes),
        )
        ask_packet = prepare_ask_network_packet(
            settings.database_url,
            goal=north_star_semantic_query,
            actual_employee_count_min=10,
            actual_employee_count_max=20,
            consultant_count_min=10,
            consultant_count_max=20,
            semantic_query=north_star_semantic_query if semantic_query_embedding is not None else None,
            semantic_query_embedding=semantic_query_embedding,
            semantic_provider=embed_provider if semantic_query_embedding is not None else None,
            embedding_model=embed_model if semantic_query_embedding is not None else None,
            sort="semantic" if semantic_query_embedding is not None else "relationship",
            limit=north_star_limit,
        )
        tone_worklist = tone_state_worklist_from_ask_packet(ask_packet)
        artifacts["status"] = _write_json(iteration_dir / "substrate_status.json", status)
        artifacts["ask_network_packet"] = _write_json(iteration_dir / "ask_network_packet.json", ask_packet)
        artifacts["tone_state_worklist"] = _write_json(
            iteration_dir / "tone_state_worklist.json",
            tone_worklist,
        )
        iteration_report = {
            "iteration": index + 1,
            "started_at": iteration_started_at,
            "materialization": materialization,
            "embeddings": embedding_result,
            "status": {
                "person_embedding_missing": (
                    (status.get("embeddings") or {}).get("people") or {}
                ).get("missing"),
                "organization_enrichment_missing": (
                    status.get("organization_enrichment") or {}
                ).get("missing_worklist_count"),
                "tone_state_missing_people": (status.get("tone_state") or {}).get("missing_people_count"),
            },
            "ask_network_count": ask_packet["count"],
            "tone_worklist_count": tone_worklist["count"],
            "artifacts": artifacts,
        }
        artifacts["iteration_report"] = _write_json(iteration_dir / "iteration_report.json", iteration_report)
        iterations.append(iteration_report)
        final_status = status
        if (
            not skip_embeddings
            and embed_texts is not None
            and int(embedding_result.get("candidates") or 0) == 0
        ):
            break
        if index + 1 < max_iterations and sleep_seconds > 0:
            time.sleep(sleep_seconds)
    report = {
        "ok": True,
        "run_started_at": run_started_at,
        "iterations_completed": len(iterations),
        "output_dir": str(run_dir),
        "iterations": iterations,
        "final_status": final_status or substrate_status(settings.database_url),
    }
    report["artifact"] = _write_json(run_dir / "autonomous_backfill_report.json", report)
    return report


def run_network_pipeline(
    settings: Settings,
    *,
    next_up_paths: list[Path],
    calendar_paths: list[Path],
    output_dir: Path,
    create_database: bool = True,
    sender_limit: int = 500,
    correspondence_from_senders: int = 25,
    correspondence_message_limit: int = 50,
    skip_msgvault: bool = False,
    skip_embeddings: bool = False,
    embed_texts: EmbedTexts | None = None,
    embed_provider: str = "ollama",
    embed_model: str | None = None,
    embed_limit: int | None = 500,
    organization_worklist_limit: int = 100,
    north_star_limit: int = 25,
    north_star_semantic_query: str = DEFAULT_NORTH_STAR_SEMANTIC_QUERY,
) -> dict[str, object]:
    run_started_at = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = output_dir / run_started_at
    artifacts: dict[str, str] = {}

    database = ensure_database_exists(settings.database_url) if create_database else {"checked": False}
    run_migrations(settings.database_url)

    next_up_ingestions = [_ingest_next_up(settings.database_url, path) for path in next_up_paths]
    artifacts["next_up_ingestions"] = _write_json(run_dir / "next_up_ingestions.json", next_up_ingestions)
    exact_materialization = materialize_exact_emails(
        settings.database_url,
        source_name="next_up",
        skipped_domains=set(settings.skipped_sender_domains),
    )

    msgvault: dict[str, object] = {"skipped": skip_msgvault}
    if not skip_msgvault:
        adapter = MsgvaultAdapter(settings)
        sender_rows = adapter.top_sender_candidates(sender_limit)
        domain_rows = adapter.top_domain_candidates(sender_limit)
        msgvault_profile = {"senders": sender_rows, "domains": domain_rows}
        artifacts["msgvault_profile"] = _write_json(run_dir / "msgvault_profile.json", msgvault_profile)
        sender_ingestion = _ingest_msgvault_sender_rows(
            settings.database_url,
            sender_rows,
            self_aliases=set(settings.self_email_aliases),
            skipped_domains=set(settings.skipped_sender_domains),
            skipped_system_localparts=set(settings.skipped_system_localparts),
            skipped_system_prefixes=set(settings.skipped_system_prefixes),
        )
        sender_materialization = materialize_msgvault_senders(settings.database_url)
        seed_emails = select_correspondence_seed_emails(
            sender_rows,
            limit=correspondence_from_senders,
            self_aliases=set(settings.self_email_aliases),
            skipped_domains=set(settings.skipped_sender_domains),
            skipped_system_localparts=set(settings.skipped_system_localparts),
            skipped_system_prefixes=set(settings.skipped_system_prefixes),
        )
        correspondence_ingestions = [
            _ingest_msgvault_correspondence(
                settings,
                email=email,
                limit=correspondence_message_limit,
            )
            for email in seed_emails
        ]
        artifacts["msgvault_correspondence_ingestions"] = _write_json(
            run_dir / "msgvault_correspondence_ingestions.json",
            correspondence_ingestions,
        )
        correspondence_materialization = materialize_msgvault_correspondence(settings.database_url)
        msgvault = {
            "skipped": False,
            "sender_candidates": len(sender_rows),
            "domain_candidates": len(domain_rows),
            "sender_ingestion": sender_ingestion,
            "sender_materialization": sender_materialization,
            "correspondence_seed_emails": seed_emails,
            "correspondence_ingestions": correspondence_ingestions,
            "correspondence_materialization": correspondence_materialization,
        }

    calendar_ingestions = [_ingest_calendar(settings.database_url, path) for path in calendar_paths]
    calendar_materialization = materialize_calendar_events(
        settings.database_url,
        self_aliases=set(settings.self_email_aliases),
        skipped_domains=set(settings.skipped_sender_domains),
    )
    artifacts["calendar_ingestions"] = _write_json(run_dir / "calendar_ingestions.json", calendar_ingestions)

    identity_candidates = _identity_candidate_report(settings.database_url)

    embedding_result: dict[str, object] = {"skipped": skip_embeddings}
    semantic_query_embedding = None
    if not skip_embeddings and embed_texts is not None:
        embedding_result = _embed_existing_entities(
            settings.database_url,
            embed_texts=embed_texts,
            embed_provider=embed_provider,
            embed_model=embed_model,
            embed_limit=embed_limit,
        )
        semantic_query_embedding = embed_texts([north_star_semantic_query])[0]

    organization_worklist = history_backed_organization_worklist(
        settings.database_url,
        limit=organization_worklist_limit,
        skipped_domains=set(settings.skipped_sender_domains),
        skipped_system_localparts=set(settings.skipped_system_localparts),
        skipped_system_prefixes=set(settings.skipped_system_prefixes),
        missing_enrichment_only=True,
    )
    artifacts["organization_enrichment_worklist"] = _write_json(
        run_dir / "organization_enrichment_worklist.json",
        organization_worklist,
    )

    north_star_results = search_people(
        settings.database_url,
        role_keywords=DEFAULT_ROLE_KEYWORDS,
        actual_employee_count_min=10,
        actual_employee_count_max=20,
        consultant_count_min=10,
        consultant_count_max=20,
        semantic_query_embedding=semantic_query_embedding,
        sort="semantic" if semantic_query_embedding is not None else "relationship",
        limit=north_star_limit,
    )
    north_star_query = {
        "query": {
            "role_keywords": DEFAULT_ROLE_KEYWORDS,
            "actual_employee_count_min": 10,
            "actual_employee_count_max": 20,
            "consultant_count_min": 10,
            "consultant_count_max": 20,
            "semantic_query": north_star_semantic_query if semantic_query_embedding is not None else None,
            "sort": "semantic" if semantic_query_embedding is not None else "relationship",
            "limit": north_star_limit,
        },
        "count": len(north_star_results),
        "results": north_star_results,
    }
    artifacts["north_star_query"] = _write_json(run_dir / "north_star_query.json", north_star_query)

    history_backed_north_star_results = search_history_backed_people(
        settings.database_url,
        actual_employee_count_min=10,
        actual_employee_count_max=20,
        consultant_count_min=10,
        consultant_count_max=20,
        limit=north_star_limit,
    )
    history_backed_north_star_query = {
        "query": {
            "actual_employee_count_min": 10,
            "actual_employee_count_max": 20,
            "consultant_count_min": 10,
            "consultant_count_max": 20,
            "limit": north_star_limit,
            "evidence_surface": "msgvault_calendar_history_by_email_domain",
        },
        "count": len(history_backed_north_star_results),
        "results": history_backed_north_star_results,
    }
    artifacts["history_backed_north_star_query"] = _write_json(
        run_dir / "history_backed_north_star_query.json",
        history_backed_north_star_query,
    )

    operating_picture = operating_picture_rows(settings.database_url, limit=north_star_limit)
    artifacts["operating_picture"] = _write_json(run_dir / "operating_picture.json", operating_picture)

    report: dict[str, object] = {
        "ok": True,
        "run_started_at": run_started_at,
        "database_url": settings.database_url,
        "database": database,
        "next_up": {
            "paths": [str(path) for path in next_up_paths],
            "ingestions": next_up_ingestions,
            "materialization": exact_materialization,
        },
        "msgvault": msgvault,
        "calendar": {
            "paths": [str(path) for path in calendar_paths],
            "ingestions": calendar_ingestions,
            "materialization": calendar_materialization,
        },
        "identity_candidates": identity_candidates,
        "embeddings": embedding_result,
        "organization_worklist": {
            "count": len(organization_worklist),
            "artifact": artifacts["organization_enrichment_worklist"],
        },
        "north_star_query": {
            "count": len(north_star_results),
            "artifact": artifacts["north_star_query"],
        },
        "history_backed_north_star_query": {
            "count": len(history_backed_north_star_results),
            "artifact": artifacts["history_backed_north_star_query"],
        },
        "operating_picture": {
            "count": len(operating_picture),
            "artifact": artifacts["operating_picture"],
        },
        "counts": substrate_counts(settings.database_url),
        "artifacts": artifacts,
        "checks": [
            "Next Up remains curated/context evidence, not relationship health.",
            "msgvault sender and correspondence ingestion skips configured self/internal domains.",
            "Correspondence seeds are selected mechanically from sender counts after skip rules.",
            "Organization enrichment worklist is evidence-ranked and model/research-ready.",
            "North Star query uses explicit organization enrichment filters for actual size/team size.",
            "History-backed North Star query searches msgvault/calendar people by enriched email-domain organizations.",
        ],
    }
    artifacts["report"] = _write_json(run_dir / "pipeline_report.json", report)
    report["artifacts"] = artifacts
    return report
