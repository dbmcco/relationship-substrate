# Relationship Substrate Jobs

These jobs keep the non-UI substrate fresh. They are repo-local scripts so agents can run,
inspect, and change them without relying on hidden machine scheduler state.

## Jobs

- `substrate-cycle.sh`: one operational cycle. Refreshes msgvault/calendar/next_up materialization,
  drains supported embedding queues, writes status, organization enrichment worklist, and the
  current North Star tone-state worklist.
- `substrate-loop.sh`: runs `substrate-cycle.sh` repeatedly. Default interval: 6 hours.
- `nightly-worklists.sh`: exports the current enrichment and tone worklists without mutating ingest.
  It also runs a bounded organization research pass. Default: 5 organizations, apply enabled.
- `nightly-worklists-loop.sh`: runs `nightly-worklists.sh` repeatedly. Default interval: 24 hours.

## Inputs

Defaults:

- next_up seed: `/Users/braydon/projects/personal/home_next_up/resources/people.xlsx`
- calendar exports:
  - `output/ops/calendar-mcco-20180101-20260514.json`
  - `output/ops/calendar-intempio-20180101-20260514.json`
  - `output/ops/calendar-gmail-20240101-20260514.json`

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
