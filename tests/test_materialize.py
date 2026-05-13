import psycopg

from relationship_substrate.contracts import SourceEventIn, SourcePosture
from relationship_substrate.db import run_migrations
from relationship_substrate.materialize import materialize_curated_contact
from relationship_substrate.repositories import upsert_source_event


def test_materialize_curated_contact_creates_person_and_channel(database_url):
    run_migrations(database_url)
    event = SourceEventIn(
        source_name="next_up",
        source_event_type="curated_contact",
        source_event_key="next_up:people.xlsx:Contacts:2",
        source_payload={
            "first_name": "Jane",
            "last_name": "Doe",
            "email": "Jane@Example.com",
            "company": "ExampleCo",
            "title": "VP Product",
        },
        source_posture=SourcePosture.CURATED_EXPORT,
        provenance_status="unknown_upstream",
        trust_role="identity/context seed",
    )
    source_event_id = upsert_source_event(database_url, event)

    person_id = materialize_curated_contact(database_url, source_event_id)

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT display_name, primary_email FROM relationship_substrate.person WHERE id = %s",
                (person_id,),
            )
            assert cur.fetchone() == ("Jane Doe", "jane@example.com")
            cur.execute(
                "SELECT channel_value FROM relationship_substrate.contact_channel WHERE person_id = %s",
                (person_id,),
            )
            assert cur.fetchone() == ("jane@example.com",)
