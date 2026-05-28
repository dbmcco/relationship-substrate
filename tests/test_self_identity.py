from __future__ import annotations

from relationship_substrate.self_identity import (
    EXAMPLE_SELF_IDENTITY_ACCOUNTS,
    default_self_email_aliases,
    is_self_identity_email,
)


def test_default_self_email_aliases_are_derived_from_account_model():
    aliases = default_self_email_aliases()

    assert len(EXAMPLE_SELF_IDENTITY_ACCOUNTS) > 1
    assert "user.name@gmail.com" in aliases
    assert "user@examplecorp.com" in aliases
    assert "user@demo.co" in aliases
    assert aliases == tuple(sorted(set(aliases)))


def test_is_self_identity_email_matches_plus_and_gmail_dot_variants():
    aliases = {"username@gmail.com", "user@examplecorp.com"}

    assert is_self_identity_email("user.name+calendar@gmail.com", aliases=aliases) is True
    assert is_self_identity_email("user.name@gmail.com", aliases=aliases) is True
    assert is_self_identity_email("user+ops@examplecorp.com", aliases=aliases) is True
    assert is_self_identity_email("external.person@example.com", aliases=aliases) is False
