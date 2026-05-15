#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${RELATIONSHIP_SUBSTRATE_ROOT:-/Users/braydon/projects/experiments/relationship-substrate}"
cd "$ROOT_DIR"

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
REPORT_DIR="output/jobs/${RUN_ID}"
mkdir -p "$REPORT_DIR" output/ops output/autonomous

DEFAULT_NEXT_UP="/Users/braydon/projects/personal/home_next_up/resources/people.xlsx"
DEFAULT_CALENDAR_PATHS="output/ops/calendar-mcco-20180101-20260514.json:output/ops/calendar-intempio-20180101-20260514.json:output/ops/calendar-gmail-20240101-20260514.json"

NEXT_UP_PATHS="${RELATIONSHIP_SUBSTRATE_NEXT_UP_PATHS:-$DEFAULT_NEXT_UP}"
CALENDAR_PATHS="${RELATIONSHIP_SUBSTRATE_CALENDAR_PATHS:-$DEFAULT_CALENDAR_PATHS}"
SENDER_LIMIT="${RELATIONSHIP_SUBSTRATE_SENDER_LIMIT:-500}"
CORRESPONDENCE_FROM_SENDERS="${RELATIONSHIP_SUBSTRATE_CORRESPONDENCE_FROM_SENDERS:-25}"
CORRESPONDENCE_MESSAGE_LIMIT="${RELATIONSHIP_SUBSTRATE_CORRESPONDENCE_MESSAGE_LIMIT:-50}"
EMBED_LIMIT="${RELATIONSHIP_SUBSTRATE_EMBED_LIMIT:-50}"
MAX_EMBED_ITERATIONS="${RELATIONSHIP_SUBSTRATE_MAX_EMBED_ITERATIONS:-100}"
NORTH_STAR_LIMIT="${RELATIONSHIP_SUBSTRATE_NORTH_STAR_LIMIT:-25}"
ORGANIZATION_WORKLIST_LIMIT="${RELATIONSHIP_SUBSTRATE_ORGANIZATION_WORKLIST_LIMIT:-250}"

pipeline_cmd=(
  uv run relationship-substrate run-network-pipeline
  --output-dir output/ops
  --sender-limit "$SENDER_LIMIT"
  --correspondence-from-senders "$CORRESPONDENCE_FROM_SENDERS"
  --correspondence-message-limit "$CORRESPONDENCE_MESSAGE_LIMIT"
  --skip-embeddings
  --embed-limit "$EMBED_LIMIT"
  --organization-worklist-limit "$ORGANIZATION_WORKLIST_LIMIT"
  --north-star-limit "$NORTH_STAR_LIMIT"
)

IFS=':' read -r -a next_up_paths <<< "$NEXT_UP_PATHS"
for path in "${next_up_paths[@]}"; do
  if [[ -e "$path" ]]; then
    pipeline_cmd+=(--next-up-path "$path")
  fi
done

IFS=':' read -r -a calendar_paths <<< "$CALENDAR_PATHS"
for path in "${calendar_paths[@]}"; do
  if [[ -e "$path" ]]; then
    pipeline_cmd+=(--calendar-path "$path")
  fi
done

if [[ " ${pipeline_cmd[*]} " != *" --next-up-path "* ]]; then
  echo "No next_up seed path exists; set RELATIONSHIP_SUBSTRATE_NEXT_UP_PATHS" >&2
  exit 2
fi

"${pipeline_cmd[@]}" > "${REPORT_DIR}/pipeline_report_stdout.json"

uv run relationship-substrate run-autonomous-backfill \
  --output-dir output/autonomous \
  --max-iterations "$MAX_EMBED_ITERATIONS" \
  --sleep-seconds 15 \
  --embed-provider ollama \
  --embed-limit "$EMBED_LIMIT" \
  --organization-worklist-limit "$ORGANIZATION_WORKLIST_LIMIT" \
  --north-star-limit "$NORTH_STAR_LIMIT" \
  > "${REPORT_DIR}/autonomous_backfill_stdout.json"

uv run relationship-substrate substrate-status \
  --organization-worklist-limit "$ORGANIZATION_WORKLIST_LIMIT" \
  > "${REPORT_DIR}/substrate_status.json"

uv run relationship-substrate export-history-backed-organization-worklist \
  --missing-only \
  --limit "$ORGANIZATION_WORKLIST_LIMIT" \
  > "${REPORT_DIR}/organization_enrichment_worklist.json"

latest_packet="$(find output/autonomous -path '*/iteration-*/ask_network_packet.json' -type f -print | sort | tail -1 || true)"
if [[ -n "$latest_packet" ]]; then
  uv run relationship-substrate export-tone-state-worklist \
    --ask-packet "$latest_packet" \
    > "${REPORT_DIR}/north_star_tone_state_worklist.json"
fi

printf '%s\n' "$REPORT_DIR" > output/jobs/latest_cycle
