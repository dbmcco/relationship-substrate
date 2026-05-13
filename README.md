# relationship-substrate

Relationship Substrate is a Python/Postgres/pgvector substrate for Braydon's personal and professional network intelligence.

The first artifact is the approved design spec:

- [2026-05-13 Relationship Substrate Design](docs/superpowers/specs/2026-05-13-relationship-substrate-design.md)

The repo starts as a design-first CLI/library substrate. It is not a Graph CRM profile and not a web app. Its first implementation milestone will prove ingestion, provenance, identity resolution, replay, and interpreted relationship state against local msgvault and Next Up evidence.

## Local Development

Install dependencies:

```bash
uv sync
```

Create local databases:

```bash
psql -d postgres -c "CREATE DATABASE relationship_substrate;"
psql -d postgres -c "CREATE DATABASE relationship_substrate_test;"
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
