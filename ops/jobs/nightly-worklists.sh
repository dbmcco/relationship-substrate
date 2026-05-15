#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${RELATIONSHIP_SUBSTRATE_ROOT:-/Users/braydon/projects/experiments/relationship-substrate}"
cd "$ROOT_DIR"

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
REPORT_DIR="output/nightly/${RUN_ID}"
ORGANIZATION_WORKLIST_LIMIT="${RELATIONSHIP_SUBSTRATE_ORGANIZATION_WORKLIST_LIMIT:-250}"
mkdir -p "$REPORT_DIR"

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

printf '%s\n' "$REPORT_DIR" > output/nightly/latest
