from __future__ import annotations

import os
from dataclasses import dataclass


DEFAULT_SELF_EMAIL_ALIASES = (
    "b@aclara.us",
    "b@mcco.us",
    "braydon@intempio.com",
    "braydon@intempio.us",
    "braydon@j-mc.org",
    "braydon@lightforgeworks.com",
    "braydon@rvibe.com",
    "braydon@synthyra.com",
    "braydonjm@gmail.com",
)

DEFAULT_SKIPPED_SENDER_DOMAINS = (
    "intempio.com",
)

DEFAULT_SKIPPED_SYSTEM_LOCALPARTS = (
    "events",
    "onlinebanking",
)

DEFAULT_SKIPPED_SYSTEM_PREFIXES = (
    "alerts",
    "do-not-reply",
    "donotreply",
    "ealerts",
    "invoice",
    "invoices",
    "no-reply",
    "noreply",
    "notification",
    "notifications",
    "receipt",
    "receipts",
    "statement",
    "statements",
)


def _csv_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.environ.get(name)
    if not value:
        return default
    return tuple(item.strip().lower() for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    database_url: str = os.environ.get(
        "RELATIONSHIP_SUBSTRATE_DATABASE_URL",
        "postgresql://localhost:5432/relationship_substrate",
    )
    msgvault_binary: str = os.environ.get(
        "MSGVAULT_BIN",
        "/Users/braydon/.local/bin/msgvault",
    )
    msgvault_home: str = os.environ.get(
        "MSGVAULT_HOME",
        "/Volumes/data2/msgvault",
    )
    msgvault_config: str = os.environ.get(
        "MSGVAULT_CONFIG",
        "/Volumes/data2/msgvault/config.toml",
    )
    self_email_aliases: tuple[str, ...] = _csv_env(
        "RELATIONSHIP_SUBSTRATE_SELF_EMAILS",
        DEFAULT_SELF_EMAIL_ALIASES,
    )
    skipped_sender_domains: tuple[str, ...] = _csv_env(
        "RELATIONSHIP_SUBSTRATE_SKIPPED_SENDER_DOMAINS",
        DEFAULT_SKIPPED_SENDER_DOMAINS,
    )
    skipped_system_localparts: tuple[str, ...] = _csv_env(
        "RELATIONSHIP_SUBSTRATE_SKIPPED_SYSTEM_LOCALPARTS",
        DEFAULT_SKIPPED_SYSTEM_LOCALPARTS,
    )
    skipped_system_prefixes: tuple[str, ...] = _csv_env(
        "RELATIONSHIP_SUBSTRATE_SKIPPED_SYSTEM_PREFIXES",
        DEFAULT_SKIPPED_SYSTEM_PREFIXES,
    )
