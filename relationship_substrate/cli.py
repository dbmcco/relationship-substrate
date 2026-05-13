from __future__ import annotations

import argparse
import json
from pathlib import Path

from relationship_substrate.adapters.next_up import iter_next_up_events
from relationship_substrate.adapters.msgvault import MsgvaultAdapter
from relationship_substrate.config import Settings
from relationship_substrate.contracts import SourceEventIn, SourcePosture
from relationship_substrate.db import run_migrations
from relationship_substrate.materialize import materialize_exact_emails, materialize_msgvault_senders
from relationship_substrate.repositories import operating_picture_rows, substrate_counts, upsert_source_event


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
    ingest = subparsers.add_parser("ingest-next-up")
    ingest.add_argument("--path", required=True)
    materialize = subparsers.add_parser("materialize-exact-emails")
    materialize.add_argument("--source", default="next_up")
    subparsers.add_parser("materialize-msgvault-senders")
    export = subparsers.add_parser("export-operating-picture")
    export.add_argument("--from-db", action="store_true")
    export.add_argument("--limit", type=int, default=25)
    eval_local = subparsers.add_parser("eval-local")
    eval_local.add_argument("--next-up-path", required=True)
    eval_local.add_argument("--output-dir", default="output/eval")
    eval_local.add_argument("--limit", type=int, default=25)
    eval_local.add_argument("--skip-msgvault", action="store_true")
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
        )
    return settings


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def ingest_next_up(database_url: str, path: Path) -> dict[str, int | str]:
    run_migrations(database_url)
    events_seen = 0
    events_upserted = 0
    for event in iter_next_up_events(path):
        events_seen += 1
        upsert_source_event(database_url, event)
        events_upserted += 1
    return {"source": "next_up", "events_seen": events_seen, "events_upserted": events_upserted}


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
) -> dict[str, int | str]:
    run_migrations(database_url)
    stats = {
        "source": "msgvault",
        "events_seen": len(rows),
        "events_upserted": 0,
        "skipped_self": 0,
        "skipped_domain": 0,
        "skipped_missing_email": 0,
    }
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
    )


def operating_picture_from_db(database_url: str, *, limit: int) -> dict:
    from relationship_substrate.read_models import build_relationship_operating_picture

    return build_relationship_operating_picture(operating_picture_rows(database_url, limit=limit))


def run_local_eval(
    settings: Settings,
    *,
    next_up_path: Path,
    output_dir: Path,
    limit: int,
    skip_msgvault: bool,
) -> dict:
    run_migrations(settings.database_url)
    next_up = ingest_next_up(settings.database_url, next_up_path)
    materialization = materialize_exact_emails(settings.database_url, source_name="next_up")
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
        )
        msgvault_materialization = materialize_msgvault_senders(settings.database_url)
        msgvault["sender_ingestion"] = sender_ingestion
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
        "counts": counts,
        "checks": [
            "Next Up events retain curated_export + unknown_upstream provenance.",
            "Exact-email materialization only creates canonical person/contact_channel records.",
            "Operating picture remains uninterpreted; no relationship-health scoring is performed.",
            "msgvault profiling uses supported read-only analytics commands.",
            "Known self email aliases are skipped before sender profiles become relationship edges.",
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
    if args.command == "ingest-next-up":
        _print_json(ingest_next_up(settings.database_url, Path(args.path)))
        return 0
    if args.command == "materialize-exact-emails":
        run_migrations(settings.database_url)
        _print_json(materialize_exact_emails(settings.database_url, source_name=args.source))
        return 0
    if args.command == "materialize-msgvault-senders":
        run_migrations(settings.database_url)
        _print_json(materialize_msgvault_senders(settings.database_url))
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
                output_dir=Path(args.output_dir),
                limit=args.limit,
                skip_msgvault=args.skip_msgvault,
            )
        )
        return 0
    parser.print_help()
    return 0
