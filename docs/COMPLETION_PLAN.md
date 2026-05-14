# Relationship Substrate Completion Plan

## North Star

The finished system lets Braydon ask a goal-oriented network question and review useful, current, evidence-backed answers without thinking about ingestion.

Example:

```text
Who are consultants in my network at firms around 10 people that I should reach out to?
```

The system returns ranked people, relationship evidence, freshness, tone/tenor state, organization enrichment, current research, and draft-only outreach proposals with citations.

The key product correction from the planning review is that ingestion is not the product. Ingestion, enrichment, research, and embeddings are substrate services. The product is the ability to ask a network question and receive a trustworthy relationship packet with enough evidence to decide what to do next.

## Product Boundary

The product is the substrate interaction surface, not the ingestion machinery.

User surface:

- ask a goal
- review ranked candidates
- inspect a relationship packet
- see evidence, uncertainty, and freshness
- generate or regenerate draft-only outreach proposals
- approve, reject, edit, or save feedback

Background machinery:

- msgvault/email sync
- calendar sync
- Next Up replay
- organization enrichment refresh
- embedding/index refresh
- current research snapshots
- stale relationship-state refresh
- citation/evidence normalization

Ingestion should surface only as health, freshness, gaps, and manual refresh controls.

## Architecture Contract

Code owns:

- source evidence capture and provenance
- canonical person, organization, interaction, relationship, and state storage
- structured filters and constraints
- bounded packet assembly
- citation validation
- schema validation
- run health and sync status

Models own:

- qualitative relationship strength interpretation
- goal relevance rationale
- tone and tenor interpretation
- priority labels
- outreach angle
- draft copy
- next-action recommendation

No hidden deterministic fit scores, tone classifiers, priority heuristics, or outreach copy templates should decide semantic meaning.

## Done Criteria

V1 is complete when a single agent/user command can:

1. Accept a goal and structured constraints.
2. Search the history-backed substrate.
3. Ensure enough relationship evidence exists for selected candidates.
4. Attach latest persisted tone/tenor state or mark it missing.
5. Attach organization enrichment and current research snapshots.
6. Produce ranked relationship packets.
7. Produce draft-only outreach proposal packets.
8. Validate all cited internal and external evidence.
9. Save feedback on useful/not useful, outreach edits, and next actions.
10. Report sync health and data freshness without requiring manual ingest commands.

The first acceptance test is the current North Star query:

```text
Give me five people who are consultants, who are at firms that have around ten people on staff.
```

The answer must distinguish:

- actual company size from how many people Braydon knows at the company
- relationship evidence from organization enrichment
- internal evidence from current external research
- model interpretation from stored facts
- outreach drafts from approved outbound actions

## Phase Plan

### Phase 1: Ask-Network Contract

Build one canonical `ask-network` command/API that accepts a goal plus constraints and returns a complete packet skeleton. It should use existing history-backed search, organization enrichment, tone state, evidence refs, and outreach packet code.

Acceptance:

- One command answers the North Star query without separate search/tone/outreach commands.
- Output identifies what is ready, missing, stale, or needs refresh.
- Output contains no hidden semantic ranking beyond mechanical ordering and model-owned proposal fields.

### Phase 2: Evidence Readiness

Automate evidence readiness for selected candidates. If a candidate only has aggregate sender evidence, the system should queue or run bounded correspondence ingestion and then rebuild the packet.

Acceptance:

- Top candidates have bounded message/calendar evidence when available.
- Missing evidence is explicit.
- Manual ingest commands are replaced by `ensure-evidence` behavior inside the orchestration path or background sync.

### Phase 3: Relationship Packet

Create a stable relationship packet shape per person:

- identity and contact channels
- organization enrichment
- relationship edge facts
- latest interactions
- bounded evidence refs
- persisted tone/tenor states
- identity ambiguity
- freshness and stale-state warnings
- model contract for interpretation

Acceptance:

- Packet is compact enough for model use.
- Packet is versioned and reproducible.
- Every surfaced claim links to source evidence or marked uncertainty.

### Phase 4: Research Snapshots

Move current external research from ad hoc JSON files into sourceable research snapshots with timestamps, source URLs, and target person/organization links.

Acceptance:

- Outreach packets cite research snapshot refs separately from relationship evidence.
- Stale or missing research is visible.
- Research refresh can run in the background.

### Phase 5: Model Ranking And Draft Proposals

Add schema-validated model proposal records for:

- relationship relevance to goal
- outreach priority
- suggested angle
- draft-only email
- next action
- cited evidence refs
- cited research refs

Acceptance:

- Code validates citations and schema only.
- Model owns priority, angle, rationale, and copy.
- Drafts are not sent or staged without explicit approval.

### Phase 6: Feedback And State

Capture review feedback as durable state:

- useful/not useful recommendation
- edited outreach
- rejected premise
- preferred angle
- follow-up status
- do-not-contact or caution notes

Acceptance:

- Feedback is model-readable future context.
- Feedback is not converted into hidden deterministic rules.
- Accepted relationship/outreach learning is auditable and reversible.

### Phase 7: First User Surface

Build a compact TUI or CLI surface around the substrate:

- ask goal
- inspect ranked candidates
- open relationship packet
- view evidence
- view research freshness
- generate proposal
- record feedback

Acceptance:

- User never needs to run ingest commands for normal operation.
- The surface can explain why a candidate appeared and what evidence is weak.

### Phase 8: Background Operations

Schedule recurring sync and refresh:

- msgvault sender/correspondence deltas
- calendar deltas
- organization enrichment worklist
- research snapshots
- embedding refresh
- stale relationship-state refresh

Acceptance:

- `status` shows last run, next run, failures, stale queues, and data coverage.
- Failures are actionable.
- Manual refresh is available but not the default path.

## Immediate Execution Order

1. Define the `ask-network` contract.
2. Add the `ask-network` packet command.
3. Add a North Star eval harness for the current consultant query.
4. Add evidence-readiness orchestration for selected candidates.
5. Persist research snapshots instead of ad hoc research JSON.
6. Add model proposal persistence for ranked packets and outreach drafts.
7. Add feedback capture.
8. Build the first review surface.
9. Schedule background sync.
10. Harden entity resolution and stale-state refresh.

## Workgraph Execution Graph

These are the implementation tasks that should carry the repo from the current state to the completed substrate. Dependencies intentionally keep the first usable loop ahead of deeper background automation.

```text
define-ask-network-contract
  -> build-ask-network-cli
    -> add-network-packet-eval-harness
    -> add-evidence-readiness-refresh
    -> add-research-snapshot-store
    -> add-model-ranked-recommendations
      -> persist-network-proposal-packets
        -> add-feedback-state-loop
          -> build-minimal-network-tui
    -> harden-entity-resolution-org-aliases
      -> build-substrate-status-and-background-sync
```

### define-ask-network-contract

Define the canonical request and response contract for a goal-conditioned network ask.

Acceptance:

- Goal, constraints, freshness requirements, candidate count, evidence requirements, and output format are explicit.
- The contract separates facts, evidence refs, research refs, model interpretation, and proposed actions.
- The contract is documented before implementation expands.

### build-ask-network-cli

Implement one CLI command that composes the existing history-backed search, organization enrichment, tone state, research context, and outreach proposal code into one packet.

Acceptance:

- One command can run the North Star query and return ranked packets.
- The command does not require the user to manually run separate ingest, tone, enrichment, or outreach commands.
- Missing/stale inputs are returned as packet readiness warnings, not silent omissions.

### add-network-packet-eval-harness

Create a regression eval for the North Star query.

Acceptance:

- The eval checks candidate count, org-size evidence, relationship evidence, citation coverage, readiness warnings, and draft-only action boundaries.
- The eval can run locally with the current database and artifacts.
- Failures are actionable instead of snapshot-only noise.

### add-evidence-readiness-refresh

Make candidate packet generation ensure bounded email/calendar evidence exists, or clearly report what is missing.

Acceptance:

- Selected candidates get correspondence/calendar evidence refreshed within configured limits when available.
- Existing evidence is reused.
- Packet output records what refresh happened and what could not be refreshed.

### add-research-snapshot-store

Persist external research snapshots as first-class records instead of relying on loose JSON artifacts.

Acceptance:

- Snapshots include subject, source URL, retrieved_at, summary, confidence, and citation ids.
- Outreach packets cite research refs separately from relationship evidence refs.
- Staleness is visible in packet readiness.

### add-model-ranked-recommendations

Add schema-validated model recommendation records for goal fit, priority, relationship rationale, risk, next action, and outreach angle.

Acceptance:

- Code validates schema and citations.
- Models own relevance, rationale, priority, and copy.
- No hidden deterministic semantic score determines recommendation meaning.

### persist-network-proposal-packets

Save generated relationship/recommendation/outreach packets with version, query, inputs, source refs, and timestamps.

Acceptance:

- Packets are reproducible and inspectable.
- A later feedback entry can reference the exact packet version.
- Packet records do not duplicate raw evidence.

### add-feedback-state-loop

Persist user feedback on recommendations and drafts.

Acceptance:

- Useful/not useful, edited draft, rejected premise, preferred angle, next-action status, and caution notes can be saved.
- Feedback is auditable and reversible.
- Future model prompts can include feedback as context without converting it into hardcoded rules.

### build-minimal-network-tui

Build the first user surface around `ask-network`.

Acceptance:

- User can enter a goal, inspect candidates, open a packet, view evidence/research freshness, regenerate a draft, and record feedback.
- Normal operation does not require manual ingest commands.
- The surface stays compact and CLI/TUI friendly.

### harden-entity-resolution-org-aliases

Tighten person and organization identity handling where it affects ranked recommendations.

Acceptance:

- Known aliases and domains do not split obvious organizations.
- Ambiguous merges are surfaced for review instead of auto-merged.
- The North Star query does not produce duplicate candidate organizations from alias drift.

### build-substrate-status-and-background-sync

Operationalize recurring sync and health reporting after the user-facing loop works.

Acceptance:

- Status shows msgvault, calendar, Next Up, enrichment, research, embedding, and stale tone-state freshness.
- Background runs are resumable and bounded.
- Failures produce actionable queues rather than silent data decay.

## Open Risks

- Entity resolution can split people and organizations across domains, aliases, and curated names.
- Research snapshots can become stale or overtrusted.
- Model proposals can sound more certain than the evidence supports.
- Generated outreach can expose sensitive context if packet boundaries are too loose.
- Background sync can become the work instead of serving the user surface.
- Workgraph currently has stale eval tasks and repo push is blocked by missing remote configuration.

## Completion Signal

The project is complete enough for daily use when Braydon can ask a network goal, review ranked relationship packets, approve or reject draft outreach, and see health/freshness status without manually orchestrating ingest, enrichment, tone analysis, or research commands.
