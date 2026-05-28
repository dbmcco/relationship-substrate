#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${RELATIONSHIP_SUBSTRATE_ROOT:-/opt/relationship-substrate}"
CATCHUP_INTERVAL_SECONDS="${RELATIONSHIP_SUBSTRATE_CATCHUP_INTERVAL_SECONDS:-60}"
REFRESH_INTERVAL_SECONDS="${RELATIONSHIP_SUBSTRATE_REFRESH_INTERVAL_SECONDS:-43200}"
STEADY_ORGANIZATION_NEWS_LIMIT="${RELATIONSHIP_SUBSTRATE_STEADY_ORGANIZATION_NEWS_LIMIT:-25}"
TONE_TENOR_ENABLED="${RELATIONSHIP_SUBSTRATE_TONE_TENOR_ENABLED:-0}"
STRENGTH_ENABLED="${RELATIONSHIP_SUBSTRATE_STRENGTH_ENABLED:-0}"
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
  organization_remaining="$(jq -r '.actionable_queues.organization_enrichment.count // 0' "${report_dir}/substrate_status.json")"
  tone_remaining="$(jq -r '.actionable_queues.relationship_tone_tenor_state.count // 0' "${report_dir}/substrate_status.json")"
  strength_remaining="$(jq -r '.actionable_queues.relationship_strength_state.count // 0' "${report_dir}/substrate_status.json")"
  local_model_backlog_suspended=0
  if [[ "$TONE_TENOR_ENABLED" != "1" && "$TONE_TENOR_ENABLED" != "true" && "$tone_remaining" != "0" ]]; then
    local_model_backlog_suspended=1
  fi
  if [[ "$STRENGTH_ENABLED" != "1" && "$STRENGTH_ENABLED" != "true" && "$strength_remaining" != "0" ]]; then
    local_model_backlog_suspended=1
  fi
  failed_count="$(
    jq -s 'map(.failed // 0) | add' \
      "${report_dir}/organization_research_stdout.json" \
      "${report_dir}/tone_tenor_stdout.json" \
      "${report_dir}/relationship_strength_stdout.json"
  )"

  if [[ "$organization_remaining" == "0" && "$tone_remaining" == "0" && "$strength_remaining" == "0" && "$failed_count" == "0" ]]; then
    steady_refresh_ready=1
    sleep "$REFRESH_INTERVAL_SECONDS"
  elif [[ "$organization_remaining" == "0" && "$failed_count" == "0" && "$local_model_backlog_suspended" == "1" ]]; then
    steady_refresh_ready=0
    sleep "$REFRESH_INTERVAL_SECONDS"
  else
    steady_refresh_ready=0
    sleep "$CATCHUP_INTERVAL_SECONDS"
  fi
done
