from __future__ import annotations

from uuid import uuid4

import psycopg

from relationship_substrate.cli import generate_identity_candidate_report
from relationship_substrate.identity import generate_identity_candidates
from relationship_substrate.repositories import operating_picture_rows


def _insert_person(database_url: str, *, name: str, email: str) -> None:
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO relationship_substrate.person (
                  display_name, primary_email, source_posture, provenance_status
                )
                VALUES (%s, %s, 'direct_interaction', 'msgvault_profile')
                ON CONFLICT (primary_email)
                DO UPDATE SET display_name = EXCLUDED.display_name
                """,
                (name, email),
            )
        conn.commit()


def test_generate_identity_candidates_for_same_localpart(database_url):
    localpart = f"candidatealpha{uuid4().hex}"
    _insert_person(database_url, name="Candidate Alpha", email=f"{localpart}@example.com")
    _insert_person(database_url, name="Candidate Alpha", email=f"{localpart}@other.example")

    stats = generate_identity_candidates(database_url)

    assert stats["candidate_pairs"] >= 1
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT reason, evidence->>'match_key'
                FROM relationship_substrate.identity_candidate
                WHERE reason = 'same_email_localpart'
                AND evidence->>'match_key' = %s
                """,
                (localpart,),
            )
            rows = cur.fetchall()

    assert rows == [("same_email_localpart", localpart)]


def test_generate_identity_candidates_is_idempotent(database_url):
    localpart = f"candidatebeta{uuid4().hex}"
    _insert_person(database_url, name="Candidate Beta", email=f"{localpart}@example.com")
    _insert_person(database_url, name="Candidate Beta", email=f"{localpart}@other.example")

    first = generate_identity_candidates(database_url)
    second = generate_identity_candidates(database_url)

    assert first["candidate_pairs"] >= 1
    assert second["candidate_pairs"] == 0


def test_generate_identity_candidates_skips_generic_role_localparts(database_url):
    localpart = f"info{uuid4().hex}"
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM relationship_substrate.identity_candidate
                WHERE evidence->>'match_key' IN ('info', 'events')
                """
            )
        conn.commit()
    _insert_person(database_url, name="Info Team", email="info@example.com")
    _insert_person(database_url, name="Info Team", email="info@other.example")
    _insert_person(database_url, name="Events Team", email="events@example.com")
    _insert_person(database_url, name="Events Team", email="events@other.example")
    _insert_person(database_url, name="Human Candidate", email=f"{localpart}@example.com")
    _insert_person(database_url, name="Human Candidate", email=f"{localpart}@other.example")

    stats = generate_identity_candidates(database_url)

    assert stats["candidate_pairs"] >= 1
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT evidence->>'match_key'
                FROM relationship_substrate.identity_candidate
                WHERE evidence->>'match_key' IN ('info', 'events')
                """
            )
            assert cur.fetchall() == []


def test_operating_picture_rows_include_unresolved_identity_candidate_counts(database_url):
    localpart = f"candidategamma{uuid4().hex}"
    emails = {f"{localpart}@example.com", f"{localpart}@other.example"}
    _insert_person(database_url, name="Candidate Gamma", email=f"{localpart}@example.com")
    _insert_person(database_url, name="Candidate Gamma", email=f"{localpart}@other.example")
    generate_identity_candidates(database_url)

    rows = operating_picture_rows(database_url, limit=1000)

    candidate_rows = [row for row in rows if row["primary_email"] in emails]
    assert candidate_rows
    assert any(row["unresolved_identity_candidates"] > 0 for row in candidate_rows)


def test_generate_identity_candidate_report_includes_total_open_candidates(database_url):
    localpart = f"candidatedelta{uuid4().hex}"
    _insert_person(database_url, name="Candidate Delta", email=f"{localpart}@example.com")
    _insert_person(database_url, name="Candidate Delta", email=f"{localpart}@other.example")

    report = generate_identity_candidate_report(database_url)

    assert report["source"] == "identity_candidate"
    assert report["candidate_pairs"] >= 1
    assert report["open_candidates"] >= 1
