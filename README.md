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
uv run relationship-substrate profile-msgvault --kind both --limit 25
```

Run the agent-oriented local evidence loop:

```bash
uv run relationship-substrate eval-local \
  --next-up-path "/Users/braydon/projects/personal/home_next_up/resources/Intempio CRM people import.xlsx" \
  --output-dir output/eval \
  --limit 25
```

This writes:

- `output/eval/eval_report.json`
- `output/eval/relationship_operating_picture.json`

Agents can also run each step independently:

```bash
uv run relationship-substrate ingest-next-up --path "/Users/braydon/projects/personal/home_next_up/resources/Intempio CRM people import.xlsx"
uv run relationship-substrate materialize-exact-emails --source next_up
uv run relationship-substrate export-operating-picture --from-db --limit 25
```

Export the first operating-picture shape:

```bash
uv run relationship-substrate export-operating-picture
```

Current eval interpretation: the CLI now proves that Next Up curated exports can be ingested and materialized with preserved provenance, and msgvault sender/domain profiles can be read through the supported analytics commands. The operating picture is intentionally conservative: until msgvault interactions are materialized into `interaction` / `relationship_edge`, rows from Next Up remain `curated_export + unknown_upstream` with no relationship-health judgment.
