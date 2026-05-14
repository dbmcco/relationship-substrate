from __future__ import annotations

import argparse
import json
from pathlib import Path

from relationship_substrate.adapters.calendar import iter_calendar_json_events
from relationship_substrate.adapters.next_up import iter_next_up_events
from relationship_substrate.adapters.msgvault import MsgvaultAdapter
from relationship_substrate.config import Settings
from relationship_substrate.contracts import SourceEventIn, SourcePosture
from relationship_substrate.db import run_migrations
from relationship_substrate.dossiers import get_person_dossier
from relationship_substrate.embeddings import (
    DEFAULT_OLLAMA_EMBEDDING_MODEL,
    DEFAULT_OPENAI_EMBEDDING_MODEL,
    embed_curated_contacts,
    hash_embed_texts,
    ollama_embed_texts,
    openai_embed_texts,
)
from relationship_substrate.identity import (
    generate_identity_candidates,
    get_identity_candidate,
    list_identity_candidates,
    resolve_identity_candidate,
)
from relationship_substrate.materialize import (
    materialize_calendar_events,
    materialize_exact_emails,
    materialize_msgvault_correspondence,
    materialize_msgvault_senders,
)
from relationship_substrate.organizations import (
    history_backed_organization_worklist,
    import_organization_enrichments,
    organization_enrichment_worklist,
    upsert_organization_enrichment,
)
from relationship_substrate.operations import run_network_pipeline
from relationship_substrate.outreach import prepare_outreach_proposal_packet, validate_outreach_proposal
from relationship_substrate.relationship_intelligence import (
    persist_relationship_state,
    prepare_relationship_intelligence_packet,
    prepare_relationship_tone_tenor_analysis_packet,
)
from relationship_substrate.repositories import (
    identity_candidate_counts,
    operating_picture_rows,
    substrate_counts,
    upsert_evidence_ref,
    upsert_source_event,
)
from relationship_substrate.search import DEFAULT_ROLE_KEYWORDS, search_history_backed_people, search_people


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="relationship-substrate")
    parser.add_argument("--version", action="store_true")
    parser.add_argument("--database-url", default=None)
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("migrate")
    profile = subparsers.add_parser("profile-msgvault")
    profile.add_argument("--limit", type=int, default=25)
    profile.add_argument("--kind", choices=["senders", "domains", "both"], default="senders")
    ingest_msgvault = subparsers.add_parser("ingest-msgvault-senders")
    ingest_msgvault.add_argument("--limit", type=int, default=100)
    ingest_msgvault.add_argument("--include-self", action="store_true")
    ingest_msgvault_correspondence = subparsers.add_parser("ingest-msgvault-correspondence")
    ingest_msgvault_correspondence.add_argument("--email", required=True)
    ingest_msgvault_correspondence.add_argument("--limit", type=int, default=50)
    ingest = subparsers.add_parser("ingest-next-up")
    ingest.add_argument("--path", required=True)
    ingest_calendar = subparsers.add_parser("ingest-calendar")
    ingest_calendar.add_argument("--path", required=True)
    materialize = subparsers.add_parser("materialize-exact-emails")
    materialize.add_argument("--source", default="next_up")
    subparsers.add_parser("materialize-msgvault-senders")
    subparsers.add_parser("materialize-msgvault-correspondence")
    subparsers.add_parser("materialize-calendar-events")
    subparsers.add_parser("generate-identity-candidates")
    list_candidates = subparsers.add_parser("list-identity-candidates")
    list_candidates.add_argument(
        "--status",
        choices=["candidate", "accepted", "rejected", "superseded"],
        default="candidate",
    )
    list_candidates.add_argument("--limit", type=int, default=25)
    show_candidate = subparsers.add_parser("show-identity-candidate")
    show_candidate.add_argument("--id", required=True)
    resolve_candidate = subparsers.add_parser("resolve-identity-candidate")
    resolve_candidate.add_argument("--id", required=True)
    resolve_candidate.add_argument(
        "--status",
        choices=["accepted", "rejected", "superseded", "candidate"],
        required=True,
    )
    resolve_candidate.add_argument("--note", required=True)
    show_person = subparsers.add_parser("show-person")
    show_person.add_argument("--email", required=True)
    prepare_intelligence = subparsers.add_parser("prepare-relationship-intelligence")
    prepare_intelligence.add_argument("--email", required=True)
    prepare_intelligence.add_argument("--evidence-limit", type=int, default=10)
    prepare_tone_analysis = subparsers.add_parser("prepare-relationship-tone-analysis")
    prepare_tone_analysis.add_argument("--email", action="append", required=True)
    prepare_tone_analysis.add_argument("--evidence-limit", type=int, default=10)
    prepare_tone_analysis.add_argument("--prior-state-limit", type=int, default=3)
    prepare_outreach = subparsers.add_parser("prepare-outreach-proposal")
    prepare_outreach.add_argument("--email", action="append", required=True)
    prepare_outreach.add_argument("--research-context", default=None)
    prepare_outreach.add_argument("--model-proposal", default=None)
    prepare_outreach.add_argument("--evidence-limit", type=int, default=10)
    persist_state = subparsers.add_parser("persist-relationship-state")
    persist_state.add_argument("--email", required=True)
    persist_state.add_argument("--proposal", required=True)
    search = subparsers.add_parser("search-people")
    search.add_argument("--role-keywords", default=",".join(DEFAULT_ROLE_KEYWORDS))
    search.add_argument("--known-people-at-company-min", "--company-size-min", type=int, default=None)
    search.add_argument("--known-people-at-company-max", "--company-size-max", type=int, default=None)
    search.add_argument("--actual-employee-count-min", type=int, default=None)
    search.add_argument("--actual-employee-count-max", type=int, default=None)
    search.add_argument("--consultant-count-min", type=int, default=None)
    search.add_argument("--consultant-count-max", type=int, default=None)
    search.add_argument("--semantic-query", default=None)
    search.add_argument("--semantic-provider", choices=["ollama", "openai", "hash"], default="ollama")
    search.add_argument("--embedding-model", default=None)
    search.add_argument("--sort", choices=["relationship", "semantic"], default=None)
    search.add_argument("--limit", type=int, default=25)
    history_search = subparsers.add_parser("search-history-backed-people")
    history_search.add_argument("--actual-employee-count-min", type=int, default=None)
    history_search.add_argument("--actual-employee-count-max", type=int, default=None)
    history_search.add_argument("--consultant-count-min", type=int, default=None)
    history_search.add_argument("--consultant-count-max", type=int, default=None)
    history_search.add_argument("--limit", type=int, default=25)
    embed = subparsers.add_parser("embed-curated-contacts")
    embed.add_argument("--provider", choices=["ollama", "openai", "hash"], default="ollama")
    embed.add_argument("--model", default=None)
    embed.add_argument("--limit", type=int, default=None)
    org = subparsers.add_parser("upsert-organization-enrichment")
    org.add_argument("--company", required=True)
    org.add_argument("--company-type", default=None)
    org.add_argument("--employee-count-min", type=int, default=None)
    org.add_argument("--employee-count-max", type=int, default=None)
    org.add_argument("--employee-count-label", default=None)
    org.add_argument("--consultant-count-estimate", type=int, default=None)
    org.add_argument("--source-name", required=True)
    org.add_argument("--source-url", default=None)
    org.add_argument("--provenance-status", default="external_research")
    org_worklist = subparsers.add_parser("export-organization-enrichment-worklist")
    org_worklist.add_argument("--limit", type=int, default=50)
    org_history_worklist = subparsers.add_parser("export-history-backed-organization-worklist")
    org_history_worklist.add_argument("--limit", type=int, default=50)
    org_history_worklist.add_argument("--missing-only", action="store_true")
    org_import = subparsers.add_parser("import-organization-enrichments")
    org_import.add_argument("--path", required=True)
    export = subparsers.add_parser("export-operating-picture")
    export.add_argument("--from-db", action="store_true")
    export.add_argument("--limit", type=int, default=25)
    eval_local = subparsers.add_parser("eval-local")
    eval_local.add_argument("--next-up-path", required=True)
    eval_local.add_argument("--calendar-path", default=None)
    eval_local.add_argument("--output-dir", default="output/eval")
    eval_local.add_argument("--limit", type=int, default=25)
    eval_local.add_argument("--skip-msgvault", action="store_true")
    pipeline = subparsers.add_parser("run-network-pipeline")
    pipeline.add_argument("--next-up-path", action="append", required=True)
    pipeline.add_argument("--calendar-path", action="append", default=[])
    pipeline.add_argument("--output-dir", default="output/ops")
    pipeline.add_argument("--no-create-database", action="store_true")
    pipeline.add_argument("--sender-limit", type=int, default=500)
    pipeline.add_argument("--correspondence-from-senders", type=int, default=25)
    pipeline.add_argument("--correspondence-message-limit", type=int, default=50)
    pipeline.add_argument("--skip-msgvault", action="store_true")
    pipeline.add_argument("--skip-embeddings", action="store_true")
    pipeline.add_argument("--embed-provider", choices=["ollama", "openai", "hash"], default="ollama")
    pipeline.add_argument("--embedding-model", default=None)
    pipeline.add_argument("--embed-limit", type=int, default=500)
    pipeline.add_argument("--organization-worklist-limit", type=int, default=100)
    pipeline.add_argument("--north-star-limit", type=int, default=25)
    pipeline.add_argument("--north-star-semantic-query", default=None)
    return parser


def _settings(args: argparse.Namespace) -> Settings:
    settings = Settings()
    if args.database_url:
        return Settings(
            database_url=args.database_url,
            msgvault_binary=settings.msgvault_binary,
            msgvault_home=settings.msgvault_home,
            msgvault_config=settings.msgvault_config,
            self_email_aliases=settings.self_email_aliases,
            skipped_sender_domains=settings.skipped_sender_domains,
            skipped_system_localparts=settings.skipped_system_localparts,
            skipped_system_prefixes=settings.skipped_system_prefixes,
        )
    return settings


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _comma_separated(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _embedding_model(provider: str, model: str | None) -> str:
    if model:
        return model
    if provider == "openai":
        return DEFAULT_OPENAI_EMBEDDING_MODEL
    if provider == "ollama":
        return DEFAULT_OLLAMA_EMBEDDING_MODEL
    return "hash"


def _embedding_function(provider: str, *, model: str | None):
    if provider == "hash":
        return hash_embed_texts
    resolved_model = _embedding_model(provider, model)
    if provider == "ollama":
        return lambda texts: ollama_embed_texts(texts, model=resolved_model)
    return lambda texts: openai_embed_texts(texts, model=resolved_model)


def ingest_next_up(database_url: str, path: Path) -> dict[str, int | str]:
    run_migrations(database_url)
    events_seen = 0
    events_upserted = 0
    for event in iter_next_up_events(path):
        events_seen += 1
        upsert_source_event(database_url, event)
        events_upserted += 1
    return {"source": "next_up", "events_seen": events_seen, "events_upserted": events_upserted}


def ingest_calendar(database_url: str, path: Path) -> dict[str, int | str]:
    run_migrations(database_url)
    events_seen = 0
    events_upserted = 0
    for event in iter_calendar_json_events(path):
        events_seen += 1
        source_event_id = upsert_source_event(database_url, event)
        upsert_evidence_ref(
            database_url,
            source_event_id=source_event_id,
            ref_type="calendar_event",
            ref_value=event.source_event_key,
            metadata={"path": str(path)},
        )
        events_upserted += 1
    return {"source": "calendar", "events_seen": events_seen, "events_upserted": events_upserted}


def profile_msgvault(settings: Settings, *, limit: int, kind: str) -> dict[str, object]:
    adapter = MsgvaultAdapter(settings)
    payload: dict[str, object] = {}
    if kind in ("senders", "both"):
        payload["senders"] = adapter.top_sender_candidates(limit)
    if kind in ("domains", "both"):
        payload["domains"] = adapter.top_domain_candidates(limit)
    return payload


def ingest_msgvault_sender_rows(
    database_url: str,
    rows: list[dict[str, object]],
    *,
    self_aliases: set[str],
    skipped_domains: set[str],
    skipped_system_localparts: set[str] | None = None,
    skipped_system_prefixes: set[str] | None = None,
) -> dict[str, int | str]:
    run_migrations(database_url)
    stats = {
        "source": "msgvault",
        "events_seen": len(rows),
        "events_upserted": 0,
        "skipped_self": 0,
        "skipped_domain": 0,
        "skipped_system": 0,
        "skipped_missing_email": 0,
    }
    skipped_system_localparts = skipped_system_localparts or set()
    skipped_system_prefixes = skipped_system_prefixes or set()
    for row in rows:
        raw_email = row.get("email")
        email = str(raw_email or "").strip().lower()
        if not email:
            stats["skipped_missing_email"] += 1
            continue
        if email in self_aliases:
            stats["skipped_self"] += 1
            continue
        domain = email.rsplit("@", 1)[-1]
        if domain in skipped_domains:
            stats["skipped_domain"] += 1
            continue
        localpart = email.split("@", 1)[0]
        normalized_localpart = localpart.replace(".", "-").replace("_", "-").lower()
        if localpart in skipped_system_localparts or any(
            normalized_localpart.startswith(prefix) for prefix in skipped_system_prefixes
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


def ingest_msgvault_senders(
    settings: Settings,
    *,
    limit: int,
    include_self: bool,
) -> dict[str, int | str]:
    rows = MsgvaultAdapter(settings).top_sender_candidates(limit)
    self_aliases = set() if include_self else set(settings.self_email_aliases)
    skipped_domains = set() if include_self else set(settings.skipped_sender_domains)
    return ingest_msgvault_sender_rows(
        settings.database_url,
        rows,
        self_aliases=self_aliases,
        skipped_domains=skipped_domains,
        skipped_system_localparts=set(settings.skipped_system_localparts),
        skipped_system_prefixes=set(settings.skipped_system_prefixes),
    )


def ingest_msgvault_correspondence(
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


def operating_picture_from_db(database_url: str, *, limit: int) -> dict:
    from relationship_substrate.read_models import build_relationship_operating_picture

    return build_relationship_operating_picture(operating_picture_rows(database_url, limit=limit))


def generate_identity_candidate_report(database_url: str) -> dict[str, int | str]:
    run_migrations(database_url)
    report = generate_identity_candidates(database_url)
    report.update(identity_candidate_counts(database_url))
    return report


def run_local_eval(
    settings: Settings,
    *,
    next_up_path: Path,
    calendar_path: Path | None,
    output_dir: Path,
    limit: int,
    skip_msgvault: bool,
) -> dict:
    run_migrations(settings.database_url)
    next_up = ingest_next_up(settings.database_url, next_up_path)
    materialization = materialize_exact_emails(
        settings.database_url,
        source_name="next_up",
        skipped_domains=set(settings.skipped_sender_domains),
    )
    msgvault = {}
    msgvault_materialization: dict[str, int | str] = {
        "source": "msgvault",
        "events_seen": 0,
        "materialized": 0,
        "skipped_missing_email": 0,
    }
    if not skip_msgvault:
        msgvault = profile_msgvault(settings, limit=limit, kind="both")
        sender_ingestion = ingest_msgvault_sender_rows(
            settings.database_url,
            msgvault.get("senders", []),
            self_aliases=set(settings.self_email_aliases),
            skipped_domains=set(settings.skipped_sender_domains),
            skipped_system_localparts=set(settings.skipped_system_localparts),
            skipped_system_prefixes=set(settings.skipped_system_prefixes),
        )
        msgvault_materialization = materialize_msgvault_senders(settings.database_url)
        msgvault["sender_ingestion"] = sender_ingestion
    calendar = {
        "skipped": calendar_path is None,
        "ingestion": {"source": "calendar", "events_seen": 0, "events_upserted": 0},
        "materialization": {
            "source": "calendar",
            "events_seen": 0,
            "materialized_events": 0,
            "attendees_materialized": 0,
            "skipped_self": 0,
            "skipped_domain": 0,
            "skipped_missing_email": 0,
            "skipped_existing": 0,
        },
    }
    if calendar_path is not None:
        calendar["ingestion"] = ingest_calendar(settings.database_url, calendar_path)
        calendar["materialization"] = materialize_calendar_events(
            settings.database_url,
            self_aliases=set(settings.self_email_aliases),
            skipped_domains=set(settings.skipped_sender_domains),
        )
    identity_candidates = generate_identity_candidate_report(settings.database_url)
    picture = operating_picture_from_db(settings.database_url, limit=limit)
    counts = substrate_counts(settings.database_url)
    report = {
        "ok": True,
        "database_url": settings.database_url,
        "next_up": next_up,
        "materialization": materialization,
        "msgvault_materialization": msgvault_materialization,
        "operating_picture": {
            "relationships": len(picture["relationships"]),
            "path": str(output_dir / "relationship_operating_picture.json"),
        },
        "msgvault": {
            "skipped": skip_msgvault,
            "sender_candidates": len(msgvault.get("senders", [])) if msgvault else 0,
            "domain_candidates": len(msgvault.get("domains", [])) if msgvault else 0,
            "sender_ingestion": msgvault.get("sender_ingestion", {}) if msgvault else {},
        },
        "identity_candidates": identity_candidates,
        "calendar": calendar,
        "counts": counts,
        "checks": [
            "Next Up events retain curated_export + unknown_upstream provenance.",
            "Exact-email materialization only creates canonical person/contact_channel records.",
            "Operating picture remains uninterpreted; no relationship-health scoring is performed.",
            "msgvault profiling uses supported read-only analytics commands.",
            "Known self email aliases are skipped before sender profiles become relationship edges.",
            "Known automated/system sender patterns are skipped before sender profiles become relationship edges.",
            "Identity candidates are generated as unresolved review suggestions; no automatic person merges are performed.",
            "Calendar events materialize attendee evidence and update relationship edges without relationship-health interpretation.",
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "relationship_operating_picture.json").write_text(
        json.dumps(picture, indent=2, sort_keys=True) + "\n"
    )
    (output_dir / "eval_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    settings = _settings(args)
    if args.version:
        from relationship_substrate import __version__

        print(__version__)
        return 0
    if args.command == "migrate":
        run_migrations(settings.database_url)
        _print_json({"migrated": True, "database_url": settings.database_url})
        return 0
    if args.command == "profile-msgvault":
        _print_json(profile_msgvault(settings, limit=args.limit, kind=args.kind))
        return 0
    if args.command == "ingest-msgvault-senders":
        _print_json(
            ingest_msgvault_senders(
                settings,
                limit=args.limit,
                include_self=args.include_self,
            )
        )
        return 0
    if args.command == "ingest-msgvault-correspondence":
        run_migrations(settings.database_url)
        _print_json(ingest_msgvault_correspondence(settings, email=args.email, limit=args.limit))
        return 0
    if args.command == "ingest-next-up":
        _print_json(ingest_next_up(settings.database_url, Path(args.path)))
        return 0
    if args.command == "ingest-calendar":
        _print_json(ingest_calendar(settings.database_url, Path(args.path)))
        return 0
    if args.command == "materialize-exact-emails":
        run_migrations(settings.database_url)
        _print_json(
            materialize_exact_emails(
                settings.database_url,
                source_name=args.source,
                skipped_domains=set(settings.skipped_sender_domains),
            )
        )
        return 0
    if args.command == "materialize-msgvault-senders":
        run_migrations(settings.database_url)
        _print_json(materialize_msgvault_senders(settings.database_url))
        return 0
    if args.command == "materialize-msgvault-correspondence":
        run_migrations(settings.database_url)
        _print_json(materialize_msgvault_correspondence(settings.database_url))
        return 0
    if args.command == "materialize-calendar-events":
        run_migrations(settings.database_url)
        _print_json(
            materialize_calendar_events(
                settings.database_url,
                self_aliases=set(settings.self_email_aliases),
                skipped_domains=set(settings.skipped_sender_domains),
            )
        )
        return 0
    if args.command == "generate-identity-candidates":
        _print_json(generate_identity_candidate_report(settings.database_url))
        return 0
    if args.command == "list-identity-candidates":
        candidates = list_identity_candidates(settings.database_url, status=args.status, limit=args.limit)
        _print_json({"candidates": candidates, "count": len(candidates)})
        return 0
    if args.command == "show-identity-candidate":
        _print_json(get_identity_candidate(settings.database_url, args.id))
        return 0
    if args.command == "resolve-identity-candidate":
        _print_json(
            resolve_identity_candidate(
                settings.database_url,
                args.id,
                status=args.status,
                note=args.note,
            )
        )
        return 0
    if args.command == "show-person":
        _print_json(get_person_dossier(settings.database_url, email=args.email))
        return 0
    if args.command == "prepare-relationship-intelligence":
        run_migrations(settings.database_url)
        _print_json(
            prepare_relationship_intelligence_packet(
                settings.database_url,
                email=args.email,
                evidence_limit=args.evidence_limit,
            )
        )
        return 0
    if args.command == "prepare-relationship-tone-analysis":
        run_migrations(settings.database_url)
        _print_json(
            prepare_relationship_tone_tenor_analysis_packet(
                settings.database_url,
                emails=args.email,
                evidence_limit=args.evidence_limit,
                prior_state_limit=args.prior_state_limit,
            )
        )
        return 0
    if args.command == "prepare-outreach-proposal":
        run_migrations(settings.database_url)
        research_context = None
        if args.research_context:
            research_context = json.loads(Path(args.research_context).read_text(encoding="utf-8"))
        packet = prepare_outreach_proposal_packet(
            settings.database_url,
            emails=args.email,
            research_context=research_context,
            evidence_limit=args.evidence_limit,
        )
        if args.model_proposal:
            proposal = json.loads(Path(args.model_proposal).read_text(encoding="utf-8"))
            packet["model_proposal_validation"] = {
                "valid": True,
                "proposal": validate_outreach_proposal(packet, proposal),
            }
        _print_json(packet)
        return 0
    if args.command == "persist-relationship-state":
        run_migrations(settings.database_url)
        proposal = json.loads(Path(args.proposal).read_text(encoding="utf-8"))
        _print_json(persist_relationship_state(settings.database_url, email=args.email, proposal=proposal))
        return 0
    if args.command == "embed-curated-contacts":
        run_migrations(settings.database_url)
        _print_json(
            embed_curated_contacts(
                settings.database_url,
                embed_texts=_embedding_function(args.provider, model=args.model),
                provider_name=args.provider,
                model=_embedding_model(args.provider, args.model),
                limit=args.limit,
            )
        )
        return 0
    if args.command == "upsert-organization-enrichment":
        run_migrations(settings.database_url)
        _print_json(
            upsert_organization_enrichment(
                settings.database_url,
                company_name=args.company,
                company_type=args.company_type,
                employee_count_min=args.employee_count_min,
                employee_count_max=args.employee_count_max,
                employee_count_label=args.employee_count_label,
                consultant_count_estimate=args.consultant_count_estimate,
                source_name=args.source_name,
                source_url=args.source_url,
                provenance_status=args.provenance_status,
            )
        )
        return 0
    if args.command == "export-organization-enrichment-worklist":
        run_migrations(settings.database_url)
        companies = organization_enrichment_worklist(settings.database_url, limit=args.limit)
        _print_json({"count": len(companies), "companies": companies})
        return 0
    if args.command == "export-history-backed-organization-worklist":
        run_migrations(settings.database_url)
        companies = history_backed_organization_worklist(
            settings.database_url,
            limit=args.limit,
            skipped_domains=set(settings.skipped_sender_domains),
            skipped_system_localparts=set(settings.skipped_system_localparts),
            skipped_system_prefixes=set(settings.skipped_system_prefixes),
            missing_enrichment_only=args.missing_only,
        )
        _print_json({"count": len(companies), "companies": companies})
        return 0
    if args.command == "import-organization-enrichments":
        run_migrations(settings.database_url)
        records = json.loads(Path(args.path).read_text(encoding="utf-8"))
        if not isinstance(records, list):
            records = [records]
        _print_json(import_organization_enrichments(settings.database_url, records))
        return 0
    if args.command == "search-people":
        semantic_query_embedding = None
        if args.semantic_query:
            semantic_query_embedding = _embedding_function(
                args.semantic_provider,
                model=args.embedding_model,
            )([args.semantic_query])[0]
        results = search_people(
            settings.database_url,
            role_keywords=_comma_separated(args.role_keywords),
            known_people_at_company_min=args.known_people_at_company_min,
            known_people_at_company_max=args.known_people_at_company_max,
            actual_employee_count_min=args.actual_employee_count_min,
            actual_employee_count_max=args.actual_employee_count_max,
            consultant_count_min=args.consultant_count_min,
            consultant_count_max=args.consultant_count_max,
            semantic_query_embedding=semantic_query_embedding,
            sort=args.sort,
            limit=args.limit,
        )
        _print_json(
            {
                "query": {
                    "role_keywords": _comma_separated(args.role_keywords),
                    "known_people_at_company_min": args.known_people_at_company_min,
                    "known_people_at_company_max": args.known_people_at_company_max,
                    "actual_employee_count_min": args.actual_employee_count_min,
                    "actual_employee_count_max": args.actual_employee_count_max,
                    "consultant_count_min": args.consultant_count_min,
                    "consultant_count_max": args.consultant_count_max,
                    "semantic_query": args.semantic_query,
                    "semantic_provider": args.semantic_provider if args.semantic_query else None,
                    "embedding_model": _embedding_model(args.semantic_provider, args.embedding_model)
                    if args.semantic_query
                    else None,
                    "sort": args.sort,
                    "limit": args.limit,
                },
                "count": len(results),
                "results": results,
            }
        )
        return 0
    if args.command == "search-history-backed-people":
        results = search_history_backed_people(
            settings.database_url,
            actual_employee_count_min=args.actual_employee_count_min,
            actual_employee_count_max=args.actual_employee_count_max,
            consultant_count_min=args.consultant_count_min,
            consultant_count_max=args.consultant_count_max,
            limit=args.limit,
        )
        _print_json(
            {
                "query": {
                    "actual_employee_count_min": args.actual_employee_count_min,
                    "actual_employee_count_max": args.actual_employee_count_max,
                    "consultant_count_min": args.consultant_count_min,
                    "consultant_count_max": args.consultant_count_max,
                    "limit": args.limit,
                },
                "count": len(results),
                "results": results,
            }
        )
        return 0
    if args.command == "export-operating-picture":
        if args.from_db:
            _print_json(operating_picture_from_db(settings.database_url, limit=args.limit))
        else:
            from relationship_substrate.read_models import build_relationship_operating_picture

            _print_json(build_relationship_operating_picture([]))
        return 0
    if args.command == "eval-local":
        _print_json(
            run_local_eval(
                settings,
                next_up_path=Path(args.next_up_path),
                calendar_path=Path(args.calendar_path) if args.calendar_path else None,
                output_dir=Path(args.output_dir),
                limit=args.limit,
                skip_msgvault=args.skip_msgvault,
            )
        )
        return 0
    if args.command == "run-network-pipeline":
        embed_texts = None
        embed_model = None
        if not args.skip_embeddings:
            embed_model = _embedding_model(args.embed_provider, args.embedding_model)
            embed_texts = _embedding_function(args.embed_provider, model=args.embedding_model)
        _print_json(
            run_network_pipeline(
                settings,
                next_up_paths=[Path(path) for path in args.next_up_path],
                calendar_paths=[Path(path) for path in args.calendar_path],
                output_dir=Path(args.output_dir),
                create_database=not args.no_create_database,
                sender_limit=args.sender_limit,
                correspondence_from_senders=args.correspondence_from_senders,
                correspondence_message_limit=args.correspondence_message_limit,
                skip_msgvault=args.skip_msgvault,
                skip_embeddings=args.skip_embeddings,
                embed_texts=embed_texts,
                embed_provider=args.embed_provider,
                embed_model=embed_model,
                embed_limit=args.embed_limit,
                organization_worklist_limit=args.organization_worklist_limit,
                north_star_limit=args.north_star_limit,
                north_star_semantic_query=args.north_star_semantic_query
                or "consulting background in medcoms medical communications business consulting supply chain pharma small consulting team",
            )
        )
        return 0
    parser.print_help()
    return 0
