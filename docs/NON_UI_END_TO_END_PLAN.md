# Non-UI End-to-End Plan

## Scope

This plan finishes the relationship substrate without building a UI or TUI. The target user surface is agent/CLI operation:

```text
ask-network -> ensure evidence -> attach research -> validate model recommendations -> save packet -> record feedback -> report freshness/health
```

The UI/TUI task remains out of scope for this plan.

## Done Means

The non-UI system is ready when an agent can run one scripted workflow that:

1. Refreshes or reports substrate data freshness.
2. Ingests current Next Up, msgvault, and calendar evidence within configured bounds.
3. Normalizes people, organizations, contact channels, interactions, and relationship edges.
4. Backfills embeddings for eligible people.
5. Runs the North Star query through `ask-network`.
6. Ensures direct relationship evidence for selected candidates.
7. Loads current research snapshots or reports missing research work.
8. Includes latest persisted tone/tenor state or reports it as missing.
9. Validates model-ranked recommendations and draft-only outreach.
10. Saves the packet and records feedback against the exact packet version.
11. Runs an end-to-end eval that fails with actionable checks.

## Excluded

- No UI/TUI.
- No automatic sending or staging of outreach.
- No hidden deterministic relationship-quality scoring.
- No LinkedIn/browser scraping path unless added later as a separate source.
- No hardcoded preference learning from feedback.

## Current Completed Spine

- `ask-network` contract and CLI.
- Bounded msgvault evidence refresh for candidates missing correspondence evidence.
- `eval-ask-network` contract eval.
- Model recommendation schema and citation validation.
- Durable research snapshots.
- Durable network packet records.
- Durable feedback records linked to saved packets.
- pgvector columns and curated-contact embedding backfill.

## Remaining Non-UI Work

### 1. Entity And Organization Alias Hardening

Goal: prevent obvious domain/name aliases from splitting organizations or producing duplicate candidates.

Acceptance:

- Domain organizations and curated company-name organizations can be linked without destructive auto-merge.
- Ambiguity is visible as reviewable alias candidates.
- `ask-network` avoids duplicate organization records for obvious domain/name variants.

Workgraph: `harden-entity-resolution-org-aliases`.

### 2. Calendar Pagination And Delta Readiness

Goal: make calendar ingestion robust for paginated exports or repeated pulls.

Acceptance:

- Calendar adapter can consume a directory or paginated export set.
- Re-running ingestion is idempotent.
- Materialization reports seen/upserted/skipped counts.

Workgraph: `paginate-calendar-exports`.

### 3. Semantic Goal Retrieval For Ask-Network

Goal: use embeddings to help retrieve candidates for semantic goals, not just explicit organization-size filters.

Acceptance:

- `ask-network` accepts semantic query/provider/model options.
- History-backed search can use existing person embeddings when present.
- Missing embeddings are reported as readiness/coverage, not silently ignored.
- No deterministic semantic category maps are added.

Workgraph to add: `extend-ask-network-semantic-retrieval`.

### 4. Tone-State Readiness

Goal: make relationship tone/tenor freshness operational instead of a manual side path.

Acceptance:

- `ask-network` reports which candidates need tone-state proposals.
- Agents can export a tone-state worklist from an ask packet.
- Persisted tone states are linked back to cited evidence.

Workgraph to add: `operationalize-tone-state-readiness`.

### 5. Substrate Status And Background Sync

Goal: make ingest/freshness observable and runnable as a bounded background job.

Acceptance:

- `status` reports counts, last run/freshness, missing enrichment, missing research, missing tone state, and embedding coverage.
- Sync command runs bounded Next Up/msgvault/calendar/research/embedding refresh stages.
- Failures become actionable queues.

Workgraph: `build-substrate-status-and-background-sync`.

### 6. End-To-End Non-UI Eval

Goal: prove the full agent workflow without a UI.

Acceptance:

- One command or script runs the North Star workflow end to end.
- It checks candidate count, actual org-size evidence, direct evidence, research refs, tone-state readiness, model proposal validation, packet persistence, and feedback persistence.
- It exits non-zero with actionable failures.

Workgraph to add: `add-non-ui-end-to-end-eval`.

## Execution Order

```text
harden-entity-resolution-org-aliases
  -> build-substrate-status-and-background-sync

paginate-calendar-exports
  -> build-substrate-status-and-background-sync

extend-ask-network-semantic-retrieval
  -> add-non-ui-end-to-end-eval

operationalize-tone-state-readiness
  -> add-non-ui-end-to-end-eval

build-substrate-status-and-background-sync
  -> add-non-ui-end-to-end-eval
```

## Quality Gates

Every task must run:

- focused tests for the changed module
- `uv run pytest -q`
- a CLI smoke test when the task changes CLI behavior
- Speedrift drift check before closing the Workgraph task

## Ready For Braydon

The non-UI system is ready for review when:

- `add-non-ui-end-to-end-eval` is done
- full tests pass
- real North Star eval passes against the local database
- repo has clean git status
- remaining work is clearly UI/TUI or optional source expansion
