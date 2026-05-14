import psycopg

from relationship_substrate.db import run_migrations


def test_run_migrations_creates_core_tables(database_url):
    run_migrations(database_url)

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'relationship_substrate'
                ORDER BY table_name
                """
            )
            tables = {row[0] for row in cur.fetchall()}
            cur.execute(
                """
                SELECT version
                FROM relationship_substrate.schema_migrations
                ORDER BY version
                """
            )
            versions = {row[0] for row in cur.fetchall()}

    assert {
        "evidence_ref",
        "identity_candidate",
        "ingestion_run",
        "interaction",
        "person",
        "relationship_state",
        "research_snapshot",
        "source_event",
        "source_identity",
        "state_journal_entry",
    }.issubset(tables)
    assert "001_initial.sql" in versions
    assert "003_research_snapshots.sql" in versions
