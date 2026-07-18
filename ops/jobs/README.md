# Relationship Substrate Jobs

These jobs keep the non-UI substrate fresh. They are repo-local scripts so agents can run,
inspect, and change them without relying on hidden machine scheduler state.

## Jobs

- `substrate-cycle.sh`: one operational cycle. Refreshes msgvault/calendar/next_up materialization,
  writes status, organization enrichment worklist, and the current North Star tone-state worklist.
  Local embedding backfill is disabled by default for laptop power safety.
- `substrate-loop.sh`: runs `substrate-cycle.sh` repeatedly. Default interval: 6 hours. This is intended for interactive or Herdr use.
- `substrate-fleet-refresh.sh`: manual recovery wrapper that runs one bounded `substrate-cycle.sh` and then the State System b-state fleet refresh. The durable launchd jobs use separate cadences instead.
- `nightly-worklists.sh`: exports the current enrichment and tone worklists without mutating ingest.
  It also runs a bounded organization research pass. Default: 25 organizations, apply enabled.
  Local-Ollama tone/tenor and relationship-strength passes are disabled by default for
  laptop power safety. Enable them explicitly when plugged into sufficient power.
  It can run bounded organization-news research snapshots when
  `RELATIONSHIP_SUBSTRATE_ORGANIZATION_NEWS_LIMIT` is non-zero.
- `nightly-worklists-loop.sh`: runs `nightly-worklists.sh` repeatedly. Default interval: 12 hours.
- `catchup-refresh-loop.sh`: runs `nightly-worklists.sh` continuously until organization enrichment,
  tone/tenor, and relationship-strength queues are clean. Once clean, it sleeps 12 hours between
  refreshes and enables bounded organization-news research. If local-Ollama tone/strength work is
  disabled, those queues remain visible but the loop sleeps on the 12-hour interval once
  organization enrichment is drained, until an explicitly enabled local-model pass drains them.

## macOS launchd

The durable schedulers are two one-shot LaunchAgents:

- `~/Library/LaunchAgents/com.dbmcco.relationship-substrate.refresh.plist` runs one bounded
  Relationship Substrate cycle at login and every six hours. Its logs are under
  `~/Library/Logs/relationship-substrate/`.
- `~/Library/LaunchAgents/com.dbmcco.state-system.b-state.fleet-refresh.plist` runs the personal
  b-state fleet refresh at login and every hour. Its logs are under
  `~/Library/Logs/state-system-fleet-refresh/`.

The separate cadences are intentional: the Relationship Substrate corpus has a seven-day
content watermark, while the b-state package has a one-hour freshness policy.

Inspect or reload it with:

```bash
launchctl print "gui/$(id -u)/com.dbmcco.relationship-substrate.refresh"
launchctl print "gui/$(id -u)/com.dbmcco.state-system.b-state.fleet-refresh"
launchctl bootout "gui/$(id -u)/com.dbmcco.relationship-substrate.refresh"
launchctl bootout "gui/$(id -u)/com.dbmcco.state-system.b-state.fleet-refresh"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.dbmcco.relationship-substrate.refresh.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.dbmcco.state-system.b-state.fleet-refresh.plist"
```

The Herdr-only `substrate-loop.sh` should not run at the same time as the launchd wrapper. The launchd job supplies the explicit MsgVault home and config paths; the adapter uses `--local` and bounds each client call with `MSGVAULT_TIMEOUT_SECONDS` (default 120 seconds), so an unavailable archive is reported as a failed cycle instead of holding the coordination lock indefinitely.

## Inputs

Defaults:

- next_up seed: `/data/contacts.xlsx`
- calendar exports:
  - `output/ops/calendar-personal-20180101-20260514.json`
  - `output/ops/calendar-work-20180101-20260514.json`
  - `output/ops/calendar-main-20240101-20260514.json`

Override with colon-separated paths:

```bash
RELATIONSHIP_SUBSTRATE_NEXT_UP_PATHS="/path/a.xlsx:/path/b.xlsx"
RELATIONSHIP_SUBSTRATE_CALENDAR_PATHS="output/ops/calendar-a.json:output/ops/calendar-b.json"
```

## Outputs

- cycle reports: `output/jobs/<run-id>/`
- autonomous backfill artifacts: `output/autonomous/<run-id>/`
- nightly worklists: `output/nightly/<run-id>/`

The scripts do not perform external web/news research yet. They produce the worklists that
the relationship tone/tenor workers should consume next. Organization web research is now
bounded by `RELATIONSHIP_SUBSTRATE_ORGANIZATION_RESEARCH_LIMIT` and can be made dry-run with:

```bash
RELATIONSHIP_SUBSTRATE_ORGANIZATION_RESEARCH_APPLY=0
```

Organization research skips domains or company names that already have a recent research snapshot
before making a Perplexity call. Static organization enrichment defaults to a 30-day skip window,
and current-news research defaults to a 24-hour skip window:

```bash
RELATIONSHIP_SUBSTRATE_ORGANIZATION_RESEARCH_TTL_HOURS=720
RELATIONSHIP_SUBSTRATE_ORGANIZATION_NEWS_TTL_HOURS=24
```

If static organization research returns an unusable response, the worker retries once with a
domain-focused alternate plan. If that also fails, it records an `organization_research_failure`
snapshot and skips that organization until the retry-after window expires:

```bash
RELATIONSHIP_SUBSTRATE_ORGANIZATION_FAILURE_RETRY_HOURS=24
```

Tone/tenor defaults to disabled to avoid local Ollama CPU/power spikes. It can be enabled, made
dry-run, or scaled with:

```bash
RELATIONSHIP_SUBSTRATE_TONE_TENOR_ENABLED=1
RELATIONSHIP_SUBSTRATE_TONE_TENOR_APPLY=0
RELATIONSHIP_SUBSTRATE_TONE_TENOR_LIMIT=5
RELATIONSHIP_SUBSTRATE_TONE_EVIDENCE_LIMIT=8
RELATIONSHIP_SUBSTRATE_TONE_MODEL=hermes3:8b
```

Relationship strength defaults to disabled to avoid local Ollama CPU/power spikes. It can be
enabled, made dry-run, or scaled with:

```bash
RELATIONSHIP_SUBSTRATE_STRENGTH_ENABLED=1
RELATIONSHIP_SUBSTRATE_STRENGTH_APPLY=0
RELATIONSHIP_SUBSTRATE_STRENGTH_LIMIT=5
RELATIONSHIP_SUBSTRATE_STRENGTH_EVIDENCE_LIMIT=8
RELATIONSHIP_SUBSTRATE_STRENGTH_MODEL=hermes3:8b
```

Catch-up and steady refresh can be tuned with:

```bash
RELATIONSHIP_SUBSTRATE_CATCHUP_INTERVAL_SECONDS=60
RELATIONSHIP_SUBSTRATE_REFRESH_INTERVAL_SECONDS=43200
RELATIONSHIP_SUBSTRATE_STEADY_ORGANIZATION_NEWS_LIMIT=25
RELATIONSHIP_SUBSTRATE_PERPLEXITY_NEWS_MODEL=sonar-pro
```

Local embedding backfill can be enabled explicitly with:

```bash
RELATIONSHIP_SUBSTRATE_AUTONOMOUS_EMBEDDINGS_ENABLED=1
RELATIONSHIP_SUBSTRATE_EMBED_PROVIDER=ollama
RELATIONSHIP_SUBSTRATE_EMBED_LIMIT=25
```
