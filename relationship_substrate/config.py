from __future__ import annotations

import os
from dataclasses import dataclass

from relationship_substrate.self_identity import default_self_email_aliases

DEFAULT_SELF_EMAIL_ALIASES = default_self_email_aliases()

DEFAULT_SKIPPED_SENDER_DOMAINS = (
    "example.com",
    "examplecorp.com",
    "demo.co",
)

DEFAULT_SKIPPED_SYSTEM_LOCALPARTS = (
    "daily",
    "events",
    "info",
    "onlinebanking",
    "return",
)

DEFAULT_SKIPPED_SYSTEM_PREFIXES = (
    "alerts",
    "auto-confirm",
    "calendar-notification",
    "daily",
    "digest",
    "do-not-reply",
    "donotreply",
    "ealerts",
    "fidelity-alerts",
    "groups-noreply",
    "invoice",
    "invoices",
    "mailer-daemon",
    "no-reply",
    "news",
    "newsletter",
    "noreply",
    "notify",
    "notification",
    "notifications",
    "nytdirect",
    "ordersender",
    "receipt",
    "receipts",
    "ship",
    "shipment",
    "statement",
    "statements",
    "voice-noreply",
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
        "msgvault",
    )
    msgvault_home: str = os.environ.get(
        "MSGVAULT_HOME",
        "",
    )
    msgvault_config: str = os.environ.get(
        "MSGVAULT_CONFIG",
        "",
    )
    msgvault_timeout_seconds: int = int(
        os.environ.get("MSGVAULT_TIMEOUT_SECONDS", "120")
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
