from __future__ import annotations

from relationship_substrate.config import (
    DEFAULT_SKIPPED_SENDER_DOMAINS,
    DEFAULT_SKIPPED_SYSTEM_LOCALPARTS,
    DEFAULT_SKIPPED_SYSTEM_PREFIXES,
)


AUTOMATED_CONTACT_DOMAINS = {
    "linkedin.com",
}

AUTOMATED_LOCALPARTS = {
    "email",
    "express",
    "quickbooks",
    "service",
    "team",
}


def _clean_email(value: object) -> str:
    return str(value or "").strip().lower()


def _normalized_localpart(localpart: str) -> str:
    return localpart.replace(".", "-").replace("_", "-").lower()


def is_automated_contact_email(email: object) -> bool:
    normalized = _clean_email(email)
    if "@" not in normalized:
        return True
    localpart, domain = normalized.split("@", 1)
    normalized_localpart = _normalized_localpart(localpart)
    skipped_domains = set(DEFAULT_SKIPPED_SENDER_DOMAINS) | AUTOMATED_CONTACT_DOMAINS
    if domain in skipped_domains:
        return True
    if domain.startswith(("emails.", "emails-", "email.")):
        return True
    if domain.startswith(("e.", "e-", "mail.")):
        return True
    if localpart in AUTOMATED_LOCALPARTS or normalized_localpart in AUTOMATED_LOCALPARTS:
        return True
    if localpart in DEFAULT_SKIPPED_SYSTEM_LOCALPARTS or normalized_localpart in DEFAULT_SKIPPED_SYSTEM_LOCALPARTS:
        return True
    if any(normalized_localpart.startswith(prefix) for prefix in DEFAULT_SKIPPED_SYSTEM_PREFIXES):
        return True
    return any(token in normalized_localpart for token in ("-noreply", "noreply", "-no-reply", "no-reply"))
