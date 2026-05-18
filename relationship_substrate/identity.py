from __future__ import annotations

import itertools
from datetime import UTC, datetime
from typing import Any

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
MAX_IDENTITY_CANDIDATE_GROUP_SIZE = 25


def _email_localpart(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    localpart = email.split("@", 1)[0].strip().lower()
    if not localpart or "+" in localpart or localpart in GENERIC_ROLE_LOCALPARTS:
        return None
    return localpart


def _email_domain(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    domain = email.split("@", 1)[1].strip().lower()
    if not domain:
        return None
    return domain


def _normalize_display_name(name: str | None) -> str | None:
    if not name:
        return None
    normalized = " ".join(
        "".join(ch for ch in token if ch.isalnum())
        for token in name.strip().lower().split()
    ).strip()
    if not normalized:
        return None
    return normalized


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
        """,
        (source_identity_id, candidate_id, reason),
    )
    return cur.fetchone() is not None


def _candidate_payload(row: tuple) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "status": row[1],
        "reason": row[2],
        "evidence": row[3],
        "created_at": row[4].isoformat() if row[4] else None,
        "source_identity": {
            "id": str(row[5]),
            "identity_type": row[6],
            "identity_value": row[7],
            "display_name": row[8],
            "metadata": row[9],
        },
        "candidate": {
            "type": row[10],
            "id": str(row[11]) if row[11] else None,
            "display_name": row[12],
            "primary_email": row[13],
        },
    }


def _candidate_select_sql() -> str:
    return """
        SELECT
          ic.id,
          ic.status,
          ic.reason,
          ic.evidence,
          ic.created_at,
          si.id,
          si.identity_type,
          si.identity_value,
          si.display_name,
          si.metadata,
          ic.candidate_type,
          ic.candidate_id,
          p.display_name,
          p.primary_email
        FROM relationship_substrate.identity_candidate ic
        JOIN relationship_substrate.source_identity si
          ON si.id = ic.source_identity_id
        LEFT JOIN relationship_substrate.person p
          ON p.id = ic.candidate_id
    """


def list_identity_candidates(
    database_url: str,
    *,
    status: str = "candidate",
    limit: int = 25,
) -> list[dict[str, Any]]:
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                _candidate_select_sql()
                + """
                WHERE ic.status = %s
                ORDER BY ic.created_at DESC, ic.id
                LIMIT %s
                """,
                (status, limit),
            )
            rows = cur.fetchall()
    return [_candidate_payload(row) for row in rows]


def get_identity_candidate(database_url: str, candidate_id: str) -> dict[str, Any]:
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                _candidate_select_sql()
                + """
                WHERE ic.id = %s
                """,
                (candidate_id,),
            )
            row = cur.fetchone()
    if row is None:
        raise ValueError(f"identity candidate not found: {candidate_id}")
    return _candidate_payload(row)


def resolve_identity_candidate(
    database_url: str,
    candidate_id: str,
    *,
    status: str,
    note: str,
) -> dict[str, Any]:
    if status not in {"accepted", "rejected", "superseded", "candidate"}:
        raise ValueError(f"unsupported identity candidate status: {status}")

    candidate = get_identity_candidate(database_url, candidate_id)
    evidence = dict(candidate["evidence"] or {})
    evidence["review"] = {
        "decision": status,
        "note": note,
        "reviewed_at": datetime.now(UTC).isoformat(),
    }
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE relationship_substrate.identity_candidate
                SET status = %s,
                    evidence = %s
                WHERE id = %s
                """,
                (status, Jsonb(evidence), candidate_id),
            )
        conn.commit()
    return get_identity_candidate(database_url, candidate_id)


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
                    "domain": _email_domain(row[2]),
                    "normalized_name": _normalize_display_name(row[1]),
                }
                for row in cur.fetchall()
            ]

            by_localpart: dict[str, list[dict]] = {}
            by_domain_name: dict[tuple[str, str], list[dict]] = {}
            for person in people:
                localpart = person["localpart"]
                if localpart:
                    by_localpart.setdefault(localpart, []).append(person)
                domain = person["domain"]
                normalized_name = person["normalized_name"]
                if domain and normalized_name:
                    by_domain_name.setdefault((domain, normalized_name), []).append(person)

            stats = {
                "source": "identity_candidate",
                "groups_seen": 0,
                "candidate_pairs": 0,
            }
            for localpart, group in by_localpart.items():
                if len(group) < 2:
                    continue
                if len(group) > MAX_IDENTITY_CANDIDATE_GROUP_SIZE:
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

            for (domain, normalized_name), group in by_domain_name.items():
                if len(group) < 2:
                    continue
                if len(group) > MAX_IDENTITY_CANDIDATE_GROUP_SIZE:
                    continue
                for left, right in itertools.combinations(group, 2):
                    if left["localpart"] == right["localpart"]:
                        continue
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
                        reason="same_email_domain_and_name",
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
                        VALUES (%s, 'person', %s, 'same_email_domain_and_name', %s)
                        """,
                        (
                            source_identity_id,
                            right["person_id"],
                            Jsonb(
                                {
                                    "domain": domain,
                                    "normalized_name": normalized_name,
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
