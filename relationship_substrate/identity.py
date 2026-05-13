from __future__ import annotations

import itertools

import psycopg
from psycopg.types.json import Jsonb

GENERIC_ROLE_LOCALPARTS = {
    "admin",
    "careers",
    "contact",
    "events",
    "hello",
    "help",
    "info",
    "jobs",
    "marketing",
    "news",
    "office",
    "press",
    "sales",
    "support",
    "team",
}


def _email_localpart(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    localpart = email.split("@", 1)[0].strip().lower()
    if not localpart or "+" in localpart or localpart in GENERIC_ROLE_LOCALPARTS:
        return None
    return localpart


def _ensure_source_identity(cur: psycopg.Cursor, *, person_id: str, email: str, name: str) -> str:
    cur.execute(
        """
        INSERT INTO relationship_substrate.source_identity (
          identity_type, identity_value, display_name, metadata
        )
        VALUES ('person_email', %s, %s, %s)
        ON CONFLICT (identity_type, identity_value)
        DO UPDATE SET display_name = EXCLUDED.display_name
        RETURNING id
        """,
        (email, name, Jsonb({"person_id": person_id})),
    )
    return cur.fetchone()[0]


def _candidate_exists(cur: psycopg.Cursor, *, source_identity_id: str, candidate_id: str, reason: str) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM relationship_substrate.identity_candidate
        WHERE source_identity_id = %s
        AND candidate_id = %s
        AND reason = %s
        AND status = 'candidate'
        """,
        (source_identity_id, candidate_id, reason),
    )
    return cur.fetchone() is not None


def generate_identity_candidates(database_url: str) -> dict[str, int | str]:
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, display_name, primary_email
                FROM relationship_substrate.person
                WHERE primary_email IS NOT NULL
                ORDER BY primary_email
                """
            )
            people = [
                {
                    "person_id": str(row[0]),
                    "display_name": row[1],
                    "primary_email": row[2],
                    "localpart": _email_localpart(row[2]),
                }
                for row in cur.fetchall()
            ]

            by_localpart: dict[str, list[dict]] = {}
            for person in people:
                localpart = person["localpart"]
                if localpart:
                    by_localpart.setdefault(localpart, []).append(person)

            stats = {
                "source": "identity_candidate",
                "groups_seen": 0,
                "candidate_pairs": 0,
            }
            for localpart, group in by_localpart.items():
                if len(group) < 2:
                    continue
                stats["groups_seen"] += 1
                for left, right in itertools.combinations(group, 2):
                    source_identity_id = _ensure_source_identity(
                        cur,
                        person_id=left["person_id"],
                        email=left["primary_email"],
                        name=left["display_name"],
                    )
                    if _candidate_exists(
                        cur,
                        source_identity_id=source_identity_id,
                        candidate_id=right["person_id"],
                        reason="same_email_localpart",
                    ):
                        continue
                    cur.execute(
                        """
                        INSERT INTO relationship_substrate.identity_candidate (
                          source_identity_id,
                          candidate_type,
                          candidate_id,
                          reason,
                          evidence
                        )
                        VALUES (%s, 'person', %s, 'same_email_localpart', %s)
                        """,
                        (
                            source_identity_id,
                            right["person_id"],
                            Jsonb(
                                {
                                    "match_key": localpart,
                                    "left_email": left["primary_email"],
                                    "right_email": right["primary_email"],
                                    "merge_policy": "candidate_only",
                                }
                            ),
                        ),
                    )
                    stats["candidate_pairs"] += 1
        conn.commit()
    return stats
