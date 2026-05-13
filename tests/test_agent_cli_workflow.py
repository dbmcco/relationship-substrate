from __future__ import annotations

import json
import sys
from pathlib import Path

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
        "5",
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
    assert (output_dir / "eval_report.json").exists()
    assert (output_dir / "relationship_operating_picture.json").exists()
