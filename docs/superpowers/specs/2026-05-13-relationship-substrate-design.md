# Relationship Substrate Design

Date: 2026-05-13
Status: Approved for implementation planning
Scope: New `relationship-substrate` repo under `/home/user/projects/experiments`

## 1. Purpose

Build a Python/Postgres/pgvector substrate for Braydon's personal and professional relationship intelligence.

The system should ingest real relationship evidence, preserve provenance, resolve people and organizations, maintain canonical network records, and auto-commit auditable model-interpreted relationship state. Product surfaces such as dossiers, network maps, freshness queues, meeting prep, and goal-driven recommendations should be projections over the substrate rather than the substrate's first implementation concern.

## 2. Repository Boundary

Create a new repo:

```text
/opt/relationship-substrate
```

This repo owns:

- evidence ledger
- source events
- ingestion adapters
- identity resolution proposals
- canonical person/organization/contact model
- relationship interaction history
- interpreted relationship state
- replay and provenance tests
- substrate read models
- exports/adapters for State System and Graph CRM

`lfw-ai-graph-crm` is reference material and a possible consumer, not the architecture owner. `state-system` provides compatible interpretation, governance, and read-model concepts, but should not be forced to own low-level ingestion or canonical graph storage.

## 3. Runtime And Stack

Start as a CLI/library substrate, not a web app.

Use:

- Python
- Postgres + pgvector
- committed SQL migrations
- Pydantic or dataclasses for contracts
- pytest for ingestion, replay, provenance, and matching behavior
- schema-validated model proposals
- auto-commit with append-only audit and reversible/supersedable interpreted state

Model route and credential handling must follow the central registry guidance in `experiments/AGENTS.md`. Do not hardcode model IDs, provider defaults, base URLs, or provider credential env vars in app code.

## 4. Architectural Flow

All meaningful data enters through an event-first substrate:

```text
source data
-> ingestion_run
-> source_event / source_identity / evidence_ref / evidence_excerpt
-> canonical network materialization
-> bounded evidence package
-> model proposal
-> auto-commit interpreted state
-> state journal / read models / exports
```

Code owns:

- source reads
- idempotency
- sync watermarks
- schema validation
- hard facts such as dates, addresses, message ids, sender/recipient fields, counts, and source paths
- persistence
- audit
- replay
- safe execution boundaries

Models own:

- identity ambiguity beyond exact mechanical matches
- whether an interaction is meaningful
- relationship health
- relationship freshness interpretation
- personal/professional context
- overlap with Braydon's goals, skills, and interests
- open-loop meaning
- discussion entry points
- recommendations and "why now" reasoning

Code must not hide semantic judgment in regexes, keyword lists, fixed scoring formulas, or unreviewed thresholds. Mechanical summaries such as message count and last-seen date are allowed; semantic interpretation belongs in model-owned proposals or explicit policy.

## 5. Data Model

### Evidence Layer

- `ingestion_run`: one adapter execution with source, timestamps, status, counts, errors, and watermarks.
- `source_account`: source account or corpus, such as a msgvault Gmail account, LinkedIn export, or Next Up resource set.
- `source_event`: append-only normalized event from a source.
- `source_identity`: raw identity from a source, such as email, display name, LinkedIn URL, attendee name, or CRM contact id.
- `evidence_ref`: stable pointer to raw material, such as message id, CSV row, workbook row, file path, calendar event id, or browser extraction id.
- `evidence_excerpt`: bounded source text used in model context.
- `sync_watermark`: replay and dedupe boundary.

### Canonical Network Layer

- `person`: canonical human/contact.
- `organization`: canonical company, institution, group, fund, school, or other organization.
- `contact_channel`: email, LinkedIn URL, phone, social URL, or other contact channel.
- `affiliation`: person-to-organization relationship with role/title/source/confidence/provenance.
- `relationship_edge`: relationship between Braydon and another person for v1, with space for person-person edges later.
- `interaction`: email, LinkedIn message, calendar meeting, note, browser capture, imported historical event, or other touchpoint.
- `identity_candidate`: unresolved or proposed link/merge between source identities and canonical people/orgs.

### Interpreted State Layer

- `person_state`: who this person appears to be, current professional/personal context, interests, skills, and uncertainties.
- `relationship_state`: relationship health, freshness, history shape, overlap, trust/context, and next useful move.
- `goal_state`: Braydon's current goals/projects/workstreams for recommendation context.
- `open_loop`: commitments, follow-ups, unanswered questions, promised intros, stale threads, and opportunities to reconnect.
- `freshness_state`: last meaningful touch, active/sleeping/stale interpretation, and rationale.
- `discussion_entry_point`: possible topic, question, ask, or reconnection angle with evidence and risk notes.
- `operating_picture`: rollup for the whole network or a slice of it.

### Proposal And Audit Layer

- `model_proposal`: proposed canonical or interpreted updates with evidence refs, uncertainty, and rationale.
- `commit_result`: accepted, superseded, rejected, blocked, or no-op result.
- `state_journal_entry`: append-only explanation of what changed and why.
- `reversal` / `supersession`: correction path for auto-committed interpretations without deleting history.

Canonical network records should be factual and source-grounded. Interpreted state records can be qualitative and model-owned, but must remain evidence-backed and auditable.

## 6. Provenance And Trust

The substrate must never collapse "we have a record of this person" into "we know this relationship is meaningful."

Each imported fact gets a source posture:

- `direct_interaction`: msgvault message, calendar meeting, LinkedIn message, or manual note about an interaction.
- `curated_export`: CRM/Copper/Coda/Dex/general contact export.
- `enrichment`: LinkedIn profile, browser extraction, public company info.
- `derived_interpretation`: model-generated relationship state, open loop, discussion entry point, or operating picture.
- `unknown_upstream`: useful source, but unclear whether it came from memory, email, CRM, import, or inference.

For Next Up workbooks such as `people.xlsx`, `Intempio CRM people.xlsx`, `Intempio CRM people import.xlsx`, `Intempio CRM companies.xlsx`, and `LDA_Clients.csv`, default posture is:

```text
source_type = curated_export
provenance_status = unknown_upstream
trust_role = identity/context seed
```

These records may seed people, organizations, channels, and affiliations. They do not prove relationship health, freshness, or current salience without supporting direct interaction evidence or explicit later review.

## 7. Source Strategy

Use real interaction evidence first.

### Primary Sources

1. msgvault
   - Strongest source for actual relationship evidence.
   - Use sender/recipient/account/thread/message metadata to build interaction spine.
   - Treat msgvault as read-only.

2. Calendar via n8n or Google Workspace calendar reads
   - Strong evidence for meetings and relationship recency.
   - Useful for attendees, continuity, and meeting-prep context.

3. Next Up curated exports
   - Useful identity/context seeds.
   - Upstream provenance is uncertain and must remain visible.

### Secondary Sources

4. LinkedIn export
   - Use for enrichment and corroboration: URLs, title/company hints, LinkedIn message evidence.
   - LinkedIn-only connections remain enrichment/source identities unless corroborated.

5. Browser extraction
   - Useful for current profile/company enrichment.
   - Should create evidence refs and source events rather than mutating state directly.

## 8. First Ingestion Spike

The first spike should answer:

> Can we build a credible top-of-network picture from actual interaction evidence, while using old contact exports only as identity/context support?

Scope:

1. Create the Python repo skeleton and Postgres/pgvector schema.
2. Add migrations for:
   - `ingestion_run`
   - `source_account`
   - `source_event`
   - `source_identity`
   - `evidence_ref`
   - `evidence_excerpt`
   - `person`
   - `organization`
   - `contact_channel`
   - `affiliation`
   - `identity_candidate`
   - `interaction`
   - `relationship_edge`
   - `relationship_state`
   - `state_journal_entry`
3. Build a msgvault adapter that profiles:
   - top sender candidates
   - top domain candidates
   - recent threads
   - sender/recipient/account directionality
4. Build a Next Up workbook adapter that imports curated contacts as identity/context seeds with `unknown_upstream`.
5. Match contacts to msgvault identities by exact email first.
6. Represent domain/name matches as `identity_candidate` records, not automatic merges.
7. Create canonical people/orgs for:
   - email-backed identities from msgvault, or
   - curated contacts with explicit email/company fields, marked as source-seeded and awaiting interaction support.
8. Generate a read model with:
   - top 25 people by interaction evidence
   - matched contact metadata
   - last interaction date
   - interaction count
   - candidate organization
   - provenance posture
   - unresolved identity conflicts
9. Emit one State System-compatible relationship operating picture JSON artifact.

No UI is required for this spike. Success is a trustworthy JSON/report output and tests proving replay, idempotency, provenance, and matching behavior.

## 9. Validation

Validation should prove substrate trustworthiness.

Required checks:

- Replay/idempotency: running the same msgvault and Next Up ingestion twice does not duplicate source events, people, channels, interactions, or relationship edges.
- Provenance preservation: every canonical and interpreted record points back to source events/evidence refs.
- Source posture: Next Up workbook records retain `curated_export + unknown_upstream` and do not become relationship-health evidence by themselves.
- Identity matching: exact email matches can materialize canonical records; fuzzy/domain/name matches create `identity_candidate` records.
- Model boundary: code does not decide relationship health, relevance, or open-loop meaning with hidden thresholds.
- Auto-commit audit: interpreted state is appended with journal entries and can be superseded/reversed.
- Report quality: the top-25 read model is inspectable enough to spot false positives, stale records, and provenance gaps.

## 10. Risks

- msgvault contains automated/system senders; source classification must be evidence-backed and revisable.
- Historical aliases across Intempio, rvibe, mcco, LightForge Works, Synthyra, and personal Gmail need explicit self-identity handling.
- Old exports may contain inferred or stale data; they should support identity/context, not relationship truth.
- Model costs can grow quickly if every email is interpreted. V1 should mechanically profile first, then send bounded evidence packets to the model.
- If Graph CRM assumptions leak into the substrate, the architecture may drift toward CRM workflows instead of general relationship intelligence.
- If State System is treated as a full runtime before it is ready, ingestion work may stall. Use State System-compatible artifacts first, then deepen integration.

## 11. Open Implementation Decisions

- Choose package management (`uv` is preferred unless repo standards point elsewhere).
- Choose DB access layer: direct `psycopg` with SQL files versus SQLAlchemy Core.
- Define local database name and migration runner.
- Define self-identity model for Braydon's known email aliases and source accounts.
- Define the exact State System-compatible `relationship_operating_picture` schema.
- Decide whether the first model proposal path is fixture-only or uses live model calls behind the central registry.

## 12. Implementation Addendum (2026-05-13)

The initial ingestion spike implementation landed with:

- Python CLI/library scaffold and project metadata.
- Committed SQL migration + migration runner for the relationship-substrate schema (including pgvector columns).
- Provenance-preserving source contracts for curated export events (`unknown_upstream` retained).
- msgvault sender profiling adapter using read-only CLI query output parsing.
- Next Up workbook ingestion adapter producing curated contact source events.
- Exact-email materialization for canonical `person` and `contact_channel` records only (no semantic relationship-health judgment).
- Operating-picture JSON read-model generator with State System-compatible envelope.
- Test coverage for replay/idempotency, provenance posture, adapter parsing, materialization, and read-model shape.

Deferred follow-up tasks were explicitly created in Workgraph:

- `implement-calendar-ingestion`
- `implement-live-model`
- `model-self-identity`
- `implement-db-backed`
- `add-domain-name`
