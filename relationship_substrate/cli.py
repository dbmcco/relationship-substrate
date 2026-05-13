from __future__ import annotations

import argparse
import json
from pathlib import Path

from relationship_substrate.adapters.next_up import iter_next_up_events
from relationship_substrate.adapters.msgvault import MsgvaultAdapter
from relationship_substrate.config import Settings
from relationship_substrate.db import run_migrations
from relationship_substrate.materialize import materialize_exact_emails
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
    ingest = subparsers.add_parser("ingest-next-up")
    ingest.add_argument("--path", required=True)
    materialize = subparsers.add_parser("materialize-exact-emails")
    materialize.add_argument("--source", default="next_up")
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
    picture = operating_picture_from_db(settings.database_url, limit=limit)
    msgvault = {} if skip_msgvault else profile_msgvault(settings, limit=limit, kind="both")
    counts = substrate_counts(settings.database_url)
    report = {
        "ok": True,
        "database_url": settings.database_url,
        "next_up": next_up,
        "materialization": materialization,
        "operating_picture": {
            "relationships": len(picture["relationships"]),
            "path": str(output_dir / "relationship_operating_picture.json"),
        },
        "msgvault": {
            "skipped": skip_msgvault,
            "sender_candidates": len(msgvault.get("senders", [])) if msgvault else 0,
            "domain_candidates": len(msgvault.get("domains", [])) if msgvault else 0,
        },
        "counts": counts,
        "checks": [
            "Next Up events retain curated_export + unknown_upstream provenance.",
            "Exact-email materialization only creates canonical person/contact_channel records.",
            "Operating picture remains uninterpreted; no relationship-health scoring is performed.",
            "msgvault profiling uses supported read-only analytics commands.",
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
    if args.command == "ingest-next-up":
        _print_json(ingest_next_up(settings.database_url, Path(args.path)))
        return 0
    if args.command == "materialize-exact-emails":
        run_migrations(settings.database_url)
        _print_json(materialize_exact_emails(settings.database_url, source_name=args.source))
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
