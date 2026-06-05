# Relationship Substrate Source Module

Relationship Substrate is a reusable source module for evidence-backed relationship records. It owns its source records and exposes typed read/correction surfaces for State System, personal substrate, and other runtimes to declare or call through capability packs.

## Record Kinds

The farmable public record kinds are:

- `person`: canonical person record with provenance and evidence refs.
- `organization`: canonical organization record with provenance and evidence refs.
- `affiliation`: person-to-organization relationship with role/title and provenance.
- `interaction`: materialized relationship interaction backed by source evidence.
- `subject_note`: source-owned contextual note attached to a `person` or `organization`.

Pydantic contracts for these records live in `relationship_substrate.contracts`. The open-source-safe fixture is `examples/source_module/relationship_substrate_records.json`.

## Tool Surfaces

Primary read surfaces:

- `tool.relationship_substrate.operating_picture`
- `tool.relationship_substrate.search_small_consulting_firm_contacts`
- `tool.relationship_substrate.search_history_backed_people`
- `tool.relationship_substrate.list_subject_notes`

Primary correction write surface:

- `tool.relationship_substrate.record_subject_note`

`search_history_backed_people` is the backing read surface for higher-level relationship search routes that need email/calendar-derived relationship evidence plus organization enrichment. Higher-level routes may call narrower search tools first, but they should declare this as the fallback/backing source rather than treating it as an unrelated ad hoc query.

## Subject Note Semantics

`record_subject_note` is a source-owned correction write with `effect_type=source_owned_correction_write`. It records subject, `note_kind`, `applies_to`, note text, evidence refs, source/source_ref, metadata, and supersession when available.

It is not an external side effect. It does not send email, mutate a CRM, publish state, or authorize outreach.

Search and list outputs should expose notes as `subject_note_context`. Compatibility aliases such as `person_notes`, `subject_notes`, and CLI `notes` may remain temporarily, but new consumers should read `subject_note_context`.

Agents must apply subject notes as contextual evidence:

- demote or explain candidates when a note changes fit for the requested context
- cite or summarize the relevant note when it affects a recommendation
- do not hide matching records solely because a subject note exists
- do not promote contextual notes into canonical person or organization facts without a governed promotion path

The route-level `answer_contract_policy` name for this rule is
`subject_note_context_demote_explain_not_hide`. Relationship Substrate fixtures
and docs should use that exact public name so State System packages, agent routes
routes, and OSS examples stay aligned.

## Tool Action Contract Names

The public ToolActionContract names are:

- `tool_action.relationship_substrate.operating_picture`
- `tool_action.relationship_substrate.list_subject_notes`
- `tool_action.relationship_substrate.search_small_consulting_firm_contacts`
- `tool_action.relationship_substrate.search_history_backed_people`
- `tool_action.relationship_substrate.record_subject_note`

`search_small_consulting_firm_contacts` declares
`search_history_backed_people` as its backing read surface. `record_subject_note`
declares `effect_type=source_owned_correction_write` and
`requires_external_action_approval=false`.

## Boundary With State System And Personal Substrate

Relationship Substrate owns relationship records and source-owned corrections. State System and personal substrate may declare capabilities, route questions, run preflight/freshness checks, and federate summaries, but they should not copy raw person, organization, affiliation, interaction, or subject-note rows into their own canonical stores.

State System's SourceModuleSpec entry declares the interface. Relationship Substrate provides the implementation and reusable contracts.
