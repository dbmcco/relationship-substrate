# Relationship Substrate North Star

## Purpose

Relationship Substrate exists to give the user a private, evidence-first understanding of his personal and professional network.

It should help answer who is in the network, what evidence exists, what the relationship state appears to be, and what action is worth taking next. It must do that without turning weak, stale, or ambiguous signals into false certainty.

## Product Promise

Relationship Substrate should become the trusted substrate behind the user's network intelligence:

- a durable evidence ledger for people, organizations, identities, interactions, and provenance
- a conservative canonical network model that separates facts from interpretation
- a reviewable layer for identity ambiguity, relationship state, freshness, open loops, and next moves
- an agent-usable interface for ingesting sources, inspecting evidence, and producing recommendations

The long-term product experience should feel less like a generic CRM and more like a living operating picture of relationships: who matters, why they matter, what has happened, what is uncertain, and what would be useful to do next.

## Core Principle

Evidence first. Interpretation second. Action only with provenance.

The system should preserve raw source evidence before it materializes canonical records. It should expose uncertainty instead of hiding it. Recommendations should always be traceable to evidence, assumptions, and review state.

## Questions The System Must Answer

1. Who is in my network?
   People, organizations, contact channels, aliases, affiliations, source identities, and unresolved candidate matches.

2. What evidence do we have?
   Email, calendar, curated exports, notes, browser-captured context, LinkedIn or other enrichment, and future sources, each with source posture and provenance.

3. What is the state of the relationship?
   Interaction history, freshness, open loops, personal/professional context, relationship health, overlap with the user's goals, and uncertainty. Mechanical evidence and model interpretation must remain visibly separate.

4. What should I do next?
   Agent-readable recommendations for who to talk to, why now, what context matters, what entry points are available, and what uncertainty remains.

## Canonical Target Workflow

The first North Star workflow is goal-conditioned network search:

1. Ask for people from the user's network matching a goal, such as "consultant-like people at companies where I know 10-15 people."
2. Use embeddings for semantic matching against the goal, plus explicit structured constraints such as known-company count.
3. Return ranked candidates with role, company, known people at that company in the user's substrate, separate organization size/type enrichment, semantic similarity, interaction count, freshness, and source evidence.
4. Evaluate which candidates have the strongest relationship evidence before drafting anything.
5. Research recent context about the selected person or organization with fresh external sources.
6. Draft an email that cites the relationship context and current entry point without pretending enrichment is direct relationship evidence.

The current executable slice is `search-people`: it searches Next Up curated contact evidence, counts known people per company inside the substrate as `known_people_at_company_count`, can include separately sourced `organization_enrichment`, can rank by pgvector semantic similarity when local Ollama embeddings are populated, can rank by materialized relationship strength, and returns provenance. It does not yet research recent news or write outreach.

## Non-Negotiable Principles

- Preserve provenance for every source-derived fact.
- Prefer direct interaction evidence over enrichment or stale contact exports.
- Treat curated exports as identity and context seeds unless corroborated.
- Keep identity candidates reviewable; do not auto-merge ambiguous people.
- Keep relationship health and freshness interpretation out of hidden heuristics.
- Make model-authored interpretation auditable, reversible, and supersedable.
- Skip known internal/self/system noise before it becomes relationship evidence.
- Design for agent and CLI operation before UI polish.
- Keep the substrate independent of Graph CRM architecture, while allowing Graph CRM and State System projections later.

## What Agents Should Be Able To Do

Agents should be able to:

- ingest and replay evidence from msgvault, calendar exports, Next Up workbooks, and future sources
- inspect source events, evidence refs, people, contact channels, interactions, and relationship edges
- generate and review identity candidates
- produce a relationship operating picture with provenance and uncertainty
- prepare a dossier for one person or organization
- recommend contacts for a goal or project with a clear evidence trail
- detect stale relationships, open loops, and useful discussion entry points
- update interpreted state through explicit proposals and journaled commits

## What The System Must Not Do

Relationship Substrate is not:

- a generic CRM
- a LinkedIn clone
- a black-box relationship-health scorer
- a place where enrichment is treated as relationship evidence
- a system that presents old imports as current truth
- a UI-first app whose data model is shaped by screens
- a model playground that writes untraceable state

## Near-Term Milestones

1. Build a credible local evidence loop from Next Up, msgvault, and calendar evidence.
2. Add person dossiers that show evidence, interactions, identity candidates, and provenance in one agent-readable command.
3. Add a conservative freshness read model based on interaction dates and explicit uncertainty.
4. Add interpreted state proposals for relationship summaries, open loops, and discussion entry points.
5. Expand goal-conditioned contact search into recommendations with evidence-backed rationale.
6. Add recent-news research and outreach drafting as a separate evidence/proposal stage.
7. Add browser or LinkedIn enrichment only as secondary, provenance-marked evidence.
8. Project substrate read models into richer UI or Graph CRM surfaces once the substrate is trustworthy.

## Definition Of Success

The substrate is succeeding when the user can ask:

- Who should I reconnect with about this goal?
- What do I know about this person and how do I know it?
- When did we last meaningfully interact?
- What is unresolved or uncertain about this relationship?
- What is a good next conversation entry point?

and receive an answer that is useful, current, and honest about its evidence.

The highest bar is trust: the system should be valuable because it is careful, not because it sounds confident.
