# relationship-substrate

Relationship Substrate is a Python/Postgres/pgvector substrate for Braydon's personal and professional network intelligence.

The first artifact is the approved design spec:

- [Relationship Substrate North Star](docs/NORTH_STAR.md)
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
  --calendar-path "/path/to/calendar-export.json" \
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
uv run relationship-substrate ingest-msgvault-senders --limit 25
uv run relationship-substrate materialize-msgvault-senders
uv run relationship-substrate ingest-calendar --path "/path/to/calendar-export.json"
uv run relationship-substrate materialize-calendar-events
uv run relationship-substrate generate-identity-candidates
uv run relationship-substrate list-identity-candidates --status candidate --limit 25
uv run relationship-substrate show-identity-candidate --id "<candidate-id>"
uv run relationship-substrate resolve-identity-candidate --id "<candidate-id>" --status rejected --note "review note"
uv run relationship-substrate show-person --email "person@example.com"
uv run relationship-substrate export-operating-picture --from-db --limit 25
```

Sender ingestion skips noisy internal/system senders before materialization. Exact-email materialization also skips configured domains. Defaults include Braydon's known self aliases, the `intempio.com` domain, and common automated local-parts/prefixes such as `events`, `onlinebanking`, `noreply`, `invoice`, and `statement`. Override with:

```bash
RELATIONSHIP_SUBSTRATE_SELF_EMAILS="a@example.com,b@example.com"
RELATIONSHIP_SUBSTRATE_SKIPPED_SENDER_DOMAINS="intempio.com,example.org"
RELATIONSHIP_SUBSTRATE_SKIPPED_SYSTEM_LOCALPARTS="events,onlinebanking"
RELATIONSHIP_SUBSTRATE_SKIPPED_SYSTEM_PREFIXES="noreply,invoice,statement"
```

Export the first operating-picture shape:

```bash
uv run relationship-substrate export-operating-picture
```

Calendar ingestion accepts JSON exports with `items`, `events`, `data`, a bare event object, or a bare list of event objects. The expected event shape matches Google Calendar/n8n-style payloads: `id`, `summary`, `start.dateTime` or `start.date`, and `attendees[].email`. Calendar materialization skips self attendees and configured internal domains, creates attendee evidence, increments relationship edges, and stores `calendar_interaction_count` in operating-picture metadata.

Current eval interpretation: the CLI now proves that Next Up curated exports can be ingested and materialized with preserved provenance, msgvault sender/domain profiles can be read through the supported analytics commands, and calendar exports can be materialized into attendee interaction evidence. Msgvault sender profiles can also be materialized into aggregate `interaction` and `relationship_edge` rows, skipping known Braydon/self aliases by default. The operating picture remains conservative: direct email/calendar counts are interaction evidence, not relationship-health interpretation; rows from Next Up without matching interaction evidence remain `curated_export + unknown_upstream` identity seeds.

Identity candidates are unresolved review suggestions, not merges. The current candidate pass detects repeated non-generic email localparts across domains, suppresses role accounts such as `events`, `info`, and `hello`, and surfaces open candidate counts in the DB-backed operating picture metadata. Candidate review records a decision and note in evidence metadata; accepted/rejected/superseded decisions prevent the same pair from being regenerated.

Person dossiers are factual inspection views for agents. `show-person --email` returns the canonical person, contact channels, relationship edge counters, matching interactions, source events, evidence refs, and identity candidates without adding semantic relationship-health interpretation.
