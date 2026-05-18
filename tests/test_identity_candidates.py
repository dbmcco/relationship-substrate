from __future__ import annotations

from uuid import uuid4

import psycopg

from relationship_substrate.cli import generate_identity_candidate_report
from relationship_substrate.db import run_migrations
from relationship_substrate.identity import (
    generate_identity_candidates,
    get_identity_candidate,
    list_identity_candidates,
    resolve_identity_candidate,
)
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
    run_migrations(database_url)
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
    run_migrations(database_url)
    localpart = f"candidatebeta{uuid4().hex}"
    _insert_person(database_url, name="Candidate Beta", email=f"{localpart}@example.com")
    _insert_person(database_url, name="Candidate Beta", email=f"{localpart}@other.example")

    first = generate_identity_candidates(database_url)
    second = generate_identity_candidates(database_url)

    assert first["candidate_pairs"] >= 1
    assert second["candidate_pairs"] == 0


def test_generate_identity_candidates_skips_generic_role_localparts(database_url):
    run_migrations(database_url)
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


def test_generate_identity_candidates_for_same_domain_and_name_heuristic(database_url):
    run_migrations(database_url)
    run_id = uuid4().hex
    domain = f"heuristic-{run_id}.example"
    _insert_person(database_url, name="Alex Candidate", email=f"alex@{domain}")
    _insert_person(database_url, name="Alex Candidate", email=f"a.candidate@{domain}")

    stats = generate_identity_candidates(database_url)

    assert stats["candidate_pairs"] >= 1
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT reason, evidence->>'domain', evidence->>'normalized_name'
                FROM relationship_substrate.identity_candidate
                WHERE reason = 'same_email_domain_and_name'
                AND evidence->>'domain' = %s
                """,
                (domain,),
            )
            rows = cur.fetchall()

    assert rows == [("same_email_domain_and_name", domain, "alex candidate")]


def test_generate_identity_candidates_skips_same_domain_without_name_match(database_url):
    run_migrations(database_url)
    run_id = uuid4().hex
    domain = f"heuristic-namemiss-{run_id}.example"
    _insert_person(database_url, name="Alex Candidate", email=f"alex@{domain}")
    _insert_person(database_url, name="Jordan Different", email=f"jordan@{domain}")

    generate_identity_candidates(database_url)

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*)
                FROM relationship_substrate.identity_candidate
                WHERE reason = 'same_email_domain_and_name'
                AND evidence->>'domain' = %s
                """,
                (domain,),
            )
            assert cur.fetchone() == (0,)


def test_generate_identity_candidates_skips_large_low_signal_groups(database_url):
    run_migrations(database_url)
    run_id = uuid4().hex
    localpart = f"largegroup{run_id}"
    for index in range(26):
        _insert_person(
            database_url,
            name=f"Large Group {index}",
            email=f"{localpart}@large-{index}-{run_id}.example",
        )

    generate_identity_candidates(database_url)

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*)
                FROM relationship_substrate.identity_candidate
                WHERE evidence->>'match_key' = %s
                """,
                (localpart,),
            )
            assert cur.fetchone() == (0,)


def test_operating_picture_rows_include_unresolved_identity_candidate_counts(database_url):
    run_migrations(database_url)
    localpart = f"candidategamma{uuid4().hex}"
    emails = {f"{localpart}@example.com", f"{localpart}@other.example"}
    _insert_person(database_url, name="Candidate Gamma", email=f"{localpart}@example.com")
    _insert_person(database_url, name="Candidate Gamma", email=f"{localpart}@other.example")
    generate_identity_candidates(database_url)

    rows = operating_picture_rows(database_url, limit=100000)

    candidate_rows = [row for row in rows if row["primary_email"] in emails]
    assert candidate_rows
    assert any(row["unresolved_identity_candidates"] > 0 for row in candidate_rows)


def test_generate_identity_candidate_report_includes_total_open_candidates(database_url):
    run_migrations(database_url)
    localpart = f"candidatedelta{uuid4().hex}"
    _insert_person(database_url, name="Candidate Delta", email=f"{localpart}@example.com")
    _insert_person(database_url, name="Candidate Delta", email=f"{localpart}@other.example")

    report = generate_identity_candidate_report(database_url)

    assert report["source"] == "identity_candidate"
    assert report["candidate_pairs"] >= 1
    assert report["open_candidates"] >= 1


def test_list_and_get_identity_candidates_include_review_evidence(database_url):
    run_migrations(database_url)
    localpart = f"candidateepsilon{uuid4().hex}"
    _insert_person(database_url, name="Candidate Epsilon", email=f"{localpart}@example.com")
    _insert_person(database_url, name="Candidate Epsilon", email=f"{localpart}@other.example")
    generate_identity_candidates(database_url)

    candidates = list_identity_candidates(database_url, status="candidate", limit=1000)
    candidate = next(row for row in candidates if row["evidence"].get("match_key") == localpart)
    loaded = get_identity_candidate(database_url, candidate["id"])

    assert candidate["status"] == "candidate"
    assert candidate["source_identity"]["identity_value"] == f"{localpart}@example.com"
    assert candidate["candidate"]["primary_email"] == f"{localpart}@other.example"
    assert loaded == candidate


def test_resolve_identity_candidate_records_decision_without_merging_people(database_url):
    run_migrations(database_url)
    localpart = f"candidatezeta{uuid4().hex}"
    _insert_person(database_url, name="Candidate Zeta", email=f"{localpart}@example.com")
    _insert_person(database_url, name="Candidate Zeta", email=f"{localpart}@other.example")
    generate_identity_candidates(database_url)
    candidate = next(
        row
        for row in list_identity_candidates(database_url, status="candidate", limit=1000)
        if row["evidence"].get("match_key") == localpart
    )

    resolved = resolve_identity_candidate(
        database_url,
        candidate["id"],
        status="rejected",
        note="Different people; same first name only.",
    )

    assert resolved["status"] == "rejected"
    assert resolved["evidence"]["review"]["note"] == "Different people; same first name only."
    assert resolved["evidence"]["review"]["decision"] == "rejected"
    assert list_identity_candidates(database_url, status="candidate", limit=1000) != [resolved]
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*)
                FROM relationship_substrate.person
                WHERE primary_email IN (%s, %s)
                """,
                (f"{localpart}@example.com", f"{localpart}@other.example"),
            )
            assert cur.fetchone() == (2,)


def test_resolved_identity_candidate_is_not_regenerated(database_url):
    run_migrations(database_url)
    localpart = f"candidateeta{uuid4().hex}"
    _insert_person(database_url, name="Candidate Eta", email=f"{localpart}@example.com")
    _insert_person(database_url, name="Candidate Eta", email=f"{localpart}@other.example")
    generate_identity_candidates(database_url)
    candidate = next(
        row
        for row in list_identity_candidates(database_url, status="candidate", limit=1000)
        if row["evidence"].get("match_key") == localpart
    )
    resolve_identity_candidate(database_url, candidate["id"], status="rejected", note="Reviewed.")

    stats = generate_identity_candidates(database_url)

    assert stats["candidate_pairs"] == 0
    assert [
        row
        for row in list_identity_candidates(database_url, status="candidate", limit=1000)
        if row["evidence"].get("match_key") == localpart
    ] == []
