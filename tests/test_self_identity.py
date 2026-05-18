from __future__ import annotations

from relationship_substrate.self_identity import (
    BRAYDON_SELF_IDENTITY_ACCOUNTS,
    default_self_email_aliases,
    is_self_identity_email,
)


def test_default_self_email_aliases_are_derived_from_account_model():
    aliases = default_self_email_aliases()

    assert len(BRAYDON_SELF_IDENTITY_ACCOUNTS) > 1
    assert "braydonjm@gmail.com" in aliases
    assert "braydon@intempio.com" in aliases
    assert "b@aclara.us" in aliases
    assert aliases == tuple(sorted(set(aliases)))


def test_is_self_identity_email_matches_plus_and_gmail_dot_variants():
    aliases = {"braydonjm@gmail.com", "braydon@intempio.com"}

    assert is_self_identity_email("braydonjm+calendar@gmail.com", aliases=aliases) is True
    assert is_self_identity_email("braydon.jm@gmail.com", aliases=aliases) is True
    assert is_self_identity_email("braydon+ops@intempio.com", aliases=aliases) is True
    assert is_self_identity_email("external.person@example.com", aliases=aliases) is False
