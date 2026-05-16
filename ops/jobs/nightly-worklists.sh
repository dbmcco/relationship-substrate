#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${RELATIONSHIP_SUBSTRATE_ROOT:-/Users/braydon/projects/experiments/relationship-substrate}"
cd "$ROOT_DIR"

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
REPORT_DIR="output/nightly/${RUN_ID}"
ORGANIZATION_WORKLIST_LIMIT="${RELATIONSHIP_SUBSTRATE_ORGANIZATION_WORKLIST_LIMIT:-250}"
ORGANIZATION_RESEARCH_LIMIT="${RELATIONSHIP_SUBSTRATE_ORGANIZATION_RESEARCH_LIMIT:-25}"
ORGANIZATION_RESEARCH_APPLY="${RELATIONSHIP_SUBSTRATE_ORGANIZATION_RESEARCH_APPLY:-1}"
TONE_TENOR_LIMIT="${RELATIONSHIP_SUBSTRATE_TONE_TENOR_LIMIT:-5}"
TONE_TENOR_APPLY="${RELATIONSHIP_SUBSTRATE_TONE_TENOR_APPLY:-1}"
TONE_TENOR_MODEL="${RELATIONSHIP_SUBSTRATE_TONE_MODEL:-hermes3:8b}"
TONE_TENOR_EVIDENCE_LIMIT="${RELATIONSHIP_SUBSTRATE_TONE_EVIDENCE_LIMIT:-8}"
mkdir -p "$REPORT_DIR"

uv run relationship-substrate substrate-status \
  --organization-worklist-limit "$ORGANIZATION_WORKLIST_LIMIT" \
  > "${REPORT_DIR}/substrate_status.json"

uv run relationship-substrate export-history-backed-organization-worklist \
  --missing-only \
  --limit "$ORGANIZATION_WORKLIST_LIMIT" \
  > "${REPORT_DIR}/organization_enrichment_worklist.json"

organization_research_cmd=(
  uv run relationship-substrate run-organization-enrichment-research
  --output-dir output/research/organizations
  --limit "$ORGANIZATION_RESEARCH_LIMIT"
)
if [[ "$ORGANIZATION_RESEARCH_APPLY" == "1" || "$ORGANIZATION_RESEARCH_APPLY" == "true" ]]; then
  organization_research_cmd+=(--apply)
fi
"${organization_research_cmd[@]}" > "${REPORT_DIR}/organization_research_stdout.json"

tone_tenor_cmd=(
  uv run relationship-substrate run-relationship-tone-analysis
  --output-dir output/tone-tenor
  --limit "$TONE_TENOR_LIMIT"
  --evidence-limit "$TONE_TENOR_EVIDENCE_LIMIT"
  --model "$TONE_TENOR_MODEL"
)
if [[ "$TONE_TENOR_APPLY" == "1" || "$TONE_TENOR_APPLY" == "true" ]]; then
  tone_tenor_cmd+=(--apply)
fi
"${tone_tenor_cmd[@]}" > "${REPORT_DIR}/tone_tenor_stdout.json"

latest_packet="$(find output/autonomous -path '*/iteration-*/ask_network_packet.json' -type f -print | sort | tail -1 || true)"
if [[ -n "$latest_packet" ]]; then
  uv run relationship-substrate export-tone-state-worklist \
    --ask-packet "$latest_packet" \
    > "${REPORT_DIR}/north_star_tone_state_worklist.json"
fi

printf '%s\n' "$REPORT_DIR" > output/nightly/latest
