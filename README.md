<p align="center">
  <img src="docs/hero.png" alt="Relationship Substrate — evidence-backed relationship intelligence" width="100%">
</p>

<h1 align="center">Relationship Substrate</h1>

<p align="center">
  <strong>Evidence-first relationship intelligence for people who work with people.</strong>
</p>

<p align="center">
  A Python/Postgres/pgvector substrate that ingests real relationship evidence,<br>
  preserves provenance, resolves identities, and produces honest network intelligence.
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> ·
  <a href="#why">Why This Exists</a> ·
  <a href="#how-it-works">How It Works</a> ·
  <a href="#cli-reference">CLI Reference</a> ·
  <a href="#for-agents">For Agents</a> ·
  <a href="#architecture">Architecture</a>
</p>

---

## Why

Most "relationship intelligence" tools have the same structural problem: **they confuse contact data with relationship truth.**

Your CRM says you know 500 people. Your inbox says you've exchanged emails with 200 of them. Your calendar says you've met 50 of those in the last year. The gap between "in my contacts" and "I have an active, evidence-backed relationship with this person" is where all the value — and all the danger — lives.

Existing tools paper over this gap in three ways:

1. **CRM-driven optimism** — everyone in the database is a "contact" regardless of evidence
2. **Activity-driven noise** — every email exchange counts equally, no matter how transactional
3. **AI-driven hallucination** — LLMs infer relationship warmth from sparse signals and present it as insight

Relationship Substrate takes a different approach: **evidence first, interpretation second, action only with provenance.**

It preserves raw source evidence before it materializes canonical records. It exposes uncertainty instead of hiding it. Recommendations are always traceable to evidence, assumptions, and review state. The highest bar is trust: the system is valuable because it is careful, not because it sounds confident.

## What It Does

Relationship Substrate gives you:

- **An evidence ledger** — every fact about a person, organization, or interaction is traceable to a source event with posture and provenance
- **A canonical network model** — people, organizations, affiliations, contact channels, and interactions, materialized from source evidence
- **Identity resolution** — candidates are surfaced for review, not auto-merged
- **A relationship operating picture** — who is in your network, how strong the evidence is, and how fresh it is
- **Goal-conditioned search** — find people matching a goal (semantic + structured), ranked by evidence strength
- **Model-mediated interpretation** — relationship tone analysis and outreach preparation are model proposals, not hidden heuristics
- **Subject notes** — human/agent corrections layered onto canonical records, never promoted to facts without a governed path

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL with pgvector extension
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

### Install

```bash
git clone https://github.com/dbmcco/relationship-substrate.git
cd relationship-substrate
uv sync
```

### Set Up Database

```bash
psql -d postgres -c "CREATE DATABASE relationship_substrate;"
psql -d relationship_substrate -c "CREATE EXTENSION IF NOT EXISTS vector;"
relationship-substrate migrate
```

### Configure

Set environment variables for your deployment:

```bash
export RELATIONSHIP_SUBSTRATE_DATABASE_URL="postgresql://localhost:5432/relationship_substrate"
export RELATIONSHIP_SUBSTRATE_SELF_EMAILS="you@example.com,you@yourcompany.com"
```

See [Configuration](#configuration) for all options.

### Run the Pipeline

```bash
# Ingest contacts from a curated spreadsheet
relationship-substrate ingest-next-up --path contacts.xlsx

# Ingest email sender profiles from msgvault
relationship-substrate ingest-msgvault-senders --limit 50

# Materialize evidence into canonical records
relationship-substrate materialize-exact-emails --source next_up
relationship-substrate materialize-msgvault-senders

# Generate identity candidates for review
relationship-substrate generate-identity-candidates

# Export the operating picture
relationship-substrate export-operating-picture --from-db --limit 25
```

### Run Tests

```bash
pytest
```

## How It Works

### Evidence Flow

```
source data (email, calendar, spreadsheets, exports)
  → ingestion run
  → source events with posture and provenance
  → canonical network materialization (people, orgs, interactions)
  → bounded evidence packages for model review
  → model proposals (tone, outreach — never auto-committed)
  → operating picture, search, exports
```

### Source Posture

Every piece of evidence carries a posture tag that determines how much trust it gets:

| Posture | Meaning | Example |
|---|---|---|
| `direct_interaction` | First-party interaction evidence | Email exchange, calendar meeting |
| `curated_export` | Human-curated contact data | CRM export, spreadsheet |
| `enrichment` | External data enrichment | Company research, LinkedIn |
| `derived_interpretation` | Model-generated interpretation | Tone analysis, relationship summary |

Curated exports are identity/context seeds unless corroborated by direct interaction evidence. Enrichment is never treated as relationship evidence.

### Freshness

Freshness is mechanical, not a relationship-health score:

| State | Last Interaction |
|---|---|
| `recent` | 0–30 days |
| `active` | 31–120 days |
| `stale` | 121–365 days |
| `dormant` | 366+ days |
| `unknown` | No interaction materialized |

### Identity Resolution

Identity candidates are review suggestions, not auto-merges. The system detects repeated non-generic email localparts across domains, suppresses role accounts (`info@`, `events@`, `hello@`), and surfaces open candidates for human review. Accepted/rejected/superseded decisions prevent the same pair from regenerating.

## CLI Reference

### Ingestion

```bash
relationship-substrate ingest-next-up --path contacts.xlsx
relationship-substrate ingest-msgvault-senders --limit 50
relationship-substrate ingest-calendar --path calendar-export.json
relationship-substrate ingest-msgvault-correspondence --sender someone@example.com --limit 25
```

### Materialization

```bash
relationship-substrate materialize-exact-emails --source next_up
relationship-substrate materialize-msgvault-senders
relationship-substrate materialize-calendar-events
relationship-substrate materialize-msgvault-correspondence
```

### Identity

```bash
relationship-substrate generate-identity-candidates
relationship-substrate list-identity-candidates --status candidate --limit 25
relationship-substrate resolve-identity-candidate --id <id> --status rejected --note "duplicate"
```

### Search & Discovery

```bash
# Search by role keywords
relationship-substrate search-people --role-keywords "consultant,advisor,strategy" --limit 10

# Semantic search with local embeddings
relationship-substrate search-people --semantic-provider ollama \
  --embedding-model mxbai-embed-large:latest \
  --semantic-query "healthcare strategy consultants" \
  --sort semantic --limit 10

# History-backed search (email/calendar evidence + org enrichment)
relationship-substrate search-history-backed-people \
  --actual-employee-count-min 10 --actual-employee-count-max 20 --limit 10
```

### Operating Picture

```bash
relationship-substrate export-operating-picture --from-db --limit 25
relationship-substrate show-person --email someone@example.com
```

### Notes & Corrections

```bash
relationship-substrate record-subject-note \
  --subject-type person --subject someone@example.com \
  --kind context_fit --applies-to outreach_screening \
  --note "Not a fit for current search context."
relationship-substrate list-subject-notes --subject-type person --subject someone@example.com
```

### Model-Mediated Analysis

```bash
# Prepare evidence packet for relationship tone analysis
relationship-substrate prepare-relationship-tone-analysis \
  --email someone@example.com --evidence-limit 10

# Prepare outreach proposal
relationship-substrate prepare-history-backed-outreach-proposal \
  --actual-employee-count-min 10 --actual-employee-count-max 20 --limit 5
```

### Organization Enrichment

```bash
relationship-substrate upsert-organization-enrichment \
  --company "ExampleCorp" --company-type consulting_firm \
  --employee-count-label "11-50" --source-name manual_research

relationship-substrate export-organization-enrichment-worklist --limit 50
relationship-substrate export-history-backed-organization-worklist --limit 50
relationship-substrate import-organization-enrichments --path enrichment.json
```

### Embeddings

```bash
relationship-substrate embed-curated-contacts \
  --provider ollama --model mxbai-embed-large:latest --limit 250
```

## Configuration

| Environment Variable | Default | Description |
|---|---|---|
| `RELATIONSHIP_SUBSTRATE_DATABASE_URL` | `postgresql://localhost:5432/relationship_substrate` | PostgreSQL connection string |
| `RELATIONSHIP_SUBSTRATE_SELF_EMAILS` | (from identity accounts) | Comma-separated self email aliases |
| `RELATIONSHIP_SUBSTRATE_SKIPPED_SENDER_DOMAINS` | (built-in list) | Domains to skip during sender ingestion |
| `RELATIONSHIP_SUBSTRATE_SKIPPED_SYSTEM_LOCALPARTS` | (built-in list) | Local parts to skip (`info`, `events`, etc.) |
| `RELATIONSHIP_SUBSTRATE_SKIPPED_SYSTEM_PREFIXES` | (built-in list) | Prefixes to skip (`noreply`, `digest`, etc.) |
| `MSGVAULT_BIN` | `msgvault` | Path to msgvault binary |
| `MSGVAULT_HOME` | (empty) | Path to msgvault home directory |
| `MSGVAULT_CONFIG` | (empty) | Path to msgvault config file |
| `COGNITION_PRESETS_PATH` | (empty) | Path to model route registry |

## For Agents

This section describes the machine-usable interface for AI agents interacting with Relationship Substrate.

### Agent Context

Relationship Substrate is a **source module** that owns relationship records and exposes typed read/correction surfaces. It is designed to be called by agents, not by humans clicking through screens.

### Record Kinds

The farmable public record kinds are:

- `person` — canonical person record with provenance and evidence refs
- `organization` — canonical organization record with provenance and evidence refs
- `affiliation` — person-to-organization link with role/title and provenance
- `interaction` — materialized relationship interaction backed by source evidence
- `subject_note` — source-owned contextual correction attached to a person or organization

Pydantic contracts live in `relationship_substrate.contracts`. The open-source-safe fixture is at `examples/source_module/relationship_substrate_records.json`.

### Tool Surfaces

| Surface | Purpose |
|---|---|
| `tool.relationship_substrate.operating_picture` | Current relationship operating picture |
| `tool.relationship_substrate.search_small_consulting_firm_contacts` | Goal-conditioned contact search |
| `tool.relationship_substrate.search_history_backed_people` | Email/calendar evidence-backed people search |
| `tool.relationship_substrate.list_subject_notes` | Read contextual corrections |
| `tool.relationship_substrate.record_subject_note` | Write a source-owned correction |

### Agent Rules

1. **Subject notes are contextual evidence, not canonical facts.** Apply them to demote or explain candidates. Do not hide matching records solely because a note exists. Do not promote notes into canonical person/organization facts without a governed promotion path.

2. **Identity candidates are review suggestions, not merges.** Do not auto-accept candidates. Surface them for review with the supporting evidence.

3. **Model proposals must cite evidence.** Relationship tone analysis and outreach proposals must reference specific source events. Code validates cited evidence refs before persisting model output.

4. **Enrichment is not relationship evidence.** Company size, type, and research context are organizational facts with their own provenance. They do not constitute relationship warmth or interaction history.

5. **Freshness is mechanical.** `freshness_state` is derived from interaction dates, not relationship quality. A `dormant` label means "no recent interaction evidence," not "this relationship is bad."

### Pipeline Operations

Agents can run each pipeline step independently or use `run-network-pipeline` for a full refresh:

```bash
relationship-substrate run-network-pipeline \
  --next-up-path /data/contacts/ \
  --output-dir output/ops \
  --sender-limit 500 \
  --correspondence-from-senders 25 \
  --embed-provider ollama \
  --embedding-model mxbai-embed-large:latest \
  --organization-worklist-limit 100 \
  --north-star-limit 25
```

Each run writes timestamped artifacts: pipeline report, sender profiles, correspondence ingestions, organization worklist, operating picture, and North Star query.

### Agent-Readable Output Format

All CLI commands emit JSON to stdout. Key output shapes:

```json
{
  "id": "relationship_operating_picture.user.v1",
  "subject_ref": "person.user",
  "relationships": [
    {
      "id": "relationship.<person_id>",
      "name": "Jane Smith",
      "relationship_state": "uninterpreted_interaction_evidence",
      "evidence_refs": ["person:<person_id>"],
      "metadata": {
        "primary_email": "jane@example.com",
        "interaction_count": 12,
        "freshness_state": "active",
        "days_since_last_interaction": 45
      }
    }
  ]
}
```

## Architecture

### Stack

- **Python** — CLI/library substrate, not a web app
- **PostgreSQL + pgvector** — canonical storage, identity resolution, semantic search
- **Pydantic** — typed contracts for all record kinds
- **Ollama** (optional) — local embeddings for semantic search (`mxbai-embed-large`)
- **msgvault** (optional) — email archive adapter for sender/correspondence ingestion

### Ingestion Sources

Relationship Substrate ingests relationship evidence from multiple sources. Each source has an adapter that reads raw data and produces typed source events with posture and provenance.

| Source | Adapter | What it provides | Posture |
|---|---|---|---|
| **msgvault** | `MsgvaultAdapter` | Email sender profiles, domain aggregates, full correspondence messages (from/to/subject/date/body excerpt). Requires a running [msgvault](https://github.com/dbmcco/msgvault) daemon or CLI binary. | `direct_interaction` |
| **Calendar exports** | `CalendarAdapter` | Google Calendar / n8n-style JSON event payloads with attendees, times, and summaries. | `direct_interaction` |
| **Curated spreadsheets** | `NextUpAdapter` | Contact exports (XLSX/CSV) with name, email, company, title. These are identity/context seeds, not interaction evidence. | `curated_export` |
| **Organization research** | Manual / agent-driven | Company type, employee count, consultant count. Loaded via `import-organization-enrichments`. | `enrichment` |

**msgvault** is an offline email archive tool that syncs Gmail accounts to local storage and exposes sender analytics, domain profiles, and full-text search through a CLI and local HTTP API. Relationship Substrate uses it to:

1. Profile top senders and domains across all synced accounts (`list-senders`, `list-domains`)
2. Ingest correspondence messages for specific people (`search`)
3. Extract interaction evidence (who emailed whom, when, how often)

If msgvault is not available, you can still use calendar exports, curated spreadsheets, and manual organization enrichment. The email ingestion commands will simply fail with a connection error.

To set up msgvault:

```bash
# Install msgvault
msgvault sync --account you@example.com

# Verify it works
msgvault list-senders --json --limit 5

# Point relationship-substrate at it
export MSGVAULT_BIN=msgvault
export MSGVAULT_HOME=/path/to/msgvault/data
export MSGVAULT_CONFIG=/path/to/msgvault/config.toml
```

### Ingestion Pipeline

The full pipeline runs source-by-source through these stages:

```
1. INGEST    Read raw source data → source_events table
               (idempotent — re-running won't duplicate)

2. MATERIALIZE source_events → canonical records
               people, organizations, affiliations, interactions, relationship_edges
               Skips self-aliases, configured domains, and system accounts

3. RESOLVE   Generate identity candidates from repeated localparts across domains
               (review suggestions, not auto-merges)

4. ENRICH    Embed curated contacts with local Ollama for semantic search
               (optional — keyword search works without embeddings)

5. INTERPRET Prepare bounded evidence packages for model review
               Relationship tone, outreach proposals
               (model proposals only — never auto-committed)
```

Each stage can be run independently or all at once with `run-network-pipeline`.

### Design Principles

1. **Evidence first.** Interpretation second. Action only with provenance.
2. **Source posture determines trust.** Direct interaction > curated export > enrichment > derived interpretation.
3. **Identity candidates are reviewable.** No auto-merges.
4. **Model interpretation is auditable.** Tone analysis and outreach proposals cite evidence before persisting.
5. **Freshness is mechanical.** Not a relationship-health score.
6. **CLI-first.** Agent and CLI operation before UI polish.
7. **Substrate independence.** Not tied to any CRM, graph database, or UI framework.

### Module Layout

```
relationship_substrate/
├── adapters/          # Source ingestion adapters (msgvault, calendar, next_up)
├── cli.py             # Agent-oriented CLI surface
├── config.py          # Environment-driven configuration
├── contracts.py       # Pydantic record types (Person, Organization, etc.)
├── db.py              # Database connection and migration runner
├── embeddings.py      # Local embedding generation (Ollama/OpenAI/hash)
├── freshness.py       # Mechanical freshness buckets
├── identity.py        # Identity candidate generation and resolution
├── materialize.py     # Source event → canonical record materialization
├── model_registry.py  # Model route resolution from central registry
├── network_ask.py     # North Star query execution
├── operations.py      # Pipeline orchestration and reporting
├── organizations.py   # Organization enrichment workflow
├── outreach.py        # Outreach proposal preparation
├── read_models.py     # Operating picture and dossier exports
├── relationship_intelligence.py  # Relationship strength workers
├── repositories.py    # Database CRUD operations
├── search.py          # People search (keyword + semantic + structured)
├── self_identity.py   # Self email alias configuration
└── tone_tenor_workers.py  # Model-mediated tone analysis
```

## What This Is Not

- Not a generic CRM
- Not a LinkedIn clone
- Not a black-box relationship-health scorer
- Not a place where enrichment is treated as relationship evidence
- Not a system that presents old imports as current truth
- Not a UI-first app whose data model is shaped by screens
- Not a model playground that writes untraceable state

## License

[MIT](LICENSE)
