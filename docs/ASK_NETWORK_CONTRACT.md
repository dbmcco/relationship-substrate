# Ask Network Contract

## Purpose

`ask-network` is the canonical user-facing substrate contract for a goal-conditioned network question.

It turns a user goal plus explicit constraints into ranked, evidence-backed relationship packets. It does not run outreach, send messages, merge identities, or hide semantic judgment in deterministic code.

The first target question is:

```text
Give me five people who are consultants, who are at firms that have around ten people on staff.
```

The contract must preserve the distinction between:

- actual organization size and the number of people Braydon knows at that organization
- direct relationship evidence and external organization research
- mechanical facts and model-authored interpretation
- draft outreach and approved outbound action

## Command Shape

Initial CLI:

```text
relationship-substrate ask-network \
  --goal "Give me five people who are consultants, who are at firms that have around ten people on staff." \
  --actual-employee-count-min 8 \
  --actual-employee-count-max 15 \
  --consultant-count-min 8 \
  --consultant-count-max 20 \
  --limit 5 \
  --evidence-limit 10 \
  --prior-state-limit 3 \
  --refresh-missing-evidence \
  --refresh-evidence-limit 50 \
  --research-context path/to/research.json
```

`--goal` is always required. Structured constraints are optional but preferred when the user has stated a numeric or operational requirement. Code must not infer hidden numeric filters from the goal string in v1.

## Request Fields

```json
{
  "goal": "string",
  "constraints": {
    "actual_employee_count_min": "integer or null",
    "actual_employee_count_max": "integer or null",
    "consultant_count_min": "integer or null",
    "consultant_count_max": "integer or null",
    "known_people_at_company_min": "integer or null",
    "known_people_at_company_max": "integer or null",
    "semantic_query": "string or null",
    "semantic_provider": "ollama | openai | hash | null",
    "embedding_model": "string or null"
  },
  "limits": {
    "candidate_limit": "integer",
    "evidence_limit": "integer",
    "prior_state_limit": "integer",
    "refresh_evidence_limit": "integer or null"
  },
  "freshness": {
    "require_current_research": "boolean",
    "research_context_path": "string or null",
    "allow_stale_relationship_state": "boolean"
  },
  "output": {
    "format": "json",
    "include_outreach_prompt": "boolean",
    "include_draft_validation": "boolean"
  }
}
```

## Response Shape

```json
{
  "ask_stage": "network_relationship_packet",
  "contract_version": 1,
  "query": {},
  "readiness": {},
  "count": 0,
  "people": [],
  "research_context": {},
  "model_contract": {},
  "relationship_tone_model_contract": {}
}
```

The response is a packet for model review and user inspection. It is not itself a final answer unless a model proposal has been attached and validated.

## Query Block

The `query` block records exactly what code executed.

Required fields:

- `goal`
- `constraints`
- `limits`
- `semantic_query`
- `semantic_provider`
- `embedding_model`
- `search_mode`

`search_mode` is one of:

- `history_backed`: uses msgvault/calendar-backed people and organization enrichment
- `curated`: uses curated contact records
- `hybrid`: combines both, when implemented

V1 should use `history_backed` for the North Star query.

## Readiness Block

The `readiness` block reports whether the packet is complete enough for model ranking or outreach drafting.

Required fields:

```json
{
  "ready_for_model_ranking": true,
  "ready_for_outreach_drafting": true,
  "warnings": [],
  "missing": [],
  "stale": [],
  "refresh_actions": []
}
```

Examples:

- `missing`: `research_context`, `relationship_evidence`, `organization_enrichment`
- `stale`: `relationship_tone_tenor_state`, `research_snapshot`
- `refresh_actions`: bounded correspondence refresh, calendar refresh, enrichment lookup

Readiness is mechanical. It can say evidence is missing or stale. It must not say a person is a good fit, warm lead, weak relationship, or bad outreach target.

## Person Packet Shape

Each person packet must include:

```json
{
  "email": "string",
  "search_hit": {},
  "relationship_intelligence": {},
  "relationship_tone_tenor": {},
  "packet_readiness": {},
  "evidence_summary": {},
  "organization_context": {},
  "model_inputs": {}
}
```

### search_hit

The existing `search_history_backed_people` row is the base record.

It must preserve:

- `email`
- `display_name`
- `domain`
- direct interaction counts
- first and last interaction dates
- mechanical freshness
- organization enrichment fields
- provenance fields

Actual organization size must come from organization enrichment, not known-people counts.

### relationship_intelligence

The existing `prepare_relationship_intelligence_packet` output is the relationship evidence block.

It must preserve:

- canonical person
- mechanical relationship facts
- bounded evidence refs
- relationship state contract

Mechanical facts can include interaction counts and freshness. They must not include tone, priority, relationship quality, or next-action judgment.

### relationship_tone_tenor

The existing `prepare_relationship_tone_tenor_analysis_packet` person block is the tone-state block.

It must preserve:

- person
- relationship edge
- contact channels
- dossier counts
- prior `relationship_tone_tenor` states

If no persisted tone state exists, the packet should report that as missing or stale. Code must not synthesize a tone summary.

### evidence_summary

Mechanical rollup for quick inspection:

```json
{
  "evidence_ref_count": 0,
  "latest_interaction_at": "datetime or null",
  "email_message_count": 0,
  "calendar_interaction_count": 0,
  "has_direct_relationship_evidence": true,
  "has_prior_tone_state": true,
  "has_organization_enrichment": true
}
```

This is not a score. It is a compact readiness and evidence inventory.

### organization_context

Organization facts copied or normalized from the search hit:

```json
{
  "name": "string or null",
  "domain": "string or null",
  "company_type": "string or null",
  "actual_employee_count_min": "integer or null",
  "actual_employee_count_max": "integer or null",
  "employee_count_label": "string or null",
  "consultant_count_estimate": "integer or null",
  "source_name": "string or null",
  "source_url": "string or null",
  "provenance_status": "string or null"
}
```

If organization enrichment is absent, the packet must show that explicitly.

### model_inputs

The model input block is a compact view of what a model may interpret:

```json
{
  "goal": "string",
  "candidate_evidence_refs": [],
  "candidate_research_refs": [],
  "model_may_judge": [
    "goal relevance",
    "relationship strength and tenor",
    "outreach priority",
    "best angle",
    "risk or caution",
    "next action",
    "draft copy"
  ],
  "model_must_cite": [
    "relationship evidence refs for relationship claims",
    "research refs for external/current claims"
  ]
}
```

## Model Contract

Code owns:

- request parsing
- explicit structured constraints
- database reads
- embeddings calls when requested
- packet assembly
- evidence refs
- research refs
- readiness warnings
- schema validation
- citation validation
- persistence of approved packet/proposal/feedback records

Model owns:

- qualitative relevance to the goal
- relationship strength interpretation
- tone and tenor interpretation
- priority label
- best outreach angle
- next-action recommendation
- draft email copy
- explanation phrasing

Code must not:

- parse semantic intent from the goal into hidden filters
- convert relationship quality into a deterministic score
- rank candidates by hidden qualitative heuristics
- infer tone from keywords
- fabricate research or relationship context
- rewrite model output beyond schema/citation validation
- send or stage outreach without explicit approval

## Model Proposal Shape

Future model output attached to an `ask-network` packet should use this shape:

```json
{
  "person_email": "string",
  "priority": "string",
  "goal_fit_rationale": "string",
  "relationship_rationale": "string",
  "relationship_risk_or_caution": "string",
  "best_angle": "string",
  "next_action": "string",
  "draft_email": {
    "subject": "string",
    "body": "string"
  },
  "cited_evidence_refs": [],
  "cited_research_refs": []
}
```

Validation rules:

- `person_email` must exist in the packet.
- `cited_evidence_refs` must exist in supplied relationship evidence.
- `cited_research_refs` must exist in supplied research context.
- At least one cited evidence or research ref is required.
- Extra fields are rejected unless the contract version changes.

## Research Context

V1 can accept the existing loose research JSON as `research_context`.

Required future shape for persisted snapshots:

```json
{
  "snapshots": [
    {
      "id": "string",
      "subject_type": "person | organization | query",
      "subject": "string",
      "retrieved_at": "datetime",
      "summary": "string",
      "confidence": "string",
      "sources": [
        {
          "id": "string",
          "url": "string",
          "title": "string or null",
          "publisher": "string or null",
          "published_at": "datetime or null"
        }
      ]
    }
  ]
}
```

Until research snapshots are persisted, the packet must label research context as an input artifact, not durable substrate truth.

## Background Refresh Contract

`ask-network` may trigger bounded readiness refreshes when `--refresh-missing-evidence` is supplied.

Allowed refresh actions:

- bounded msgvault correspondence ingest for selected candidates
- bounded calendar materialization refresh
- organization enrichment queue creation
- research snapshot queue creation
- embedding refresh request

Refresh actions must be visible in `readiness.refresh_actions`.

V1 implements bounded msgvault correspondence refresh only. Other refresh actions remain future work and should be added as explicit tasks.

## Current V1 Mapping

The first implementation should compose existing functions:

- search: `search_history_backed_people`
- relationship evidence: `prepare_relationship_intelligence_packet`
- tone state: `prepare_relationship_tone_tenor_analysis_packet`
- outreach packet contract: existing outreach model contract
- citation validation: existing `validate_outreach_proposal`

The initial `ask-network` command can reuse `prepare_history_backed_outreach_proposal_packet` internally if it adds:

- `ask_stage`
- `contract_version`
- original `goal`
- explicit `readiness`
- per-person `packet_readiness`
- `evidence_summary`
- `organization_context`
- `model_inputs`

## Completion Test

The v1 command is acceptable when this works:

```text
relationship-substrate ask-network \
  --goal "Give me five people who are consultants, who are at firms that have around ten people on staff." \
  --actual-employee-count-min 8 \
  --actual-employee-count-max 15 \
  --consultant-count-min 8 \
  --consultant-count-max 20 \
  --limit 5
```

Expected result:

- JSON output has `ask_stage = network_relationship_packet`.
- `query.goal` contains the supplied goal.
- `query.constraints.actual_employee_count_*` are preserved.
- `query.constraints.consultant_count_*` are preserved.
- `people` contains at most 5 candidates.
- Each candidate has search hit, relationship intelligence, tone state block, readiness, evidence summary, organization context, and model inputs.
- Organization size evidence is based on enriched actual employee counts.
- Missing research or tone state appears as readiness warnings.
- No deterministic semantic recommendation or draft email is generated by code.

## Eval Harness

`eval-ask-network` runs the same packet assembly and returns the packet plus contract checks:

```text
relationship-substrate eval-ask-network \
  --goal "Give me five people who are consultants, who are at firms that have around ten people on staff." \
  --actual-employee-count-min 8 \
  --actual-employee-count-max 15 \
  --consultant-count-min 8 \
  --consultant-count-max 20 \
  --limit 5 \
  --refresh-missing-evidence
```

The eval checks:

- packet contract shape
- candidate count within limit
- actual organization size evidence
- direct relationship evidence
- visible readiness warnings
- no code-generated draft outreach

The eval is a regression harness for packet readiness, not a model quality judge.
