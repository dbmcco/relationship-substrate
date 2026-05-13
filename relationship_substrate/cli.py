from __future__ import annotations

import argparse
import json

from relationship_substrate.adapters.msgvault import MsgvaultAdapter
from relationship_substrate.config import Settings
from relationship_substrate.db import run_migrations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="relationship-substrate")
    parser.add_argument("--version", action="store_true")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("migrate")
    profile = subparsers.add_parser("profile-msgvault")
    profile.add_argument("--limit", type=int, default=25)
    subparsers.add_parser("export-operating-picture")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.version:
        from relationship_substrate import __version__

        print(__version__)
        return 0
    if args.command == "migrate":
        run_migrations(Settings().database_url)
        return 0
    if args.command == "profile-msgvault":
        rows = MsgvaultAdapter(Settings()).top_sender_candidates(args.limit)
        for row in rows:
            print(row)
        return 0
    if args.command == "export-operating-picture":
        from relationship_substrate.read_models import build_relationship_operating_picture

        print(json.dumps(build_relationship_operating_picture([]), indent=2))
        return 0
    parser.print_help()
    return 0
