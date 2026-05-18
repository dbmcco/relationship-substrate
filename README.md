# relationship-substrate

Relationship Substrate is a Python/Postgres/pgvector substrate for evidence-backed relationship intelligence.

The first artifact is the approved design spec:

- [Relationship Substrate North Star](docs/NORTH_STAR.md)
- [2026-05-13 Relationship Substrate Design](docs/superpowers/specs/2026-05-13-relationship-substrate-design.md)

The repo starts as a design-first CLI/library substrate. It is not a Graph CRM profile and not a web app. Its first implementation milestone proves ingestion, provenance, identity resolution, replay, and interpreted relationship state against source evidence.

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

Run the operational substrate refresh:

```bash
uv run relationship-substrate run-network-pipeline \
  --next-up-path "/Users/braydon/projects/personal/home_next_up/resources" \
  --output-dir output/ops \
  --sender-limit 500 \
  --correspondence-from-senders 25 \
  --correspondence-message-limit 50 \
  --embed-provider ollama \
  --embedding-model mxbai-embed-large:latest \
  --embed-limit 500 \
  --organization-worklist-limit 100 \
  --north-star-limit 25
```

This creates the configured Postgres database if needed, runs migrations, ingests the whole Next Up resources directory, profiles msgvault senders/domains, seeds correspondence ingestion from the top non-self/non-excluded senders, materializes email/calendar evidence, generates identity candidates, embeds curated contacts when not skipped, exports the history-backed organization enrichment worklist, and writes the current North Star query artifact. Each run writes timestamped artifacts under `output/ops/<run-id>/`, including:

- `pipeline_report.json`
- `msgvault_profile.json`
- `msgvault_correspondence_ingestions.json`
- `organization_enrichment_worklist.json`
- `north_star_query.json`
- `history_backed_north_star_query.json`
- `operating_picture.json`

Calendar ingestion is included when one or more `--calendar-path` JSON exports are supplied. Use `--skip-embeddings` for a faster structural refresh before starting Ollama-backed semantic search.

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
uv run relationship-substrate record-subject-note --subject-type person --subject "person@example.com" --kind context_fit --applies-to small_consulting_firm_discovery --note "Not a good fit for this search context."
uv run relationship-substrate list-subject-notes --subject-type person --subject "person@example.com"
uv run relationship-substrate prepare-relationship-tone-analysis --email "person@example.com" --evidence-limit 10 --prior-state-limit 3
uv run relationship-substrate prepare-history-backed-outreach-proposal --actual-employee-count-min 10 --actual-employee-count-max 20 --consultant-count-min 10 --consultant-count-max 20 --limit 5 --research-context /path/to/current-research.json --evidence-limit 5
uv run relationship-substrate embed-curated-contacts --provider ollama --model mxbai-embed-large:latest --limit 250
uv run relationship-substrate upsert-organization-enrichment --company "AbbVie" --company-type public_pharmaceutical_company --employee-count-label enterprise --source-name manual_research --source-url "https://www.abbvie.com/"
uv run relationship-substrate export-organization-enrichment-worklist --limit 50
uv run relationship-substrate export-history-backed-organization-worklist --limit 50
uv run relationship-substrate import-organization-enrichments --path /path/to/reviewed-company-enrichment.json
uv run relationship-substrate search-people --role-keywords "consultant,advisor,principal,strategy,operations,supply,medical communications,commercial" --known-people-at-company-min 10 --known-people-at-company-max 15 --limit 10
uv run relationship-substrate search-people --role-keywords "" --semantic-provider ollama --embedding-model mxbai-embed-large:latest --semantic-query "consultants or advisory firms in medcomms, pharma operations, supply chain, or business consulting" --known-people-at-company-min 10 --known-people-at-company-max 15 --sort semantic --limit 10
uv run relationship-substrate search-people --role-keywords "" --semantic-provider ollama --embedding-model mxbai-embed-large:latest --semantic-query "consulting background in medcoms medical communications agency" --actual-employee-count-min 10 --actual-employee-count-max 20 --sort semantic --limit 5
uv run relationship-substrate search-people --role-keywords "" --semantic-provider ollama --embedding-model mxbai-embed-large:latest --semantic-query "consulting background in medcoms medical communications healthcare life sciences strategy consultancy" --consultant-count-min 10 --consultant-count-max 20 --sort semantic --limit 5
uv run relationship-substrate search-history-backed-people --actual-employee-count-min 10 --actual-employee-count-max 20 --consultant-count-min 10 --consultant-count-max 20 --limit 10
uv run relationship-substrate export-operating-picture --from-db --limit 25
```

Sender ingestion skips noisy internal/system senders before materialization. Exact-email materialization also skips configured domains. Defaults include Braydon's known self aliases, `go2impact.com`, `intempio.com`, `intempio.us`, `lehigh.edu`, `mcco.us`, `rvibe.com`, `thepracticalaccountant.com`, and common automated local-parts/prefixes such as `events`, `info`, `daily`, `onlinebanking`, `return`, `noreply`, `invoice`, `statement`, `digest`, `newsletter`, `ship`, `shipment`, `groups-noreply`, `calendar-notification`, `voice-noreply`, `auto-confirm`, and `ordersender`. Override with:

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

Subject notes are explicit user/agent corrections layered onto canonical people or organizations. `record-subject-note` stores notes such as fit caveats, identity context, or relationship caveats with `source_ref`, evidence refs, metadata, and optional supersession. `list-subject-notes`, `show-person`, and history-backed search expose these as `subject_note_context`; the CLI also keeps `notes` as a transitional output alias. Agents should use subject-note context to demote or explain candidates, not to hide records or promote contextual notes into canonical profile facts. `record-person-note` and `list-person-notes` remain compatibility aliases only.

Freshness is mechanical, not a relationship-health score. Operating-picture rows and person dossiers expose `freshness_state`, `days_since_last_interaction`, and `freshness_basis` from the last materialized interaction only: `recent` (0-30 days), `active` (31-120), `stale` (121-365), `dormant` (366+), or `unknown` when no interaction is materialized.

Relationship tone analysis is model-owned. `prepare-relationship-tone-analysis` emits a compact packet with bounded evidence, mechanical relationship facts, prior tone/tenor states, and a model contract. Code does not classify tone, score tenor, or infer relationship health; a model proposal must cite supplied evidence refs before `persist-relationship-state` can store it.

Outreach proposal prep is draft-only. `prepare-history-backed-outreach-proposal` turns the history-backed North Star search results into a compact model packet with the selected search hit, bounded relationship evidence, prior tone/tenor state, organization enrichment, and optional current research context. Code validates cited evidence and research refs but does not choose the angle, write copy, assign priority, or send messages.

Network search is the first executable North Star query. `search-people` searches Next Up curated contact evidence, filters by explicit constraints, ranks by materialized relationship interaction count or embedding similarity, and returns source event provenance plus mechanical freshness. The result field `known_people_at_company_count` is not actual employer size; actual company size/type belongs in `organization_enrichment`, populated separately with `upsert-organization-enrichment` and its own provenance. Use `--known-people-at-company-*` for Braydon's known network count. Use `--actual-employee-count-*` for actual organization size; organizations without employee-count enrichment do not match actual-size filters, and broad ranges such as `11-50` do not satisfy narrower requests such as `10-20`. Use `--consultant-count-*` for separately researched consultant/team counts from company pages, employee-profile counts, or other sourced estimates. `embed-curated-contacts` populates `person.content_embedding` from curated contact context. The default provider is local Ollama at `http://localhost:11434/api/embed`; `mxbai-embed-large:latest` is the current local default. OpenAI remains available through `--provider openai` and `OPENAI_API_KEY`; `--provider hash` exists only for local smoke tests. Network search does not yet perform external recent-news research or draft outreach.

History-backed people search is the operational North Star query for email/calendar-derived relationships and the backing read surface for higher-level relationship search routes. `search-history-backed-people` searches materialized msgvault/calendar people by email domain, joins those domains to reviewed `organization_enrichment`, filters by actual employee count and consultant/team count, ranks by direct interaction count, and returns `subject_note_context` when source-owned corrections exist. This is the right command for questions like: "give me five people who are consultants at consulting firms with around ten people on staff." It complements `search-people`; it does not require the person to exist in a curated Next Up spreadsheet.

## Source Module Contract

Relationship Substrate is intended to be farmable as a SourceModuleSpec provider/consumer. The reusable module boundary covers record kinds `person`, `organization`, `affiliation`, `interaction`, and `subject_note`. The correction write surface is `record_subject_note` / `record-subject-note` with `effect_type=source_owned_correction_write`; it writes audited relationship-context corrections inside the source module and does not authorize external side effects. See [docs/SOURCE_MODULE_SPEC.md](docs/SOURCE_MODULE_SPEC.md) and [examples/source_module/relationship_substrate_records.json](examples/source_module/relationship_substrate_records.json).

Organization enrichment is a separate batch workflow. `export-organization-enrichment-worklist` lists companies from curated contacts with known-network count, sample titles, existing enrichment, and a research prompt. Agents can enrich those companies from institutional knowledge, Perplexity, or direct web research, then load reviewed facts with `import-organization-enrichments`. Imports require `company_name` and `source_name`; supported fields include `company_type`, `employee_count_min`, `employee_count_max`, `employee_count_label`, `consultant_count_estimate`, `source_url`, and `provenance_status`.

History-backed organization enrichment is the operational queue. `export-history-backed-organization-worklist` groups people by email domain, connects domains to Next Up company names when available, and ranks organizations by direct msgvault/calendar interaction evidence before curated-only company counts. The output includes known people count, direct people count, email interaction count, calendar interaction count, last interaction, strongest people, sample titles, current enrichment, mechanical enrichment reasons, and a research prompt. This command is for deciding what to enrich next; it does not decide whether a company is medcoms, consulting, or a good outreach target.
