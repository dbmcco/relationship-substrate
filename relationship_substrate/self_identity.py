from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SelfIdentityAccount:
    account_key: str
    aliases: tuple[str, ...]


BRAYDON_SELF_IDENTITY_ACCOUNTS = (
    SelfIdentityAccount(
        account_key="personal_gmail",
        aliases=("braydonjm@gmail.com",),
    ),
    SelfIdentityAccount(
        account_key="intempio",
        aliases=("braydon@intempio.com", "braydon@intempio.us"),
    ),
    SelfIdentityAccount(
        account_key="mcco",
        aliases=("b@mcco.us", "braydon@mcco.us"),
    ),
    SelfIdentityAccount(
        account_key="aclara",
        aliases=("b@aclara.us", "braydon@aclara.us"),
    ),
    SelfIdentityAccount(
        account_key="j_mc",
        aliases=("braydon@j-mc.org",),
    ),
    SelfIdentityAccount(
        account_key="lightforgeworks",
        aliases=("braydon@lightforgeworks.com",),
    ),
    SelfIdentityAccount(
        account_key="rvibe",
        aliases=("braydon@rvibe.com",),
    ),
    SelfIdentityAccount(
        account_key="synthyra",
        aliases=("braydon@synthyra.com",),
    ),
)

_GMAIL_DOMAINS = {"gmail.com", "googlemail.com"}


def _normalize_email(value: object) -> str | None:
    text = str(value or "").strip().lower()
    if not text or "@" not in text:
        return None
    localpart, domain = text.rsplit("@", 1)
    if not localpart or not domain:
        return None
    return f"{localpart}@{domain}"


def _plus_base(email: str) -> str:
    localpart, domain = email.rsplit("@", 1)
    if "+" not in localpart:
        return email
    return f"{localpart.split('+', 1)[0]}@{domain}"


def _gmail_dot_base(email: str) -> str:
    localpart, domain = email.rsplit("@", 1)
    if domain not in _GMAIL_DOMAINS:
        return email
    return f"{localpart.replace('.', '')}@{domain}"


def _self_match_candidates(email: str) -> tuple[str, ...]:
    plus_base = _plus_base(email)
    candidates = {email, plus_base, _gmail_dot_base(email), _gmail_dot_base(plus_base)}
    return tuple(candidate for candidate in candidates if candidate)


def default_self_email_aliases() -> tuple[str, ...]:
    aliases: set[str] = set()
    for account in BRAYDON_SELF_IDENTITY_ACCOUNTS:
        for alias in account.aliases:
            normalized = _normalize_email(alias)
            if normalized is not None:
                aliases.add(normalized)
    return tuple(sorted(aliases))


def is_self_identity_email(email: str, *, aliases: set[str]) -> bool:
    normalized_email = _normalize_email(email)
    if normalized_email is None:
        return False
    normalized_aliases = {_normalize_email(alias) for alias in aliases}
    normalized_aliases.discard(None)
    for candidate in _self_match_candidates(normalized_email):
        if candidate in normalized_aliases:
            return True
    return False
