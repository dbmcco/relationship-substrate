import psycopg

from relationship_substrate.contracts import SourceEventIn, SourcePosture
from relationship_substrate.db import run_migrations
from relationship_substrate.repositories import upsert_source_event


def test_upsert_source_event_is_idempotent(database_url):
    run_migrations(database_url)
    event = SourceEventIn(
        source_name="next_up",
        source_event_type="curated_contact",
        source_event_key="next_up:test:row:1",
        source_payload={"email": "person@example.com"},
        source_posture=SourcePosture.CURATED_EXPORT,
        provenance_status="unknown_upstream",
        trust_role="identity/context seed",
    )

    first_id = upsert_source_event(database_url, event)
    second_id = upsert_source_event(database_url, event)

    assert first_id == second_id

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM relationship_substrate.source_event WHERE source_event_key = %s",
                ("next_up:test:row:1",),
            )
            assert cur.fetchone()[0] == 1
