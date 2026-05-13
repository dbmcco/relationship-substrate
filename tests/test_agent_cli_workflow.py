from __future__ import annotations

import json
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
from openpyxl import Workbook

from relationship_substrate.cli import main
from relationship_substrate.db import run_migrations


def _workbook(path: Path, email: str = "Jane@Example.com") -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Contacts"
    ws.append(["First Name", "Last Name", "Title", "Company", "Email"])
    ws.append(["Jane", "Doe", "VP Product", "ExampleCo", email])
    wb.save(path)
    return path


def _run_cli(monkeypatch, capsys, *args: str) -> dict:
    monkeypatch.setattr(sys, "argv", ["relationship-substrate", *args])
    assert main() == 0
    return json.loads(capsys.readouterr().out)


def test_agent_cli_ingests_materializes_and_exports_from_db(
    database_url, tmp_path, monkeypatch, capsys
):
    run_migrations(database_url)
    workbook = _workbook(tmp_path / "people.xlsx")
    event_key = f"next_up:{workbook.name}:Contacts:2"
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM relationship_substrate.source_event WHERE source_event_key = %s",
                (event_key,),
            )
            cur.execute(
                "DELETE FROM relationship_substrate.person WHERE primary_email = %s",
                ("jane@example.com",),
            )
        conn.commit()

    ingest = _run_cli(
        monkeypatch,
        capsys,
        "--database-url",
        database_url,
        "ingest-next-up",
        "--path",
        str(workbook),
    )
    assert ingest == {"source": "next_up", "events_seen": 1, "events_upserted": 1}

    materialized = _run_cli(
        monkeypatch,
        capsys,
        "--database-url",
        database_url,
        "materialize-exact-emails",
        "--source",
        "next_up",
    )
    assert materialized["source"] == "next_up"
    assert materialized["materialized"] >= 1

    picture = _run_cli(
        monkeypatch,
        capsys,
        "--database-url",
        database_url,
        "export-operating-picture",
        "--from-db",
        "--limit",
        "1000",
    )
    assert picture["relationships"]
    relationship = next(
        row for row in picture["relationships"] if row["metadata"]["primary_email"] == "jane@example.com"
    )
    assert relationship["name"] == "Jane Doe"
    assert relationship["relationship_state"] == "uninterpreted_identity_seed"


def test_agent_cli_eval_local_writes_machine_readable_artifacts(
    database_url, tmp_path, monkeypatch, capsys
):
    run_migrations(database_url)
    workbook = _workbook(tmp_path / "eval_people.xlsx", email="eval@example.com")
    output_dir = tmp_path / "eval-output"

    report = _run_cli(
        monkeypatch,
        capsys,
        "--database-url",
        database_url,
        "eval-local",
        "--next-up-path",
        str(workbook),
        "--output-dir",
        str(output_dir),
        "--skip-msgvault",
    )

    assert report["ok"] is True
    assert report["next_up"]["events_seen"] == 1
    assert report["materialization"]["materialized"] >= 1
    assert report["operating_picture"]["relationships"] >= 1
    assert report["identity_candidates"]["source"] == "identity_candidate"
    assert (output_dir / "eval_report.json").exists()
    assert (output_dir / "relationship_operating_picture.json").exists()


def test_agent_cli_eval_local_can_include_calendar_json(database_url, tmp_path, monkeypatch, capsys):
    run_migrations(database_url)
    localpart = f"eval-calendar-{uuid4().hex}"
    email = f"{localpart}@example.com"
    workbook = _workbook(tmp_path / "eval_calendar_people.xlsx", email=email)
    calendar_path = tmp_path / "eval-calendar.json"
    calendar_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": f"event-{localpart}",
                        "summary": "Eval calendar event",
                        "start": {"dateTime": "2026-05-03T10:00:00-04:00"},
                        "attendees": [
                            {"email": "braydon@example.com", "self": True},
                            {"email": email, "displayName": "Eval Calendar"},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "eval-calendar-output"

    report = _run_cli(
        monkeypatch,
        capsys,
        "--database-url",
        database_url,
        "eval-local",
        "--next-up-path",
        str(workbook),
        "--calendar-path",
        str(calendar_path),
        "--output-dir",
        str(output_dir),
        "--skip-msgvault",
    )

    assert report["calendar"]["ingestion"]["events_seen"] == 1
    assert report["calendar"]["materialization"]["attendees_materialized"] >= 1


def test_agent_cli_generates_identity_candidates(database_url, monkeypatch, capsys):
    run_migrations(database_url)
    localpart = f"cliidentitycandidate{uuid4().hex}"
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO relationship_substrate.person (
                  display_name, primary_email, source_posture, provenance_status
                )
                VALUES
                  ('CLI Identity Candidate', %s, 'direct_interaction', 'test'),
                  ('CLI Identity Candidate', %s, 'direct_interaction', 'test')
                ON CONFLICT (primary_email)
                DO UPDATE SET display_name = EXCLUDED.display_name
                """,
                (f"{localpart}@example.com", f"{localpart}@other.example"),
            )
        conn.commit()

    report = _run_cli(
        monkeypatch,
        capsys,
        "--database-url",
        database_url,
        "generate-identity-candidates",
    )

    assert report["source"] == "identity_candidate"
    assert report["candidate_pairs"] >= 1
    assert report["open_candidates"] >= 1


def test_agent_cli_reviews_identity_candidate(database_url, monkeypatch, capsys):
    run_migrations(database_url)
    localpart = f"clireviewcandidate{uuid4().hex}"
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO relationship_substrate.person (
                  display_name, primary_email, source_posture, provenance_status
                )
                VALUES
                  ('CLI Review Candidate', %s, 'direct_interaction', 'test'),
                  ('CLI Review Candidate', %s, 'direct_interaction', 'test')
                ON CONFLICT (primary_email)
                DO UPDATE SET display_name = EXCLUDED.display_name
                """,
                (f"{localpart}@example.com", f"{localpart}@other.example"),
            )
        conn.commit()

    _run_cli(
        monkeypatch,
        capsys,
        "--database-url",
        database_url,
        "generate-identity-candidates",
    )
    listed = _run_cli(
        monkeypatch,
        capsys,
        "--database-url",
        database_url,
        "list-identity-candidates",
        "--limit",
        "1000",
    )
    candidate = next(row for row in listed["candidates"] if row["evidence"]["match_key"] == localpart)

    shown = _run_cli(
        monkeypatch,
        capsys,
        "--database-url",
        database_url,
        "show-identity-candidate",
        "--id",
        candidate["id"],
    )
    resolved = _run_cli(
        monkeypatch,
        capsys,
        "--database-url",
        database_url,
        "resolve-identity-candidate",
        "--id",
        candidate["id"],
        "--status",
        "rejected",
        "--note",
        "Not enough evidence to merge.",
    )

    assert shown["id"] == candidate["id"]
    assert resolved["status"] == "rejected"
    assert resolved["evidence"]["review"]["note"] == "Not enough evidence to merge."


def test_agent_cli_ingests_and_materializes_calendar_json(database_url, tmp_path, monkeypatch, capsys):
    run_migrations(database_url)
    calendar_path = tmp_path / "calendar.json"
    localpart = f"calcli{uuid4().hex}"
    calendar_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": f"event-{localpart}",
                        "summary": "Calendar CLI smoke",
                        "start": {"dateTime": "2026-05-02T10:00:00-04:00"},
                        "attendees": [
                            {"email": "braydon@example.com", "self": True},
                            {"email": f"{localpart}@example.com", "displayName": "Calendar Person"},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    ingested = _run_cli(
        monkeypatch,
        capsys,
        "--database-url",
        database_url,
        "ingest-calendar",
        "--path",
        str(calendar_path),
    )
    materialized = _run_cli(
        monkeypatch,
        capsys,
        "--database-url",
        database_url,
        "materialize-calendar-events",
    )
    picture = _run_cli(
        monkeypatch,
        capsys,
        "--database-url",
        database_url,
        "export-operating-picture",
        "--from-db",
        "--limit",
        "1000",
    )

    assert ingested == {"source": "calendar", "events_seen": 1, "events_upserted": 1}
    assert materialized["attendees_materialized"] >= 1
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*)
                FROM relationship_substrate.evidence_ref
                WHERE ref_type = 'calendar_event'
                AND ref_value = %s
                """,
                (f"calendar:{calendar_path.name}:event-{localpart}",),
            )
            assert cur.fetchone() == (1,)
    relationship = next(
        row for row in picture["relationships"] if row["metadata"]["primary_email"] == f"{localpart}@example.com"
    )
    assert relationship["metadata"]["calendar_interaction_count"] == 1
