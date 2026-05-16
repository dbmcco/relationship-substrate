#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${RELATIONSHIP_SUBSTRATE_ROOT:-/Users/braydon/projects/experiments/relationship-substrate}"
CATCHUP_INTERVAL_SECONDS="${RELATIONSHIP_SUBSTRATE_CATCHUP_INTERVAL_SECONDS:-60}"
REFRESH_INTERVAL_SECONDS="${RELATIONSHIP_SUBSTRATE_REFRESH_INTERVAL_SECONDS:-43200}"
STEADY_ORGANIZATION_NEWS_LIMIT="${RELATIONSHIP_SUBSTRATE_STEADY_ORGANIZATION_NEWS_LIMIT:-25}"
LOG_DIR="${ROOT_DIR}/output/nightly"
mkdir -p "$LOG_DIR"

steady_refresh_ready=0

while true; do
  started_at="$(date -u +%Y%m%dT%H%M%SZ)"
  if [[ "$steady_refresh_ready" == "1" ]]; then
    export RELATIONSHIP_SUBSTRATE_ORGANIZATION_NEWS_LIMIT="$STEADY_ORGANIZATION_NEWS_LIMIT"
  else
    export RELATIONSHIP_SUBSTRATE_ORGANIZATION_NEWS_LIMIT=0
  fi

  "${ROOT_DIR}/ops/jobs/nightly-worklists.sh" \
    >> "${LOG_DIR}/catchup-refresh-${started_at}.log" \
    2>&1 || true

  report_dir="$(cat "${LOG_DIR}/latest")"
  organization_selected="$(jq -r '.worklist_count // 0' "${report_dir}/organization_research_stdout.json")"
  tone_selected="$(jq -r '.selected // 0' "${report_dir}/tone_tenor_stdout.json")"
  strength_selected="$(jq -r '.selected // 0' "${report_dir}/relationship_strength_stdout.json")"
  failed_count="$(
    jq -s 'map(.failed // 0) | add' \
      "${report_dir}/organization_research_stdout.json" \
      "${report_dir}/tone_tenor_stdout.json" \
      "${report_dir}/relationship_strength_stdout.json"
  )"

  if [[ "$organization_selected" == "0" && "$tone_selected" == "0" && "$strength_selected" == "0" && "$failed_count" == "0" ]]; then
    steady_refresh_ready=1
    sleep "$REFRESH_INTERVAL_SECONDS"
  else
    steady_refresh_ready=0
    sleep "$CATCHUP_INTERVAL_SECONDS"
  fi
done
