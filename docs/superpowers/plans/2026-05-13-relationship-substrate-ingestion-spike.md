# Relationship Substrate Ingestion Spike Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first working relationship-substrate ingestion spike: Python CLI, Postgres schema, msgvault sender/domain profiling, Next Up curated contact import, exact-email identity matching, and a top-25 operating picture export.

**Architecture:** The repo is an event-first Python CLI/library. Adapters normalize external data into source events and evidence refs, repositories persist canonical network records in Postgres/pgvector, materializers only perform mechanical exact-email matching, and read-model builders emit auditable JSON without making relationship-health judgments in code.

**Tech Stack:** Python 3.14, uv, pytest, psycopg, pydantic, openpyxl, Postgres 16, pgvector, msgvault CLI JSON/query output, Workgraph/Speedrift for execution.

---

## File Structure

- Create `pyproject.toml`: package metadata, dependencies, pytest config, console script.
- Create `relationship_substrate/__init__.py`: package version.
- Create `relationship_substrate/cli.py`: command entry points for migration, ingestion, matching, and export.
- Create `relationship_substrate/config.py`: environment-driven settings and msgvault command defaults.
- Create `relationship_substrate/db.py`: psycopg connection helper and migration runner.
- Create `relationship_substrate/contracts.py`: Pydantic contracts for source posture, evidence, source identities, and read-model rows.
- Create `relationship_substrate/repositories.py`: small DB write/read functions used by adapters and materializers.
- Create `relationship_substrate/adapters/msgvault.py`: msgvault CLI/query adapter.
- Create `relationship_substrate/adapters/next_up.py`: workbook/CSV adapter for curated exports.
- Create `relationship_substrate/materialize.py`: exact-email canonicalization and identity candidate creation.
- Create `relationship_substrate/read_models.py`: top-25 operating picture builder.
- Create `migrations/001_initial.sql`: Postgres schema.
- Create `tests/conftest.py`: test database fixture and migration helper.
- Create `tests/test_contracts.py`: source posture and validation tests.
- Create `tests/test_db_migrations.py`: schema migration smoke test.
- Create `tests/test_msgvault_adapter.py`: msgvault JSON parsing and query command construction.
- Create `tests/test_next_up_adapter.py`: workbook/CSV parsing and provenance posture tests.
- Create `tests/test_materialize.py`: exact-email matching and identity candidate behavior.
- Create `tests/test_read_models.py`: operating picture output shape.
- Modify `.gitignore`: keep `.workgraph/`, generated reports, and local output out of commits.
- Modify `README.md`: add setup and first-spike commands after implementation.

## Task 1: Python Project Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `relationship_substrate/__init__.py`
- Create: `relationship_substrate/cli.py`
- Create: `relationship_substrate/config.py`
- Create: `tests/test_contracts.py`

- [ ] **Step 1: Write the package/CLI smoke test**

Create `tests/test_contracts.py`:

```python
from relationship_substrate import __version__
from relationship_substrate.config import Settings


def test_package_has_version():
    assert __version__ == "0.1.0"


def test_default_settings_are_local_and_read_only_for_msgvault():
    settings = Settings()

    assert settings.database_url == "postgresql://localhost:5432/relationship_substrate"
    assert settings.msgvault_home == "/Volumes/data2/msgvault"
    assert settings.msgvault_config == "/Volumes/data2/msgvault/config.toml"
    assert settings.msgvault_binary == "/Users/braydon/.local/bin/msgvault"
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest tests/test_contracts.py -q
```

Expected: FAIL because `pyproject.toml` and the package do not exist.

- [ ] **Step 3: Add project metadata**

Create `pyproject.toml`:

```toml
[project]
name = "relationship-substrate"
version = "0.1.0"
description = "Event-first relationship intelligence substrate for local network evidence."
requires-python = ">=3.14"
dependencies = [
  "openpyxl>=3.1.5",
  "psycopg[binary]>=3.2.13",
  "pydantic>=2.12.0",
]

[project.scripts]
relationship-substrate = "relationship_substrate.cli:main"

[dependency-groups]
dev = [
  "pytest>=9.0.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

- [ ] **Step 4: Add package files**

Create `relationship_substrate/__init__.py`:

```python
__version__ = "0.1.0"
```

Create `relationship_substrate/config.py`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.environ.get(
        "RELATIONSHIP_SUBSTRATE_DATABASE_URL",
        "postgresql://localhost:5432/relationship_substrate",
    )
    msgvault_binary: str = os.environ.get(
        "MSGVAULT_BIN",
        "/Users/braydon/.local/bin/msgvault",
    )
    msgvault_home: str = os.environ.get(
        "MSGVAULT_HOME",
        "/Volumes/data2/msgvault",
    )
    msgvault_config: str = os.environ.get(
        "MSGVAULT_CONFIG",
        "/Volumes/data2/msgvault/config.toml",
    )
```

Create `relationship_substrate/cli.py`:

```python
from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="relationship-substrate")
    parser.add_argument("--version", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.version:
        from relationship_substrate import __version__

        print(__version__)
    return 0
```

- [ ] **Step 5: Run the test to verify it passes**

Run:

```bash
uv run pytest tests/test_contracts.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml relationship_substrate tests/test_contracts.py
git commit -m "feat: scaffold relationship substrate package"
```

## Task 2: Database Migration Runner And Initial Schema

**Files:**
- Create: `relationship_substrate/db.py`
- Create: `migrations/001_initial.sql`
- Create: `tests/conftest.py`
- Create: `tests/test_db_migrations.py`
- Modify: `relationship_substrate/cli.py`

- [ ] **Step 1: Write the migration smoke test**

Create `tests/conftest.py`:

```python
from __future__ import annotations

import os

import pytest


@pytest.fixture
def database_url() -> str:
    return os.environ.get(
        "RELATIONSHIP_SUBSTRATE_TEST_DATABASE_URL",
        "postgresql://localhost:5432/relationship_substrate_test",
    )
```

Create `tests/test_db_migrations.py`:

```python
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

    assert {
        "evidence_ref",
        "identity_candidate",
        "ingestion_run",
        "interaction",
        "person",
        "relationship_state",
        "source_event",
        "source_identity",
        "state_journal_entry",
    }.issubset(tables)
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run pytest tests/test_db_migrations.py -q
```

Expected: FAIL because `relationship_substrate.db` does not exist, or because the local test database is not created. If the database is missing, create it once:

```bash
createdb relationship_substrate_test
```

- [ ] **Step 3: Add the schema migration**

Create `migrations/001_initial.sql`:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE SCHEMA IF NOT EXISTS relationship_substrate;

CREATE TABLE IF NOT EXISTS relationship_substrate.schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS relationship_substrate.ingestion_run (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_name TEXT NOT NULL,
    adapter_name TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'succeeded', 'failed')),
    source_watermark TEXT,
    stats JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT
);

CREATE TABLE IF NOT EXISTS relationship_substrate.source_account (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_name TEXT NOT NULL,
    account_key TEXT NOT NULL,
    display_name TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source_name, account_key)
);

CREATE TABLE IF NOT EXISTS relationship_substrate.source_event (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ingestion_run_id UUID REFERENCES relationship_substrate.ingestion_run(id) ON DELETE SET NULL,
    source_name TEXT NOT NULL,
    source_event_type TEXT NOT NULL,
    source_event_key TEXT NOT NULL,
    occurred_at TIMESTAMPTZ,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_posture TEXT NOT NULL,
    provenance_status TEXT NOT NULL,
    trust_role TEXT NOT NULL,
    UNIQUE (source_name, source_event_key)
);

CREATE TABLE IF NOT EXISTS relationship_substrate.evidence_ref (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_event_id UUID NOT NULL REFERENCES relationship_substrate.source_event(id) ON DELETE CASCADE,
    ref_type TEXT NOT NULL,
    ref_value TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (ref_type, ref_value)
);

CREATE TABLE IF NOT EXISTS relationship_substrate.evidence_excerpt (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    evidence_ref_id UUID NOT NULL REFERENCES relationship_substrate.evidence_ref(id) ON DELETE CASCADE,
    excerpt_text TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS relationship_substrate.source_identity (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_event_id UUID REFERENCES relationship_substrate.source_event(id) ON DELETE CASCADE,
    identity_type TEXT NOT NULL,
    identity_value TEXT NOT NULL,
    display_name TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (identity_type, identity_value)
);

CREATE TABLE IF NOT EXISTS relationship_substrate.person (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    display_name TEXT NOT NULL,
    primary_email TEXT,
    source_posture TEXT NOT NULL,
    provenance_status TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    content_embedding VECTOR(1536),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (primary_email)
);

CREATE TABLE IF NOT EXISTS relationship_substrate.organization (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    domain TEXT,
    source_posture TEXT NOT NULL,
    provenance_status TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    content_embedding VECTOR(1536),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (domain)
);

CREATE TABLE IF NOT EXISTS relationship_substrate.contact_channel (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    person_id UUID NOT NULL REFERENCES relationship_substrate.person(id) ON DELETE CASCADE,
    channel_type TEXT NOT NULL,
    channel_value TEXT NOT NULL,
    source_identity_id UUID REFERENCES relationship_substrate.source_identity(id) ON DELETE SET NULL,
    source_posture TEXT NOT NULL,
    provenance_status TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (channel_type, channel_value)
);

CREATE TABLE IF NOT EXISTS relationship_substrate.affiliation (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    person_id UUID NOT NULL REFERENCES relationship_substrate.person(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES relationship_substrate.organization(id) ON DELETE CASCADE,
    role_or_title TEXT,
    source_posture TEXT NOT NULL,
    provenance_status TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (person_id, organization_id, role_or_title)
);

CREATE TABLE IF NOT EXISTS relationship_substrate.identity_candidate (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_identity_id UUID NOT NULL REFERENCES relationship_substrate.source_identity(id) ON DELETE CASCADE,
    candidate_type TEXT NOT NULL CHECK (candidate_type IN ('person', 'organization')),
    candidate_id UUID,
    reason TEXT NOT NULL,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'candidate' CHECK (status IN ('candidate', 'accepted', 'rejected', 'superseded')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS relationship_substrate.interaction (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_event_id UUID NOT NULL REFERENCES relationship_substrate.source_event(id) ON DELETE CASCADE,
    interaction_type TEXT NOT NULL,
    occurred_at TIMESTAMPTZ,
    subject TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (source_event_id)
);

CREATE TABLE IF NOT EXISTS relationship_substrate.relationship_edge (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    person_id UUID NOT NULL REFERENCES relationship_substrate.person(id) ON DELETE CASCADE,
    first_interaction_at TIMESTAMPTZ,
    last_interaction_at TIMESTAMPTZ,
    interaction_count INTEGER NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (person_id)
);

CREATE TABLE IF NOT EXISTS relationship_substrate.relationship_state (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    person_id UUID NOT NULL REFERENCES relationship_substrate.person(id) ON DELETE CASCADE,
    state_kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    rationale TEXT NOT NULL,
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    supersedes_id UUID REFERENCES relationship_substrate.relationship_state(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS relationship_substrate.state_journal_entry (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type TEXT NOT NULL,
    entity_id UUID NOT NULL,
    change_kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

- [ ] **Step 4: Add the migration runner**

Create `relationship_substrate/db.py`:

```python
from __future__ import annotations

from pathlib import Path

import psycopg


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = ROOT / "migrations"


def run_migrations(database_url: str) -> None:
    with psycopg.connect(database_url, autocommit=True) as conn:
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = path.name
            with conn.cursor() as cur:
                cur.execute(
                    "CREATE TABLE IF NOT EXISTS public.relationship_substrate_bootstrap(version text primary key)"
                )
                cur.execute(
                    "SELECT 1 FROM public.relationship_substrate_bootstrap WHERE version = %s",
                    (version,),
                )
                if cur.fetchone():
                    continue
                cur.execute(path.read_text())
                cur.execute(
                    "INSERT INTO public.relationship_substrate_bootstrap(version) VALUES (%s)",
                    (version,),
                )
```

Modify `relationship_substrate/cli.py`:

```python
from __future__ import annotations

import argparse

from relationship_substrate.config import Settings
from relationship_substrate.db import run_migrations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="relationship-substrate")
    parser.add_argument("--version", action="store_true")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("migrate")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.version:
        from relationship_substrate import __version__

        print(__version__)
        return 0
    if args.command == "migrate":
        run_migrations(Settings().database_url)
        return 0
    parser.print_help()
    return 0
```

- [ ] **Step 5: Run the migration test**

Run:

```bash
uv run pytest tests/test_db_migrations.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add migrations relationship_substrate/db.py relationship_substrate/cli.py tests/conftest.py tests/test_db_migrations.py
git commit -m "feat: add initial postgres schema"
```

## Task 3: Source Contracts And Repository Writes

**Files:**
- Create: `relationship_substrate/contracts.py`
- Create: `relationship_substrate/repositories.py`
- Modify: `tests/test_contracts.py`

- [ ] **Step 1: Add contract and repository tests**

Append to `tests/test_contracts.py`:

```python
from relationship_substrate.contracts import SourceEventIn, SourcePosture


def test_next_up_source_event_keeps_unknown_upstream():
    event = SourceEventIn(
        source_name="next_up",
        source_event_type="curated_contact",
        source_event_key="next_up:people.xlsx:Contacts:2",
        source_payload={"email": "person@example.com"},
        source_posture=SourcePosture.CURATED_EXPORT,
        provenance_status="unknown_upstream",
        trust_role="identity/context seed",
    )

    assert event.source_posture == SourcePosture.CURATED_EXPORT
    assert event.provenance_status == "unknown_upstream"
```

Create `tests/test_repositories.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_contracts.py tests/test_repositories.py -q
```

Expected: FAIL because contracts and repository functions do not exist.

- [ ] **Step 3: Implement contracts**

Create `relationship_substrate/contracts.py`:

```python
from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class SourcePosture(StrEnum):
    DIRECT_INTERACTION = "direct_interaction"
    CURATED_EXPORT = "curated_export"
    ENRICHMENT = "enrichment"
    DERIVED_INTERPRETATION = "derived_interpretation"
    UNKNOWN_UPSTREAM = "unknown_upstream"


class SourceEventIn(BaseModel):
    source_name: str
    source_event_type: str
    source_event_key: str
    source_payload: dict[str, Any] = Field(default_factory=dict)
    source_posture: SourcePosture
    provenance_status: str
    trust_role: str
```

- [ ] **Step 4: Implement repository write**

Create `relationship_substrate/repositories.py`:

```python
from __future__ import annotations

from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from relationship_substrate.contracts import SourceEventIn


def upsert_source_event(database_url: str, event: SourceEventIn) -> UUID:
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO relationship_substrate.source_event (
                  source_name,
                  source_event_type,
                  source_event_key,
                  source_payload,
                  source_posture,
                  provenance_status,
                  trust_role
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_name, source_event_key)
                DO UPDATE SET source_payload = EXCLUDED.source_payload
                RETURNING id
                """,
                (
                    event.source_name,
                    event.source_event_type,
                    event.source_event_key,
                    Jsonb(event.source_payload),
                    event.source_posture.value,
                    event.provenance_status,
                    event.trust_role,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return row[0]
```

- [ ] **Step 5: Run tests**

Run:

```bash
uv run pytest tests/test_contracts.py tests/test_repositories.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add relationship_substrate/contracts.py relationship_substrate/repositories.py tests/test_contracts.py tests/test_repositories.py
git commit -m "feat: add source event contracts"
```

## Task 4: msgvault Adapter

**Files:**
- Create: `relationship_substrate/adapters/__init__.py`
- Create: `relationship_substrate/adapters/msgvault.py`
- Create: `tests/test_msgvault_adapter.py`
- Modify: `relationship_substrate/cli.py`

- [ ] **Step 1: Write adapter tests**

Create `tests/test_msgvault_adapter.py`:

```python
from relationship_substrate.adapters.msgvault import MsgvaultAdapter, parse_query_output
from relationship_substrate.config import Settings


def test_parse_query_output_returns_rows():
    payload = {
        "columns": ["from_email", "message_count"],
        "rows": [["person@example.com", 7]],
        "row_count": 1,
    }

    rows = parse_query_output(payload)

    assert rows == [{"from_email": "person@example.com", "message_count": 7}]


def test_sender_query_command_uses_msgvault_read_only_cli():
    adapter = MsgvaultAdapter(Settings())

    command = adapter.build_query_command("SELECT * FROM v_senders LIMIT 1")

    assert command[:5] == [
        "/Users/braydon/.local/bin/msgvault",
        "--home",
        "/Volumes/data2/msgvault",
        "--config",
        "/Volumes/data2/msgvault/config.toml",
    ]
    assert command[-3:] == ["query", "--format", "json"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_msgvault_adapter.py -q
```

Expected: FAIL because the adapter does not exist.

- [ ] **Step 3: Implement the adapter**

Create `relationship_substrate/adapters/__init__.py`:

```python
"""Source adapters for relationship-substrate."""
```

Create `relationship_substrate/adapters/msgvault.py`:

```python
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any

from relationship_substrate.config import Settings


def parse_query_output(payload: dict[str, Any]) -> list[dict[str, Any]]:
    columns = payload["columns"]
    return [dict(zip(columns, row, strict=True)) for row in payload["rows"]]


@dataclass(frozen=True)
class MsgvaultAdapter:
    settings: Settings

    def build_query_command(self, sql: str) -> list[str]:
        return [
            self.settings.msgvault_binary,
            "--home",
            self.settings.msgvault_home,
            "--config",
            self.settings.msgvault_config,
            "query",
            "--format",
            "json",
            sql,
        ]

    def top_sender_candidates(self, limit: int = 100) -> list[dict[str, Any]]:
        sql = f"""
        SELECT from_email, from_name, message_count, first_seen, last_seen
        FROM v_senders
        ORDER BY message_count DESC
        LIMIT {int(limit)}
        """
        completed = subprocess.run(
            self.build_query_command(sql),
            check=True,
            capture_output=True,
            text=True,
        )
        return parse_query_output(json.loads(completed.stdout))
```

- [ ] **Step 4: Wire the CLI command**

Modify `relationship_substrate/cli.py` so it includes:

```python
from relationship_substrate.adapters.msgvault import MsgvaultAdapter
```

and in `build_parser()` add:

```python
    profile = subparsers.add_parser("profile-msgvault")
    profile.add_argument("--limit", type=int, default=25)
```

and in `main()` add before help fallback:

```python
    if args.command == "profile-msgvault":
        rows = MsgvaultAdapter(Settings()).top_sender_candidates(args.limit)
        for row in rows:
            print(row)
        return 0
```

- [ ] **Step 5: Run adapter tests**

Run:

```bash
uv run pytest tests/test_msgvault_adapter.py -q
```

Expected: PASS.

- [ ] **Step 6: Run a live smoke command**

Run:

```bash
uv run relationship-substrate profile-msgvault --limit 5
```

Expected: prints five sender candidate dictionaries from msgvault. If msgvault emits logs on stderr, stdout still contains parseable rows from the adapter path.

- [ ] **Step 7: Commit**

```bash
git add relationship_substrate/adapters relationship_substrate/cli.py tests/test_msgvault_adapter.py
git commit -m "feat: add msgvault profiling adapter"
```

## Task 5: Next Up Curated Export Adapter

**Files:**
- Create: `relationship_substrate/adapters/next_up.py`
- Create: `tests/test_next_up_adapter.py`

- [ ] **Step 1: Write parser tests**

Create `tests/test_next_up_adapter.py`:

```python
from pathlib import Path

from openpyxl import Workbook

from relationship_substrate.adapters.next_up import iter_people_workbook_events
from relationship_substrate.contracts import SourcePosture


def test_people_workbook_rows_are_unknown_upstream_curated_exports(tmp_path: Path):
    workbook = tmp_path / "people.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Contacts"
    ws.append(["First Name", "Last Name", "Title", "Company", "Email"])
    ws.append(["Jane", "Doe", "VP Product", "ExampleCo", "jane@example.com"])
    wb.save(workbook)

    events = list(iter_people_workbook_events(workbook))

    assert len(events) == 1
    assert events[0].source_posture == SourcePosture.CURATED_EXPORT
    assert events[0].provenance_status == "unknown_upstream"
    assert events[0].trust_role == "identity/context seed"
    assert events[0].source_payload["email"] == "jane@example.com"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_next_up_adapter.py -q
```

Expected: FAIL because the adapter does not exist.

- [ ] **Step 3: Implement workbook adapter**

Create `relationship_substrate/adapters/next_up.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Iterator

from openpyxl import load_workbook

from relationship_substrate.contracts import SourceEventIn, SourcePosture


def _normalize_header(value: object) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def iter_people_workbook_events(path: Path) -> Iterator[SourceEventIn]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    sheet = workbook["Contacts"]
    rows = sheet.iter_rows(values_only=True)
    headers = [_normalize_header(value) for value in next(rows)]
    for row_number, values in enumerate(rows, start=2):
        record = dict(zip(headers, values, strict=False))
        email = record.get("email")
        first_name = record.get("first_name")
        last_name = record.get("last_name")
        if not email and not first_name and not last_name:
            continue
        payload = {
            "first_name": first_name,
            "last_name": last_name,
            "title": record.get("title"),
            "company": record.get("company"),
            "email": email,
            "row_number": row_number,
            "path": str(path),
        }
        yield SourceEventIn(
            source_name="next_up",
            source_event_type="curated_contact",
            source_event_key=f"next_up:{path.name}:Contacts:{row_number}",
            source_payload=payload,
            source_posture=SourcePosture.CURATED_EXPORT,
            provenance_status="unknown_upstream",
            trust_role="identity/context seed",
        )
```

- [ ] **Step 4: Run parser tests**

Run:

```bash
uv run pytest tests/test_next_up_adapter.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add relationship_substrate/adapters/next_up.py tests/test_next_up_adapter.py
git commit -m "feat: add next up curated contact adapter"
```

## Task 6: Exact-Email Materialization

**Files:**
- Create: `relationship_substrate/materialize.py`
- Create: `tests/test_materialize.py`
- Modify: `relationship_substrate/repositories.py`

- [ ] **Step 1: Write materialization tests**

Create `tests/test_materialize.py`:

```python
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
            cur.execute("SELECT display_name, primary_email FROM relationship_substrate.person WHERE id = %s", (person_id,))
            assert cur.fetchone() == ("Jane Doe", "jane@example.com")
            cur.execute("SELECT channel_value FROM relationship_substrate.contact_channel WHERE person_id = %s", (person_id,))
            assert cur.fetchone() == ("jane@example.com",)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_materialize.py -q
```

Expected: FAIL because `materialize.py` does not exist.

- [ ] **Step 3: Add repository helpers**

Append to `relationship_substrate/repositories.py`:

```python

def get_source_event(database_url: str, source_event_id) -> dict:
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, source_payload, source_posture, provenance_status
                FROM relationship_substrate.source_event
                WHERE id = %s
                """,
                (source_event_id,),
            )
            row = cur.fetchone()
    if row is None:
        raise ValueError(f"source event not found: {source_event_id}")
    return {
        "id": row[0],
        "source_payload": row[1],
        "source_posture": row[2],
        "provenance_status": row[3],
    }
```

- [ ] **Step 4: Implement materialization**

Create `relationship_substrate/materialize.py`:

```python
from __future__ import annotations

from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from relationship_substrate.repositories import get_source_event


def _clean_email(value: object) -> str | None:
    if value is None:
        return None
    email = str(value).strip().lower()
    return email or None


def _display_name(payload: dict) -> str:
    first = str(payload.get("first_name") or "").strip()
    last = str(payload.get("last_name") or "").strip()
    name = " ".join(part for part in [first, last] if part)
    return name or payload.get("email") or "Unknown person"


def materialize_curated_contact(database_url: str, source_event_id: UUID) -> UUID:
    event = get_source_event(database_url, source_event_id)
    payload = event["source_payload"]
    email = _clean_email(payload.get("email"))
    if email is None:
        raise ValueError("curated contact requires an email for v1 materialization")

    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO relationship_substrate.person (
                  display_name, primary_email, source_posture, provenance_status, metadata
                )
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (primary_email)
                DO UPDATE SET display_name = EXCLUDED.display_name, updated_at = now()
                RETURNING id
                """,
                (
                    _display_name(payload),
                    email,
                    event["source_posture"],
                    event["provenance_status"],
                    Jsonb({"trust_role": "identity/context seed"}),
                ),
            )
            person_id = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO relationship_substrate.contact_channel (
                  person_id, channel_type, channel_value, source_posture, provenance_status
                )
                VALUES (%s, 'email', %s, %s, %s)
                ON CONFLICT (channel_type, channel_value)
                DO UPDATE SET person_id = EXCLUDED.person_id
                """,
                (person_id, email, event["source_posture"], event["provenance_status"]),
            )
        conn.commit()
    return person_id
```

- [ ] **Step 5: Run materialization tests**

Run:

```bash
uv run pytest tests/test_materialize.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add relationship_substrate/materialize.py relationship_substrate/repositories.py tests/test_materialize.py
git commit -m "feat: materialize exact email contacts"
```

## Task 7: Top-25 Operating Picture Read Model

**Files:**
- Create: `relationship_substrate/read_models.py`
- Create: `tests/test_read_models.py`
- Modify: `relationship_substrate/cli.py`

- [ ] **Step 1: Write read model test**

Create `tests/test_read_models.py`:

```python
from relationship_substrate.read_models import build_relationship_operating_picture


def test_operating_picture_shape_from_rows():
    rows = [
        {
            "person_id": "person-1",
            "display_name": "Jane Doe",
            "primary_email": "jane@example.com",
            "interaction_count": 4,
            "last_interaction_at": "2026-05-01T12:00:00Z",
            "source_posture": "direct_interaction",
            "provenance_status": "msgvault",
        }
    ]

    picture = build_relationship_operating_picture(rows)

    assert picture["state_system_role"] == "state_system_interpretation"
    assert picture["relationships"][0]["name"] == "Jane Doe"
    assert picture["relationships"][0]["evidence_refs"] == ["person:person-1"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/test_read_models.py -q
```

Expected: FAIL because `read_models.py` does not exist.

- [ ] **Step 3: Implement read model builder**

Create `relationship_substrate/read_models.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def build_relationship_operating_picture(rows: list[dict[str, Any]]) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    return {
        "id": "relationship_operating_picture.braydon.v1",
        "subject_ref": "person.braydon",
        "generated_at": now,
        "system_of_record_ref": "relationship_substrate",
        "state_system_role": "state_system_interpretation",
        "relationships": [
            {
                "id": f"relationship.{row['person_id']}",
                "name": row["display_name"],
                "relationship_state": "uninterpreted_interaction_evidence",
                "interpretation": (
                    "Mechanical interaction evidence is present. "
                    "Relationship health is not interpreted by this read model."
                ),
                "evidence_refs": [f"person:{row['person_id']}"],
                "metadata": {
                    "primary_email": row.get("primary_email"),
                    "interaction_count": row.get("interaction_count"),
                    "last_interaction_at": row.get("last_interaction_at"),
                    "source_posture": row.get("source_posture"),
                    "provenance_status": row.get("provenance_status"),
                },
            }
            for row in rows
        ],
        "opportunities": [],
        "open_loops": [],
        "recent_changes": [],
        "evidence_refs": [f"person:{row['person_id']}" for row in rows],
        "freshness": {
            "as_of": now,
            "stale_after": now,
            "watermark_refs": [],
        },
    }
```

- [ ] **Step 4: Add CLI export command for the current read-model shape**

Modify `relationship_substrate/cli.py` to include an `export-operating-picture` subcommand that prints the current read-model shape with no rows. A follow-up Workgraph task will replace the empty row list with the DB-backed top-25 query:

```python
    subparsers.add_parser("export-operating-picture")
```

and:

```python
    if args.command == "export-operating-picture":
        from relationship_substrate.read_models import build_relationship_operating_picture

        print(build_relationship_operating_picture([]))
        return 0
```

- [ ] **Step 5: Run read model tests**

Run:

```bash
uv run pytest tests/test_read_models.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add relationship_substrate/read_models.py relationship_substrate/cli.py tests/test_read_models.py
git commit -m "feat: add operating picture read model"
```

## Task 8: Documentation And Speedrift Validation

**Files:**
- Modify: `README.md`
- Modify: `.gitignore`
- Validate: `.workgraph/drifts check`

- [ ] **Step 1: Update README commands**

Add this section to `README.md`:

~~~markdown
## Local Development

Install dependencies:

```bash
uv sync
```

Create local databases:

```bash
createdb relationship_substrate
createdb relationship_substrate_test
```

Run migrations:

```bash
uv run relationship-substrate migrate
```

Run tests:

```bash
RELATIONSHIP_SUBSTRATE_TEST_DATABASE_URL=postgresql://localhost:5432/relationship_substrate_test uv run pytest
```

Profile msgvault sender candidates:

```bash
uv run relationship-substrate profile-msgvault --limit 25
```

Export the first operating-picture shape:

```bash
uv run relationship-substrate export-operating-picture
```
~~~

- [ ] **Step 2: Ensure generated files are ignored**

Ensure `.gitignore` contains:

```gitignore
.workgraph/
reports/
output/
*.log
```

- [ ] **Step 3: Run full tests**

Run:

```bash
RELATIONSHIP_SUBSTRATE_TEST_DATABASE_URL=postgresql://localhost:5432/relationship_substrate_test uv run pytest
```

Expected: PASS.

- [ ] **Step 4: Run drift check for implementation task**

Run:

```bash
./.workgraph/drifts check --task rs-implementation-spike --write-log --create-followups
```

Expected: exit code `0` or `3`. If `3`, inspect findings and create explicit follow-up Workgraph tasks rather than expanding the implementation task silently.

- [ ] **Step 5: Commit**

```bash
git add README.md .gitignore
git commit -m "docs: add local development workflow"
```

## Self-Review

Spec coverage:

- Repo and stack are covered by Task 1.
- Postgres/pgvector schema is covered by Task 2.
- Source posture and provenance are covered by Task 3 and Task 5.
- msgvault interaction evidence starts in Task 4.
- Next Up curated export handling starts in Task 5.
- Exact-email matching starts in Task 6.
- State System-compatible operating picture starts in Task 7.
- Speedrift validation and local workflow are covered by Task 8.

Known follow-up after this plan:

- DB-backed top-25 operating-picture query.
- Calendar/n8n adapter.
- Live model proposal path through the central registry.
- Self-identity alias model for Braydon's historical email accounts.
- Domain/name identity candidates beyond exact email.
