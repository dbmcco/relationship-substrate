from __future__ import annotations

from pathlib import Path

import psycopg


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = ROOT / "migrations"


def run_migrations(database_url: str) -> None:
    with psycopg.connect(database_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS relationship_substrate")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS relationship_substrate.schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = path.name
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM relationship_substrate.schema_migrations
                    WHERE version = %s
                    """,
                    (version,),
                )
                if cur.fetchone():
                    continue
                cur.execute(path.read_text())
                cur.execute(
                    """
                    INSERT INTO relationship_substrate.schema_migrations(version)
                    VALUES (%s)
                    ON CONFLICT (version) DO NOTHING
                    """,
                    (version,),
                )
