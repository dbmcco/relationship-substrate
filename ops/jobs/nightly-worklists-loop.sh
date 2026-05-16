#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${RELATIONSHIP_SUBSTRATE_ROOT:-/Users/braydon/projects/experiments/relationship-substrate}"
INTERVAL_SECONDS="${RELATIONSHIP_SUBSTRATE_NIGHTLY_INTERVAL_SECONDS:-43200}"
LOG_DIR="${ROOT_DIR}/output/nightly"
mkdir -p "$LOG_DIR"

while true; do
  started_at="$(date -u +%Y%m%dT%H%M%SZ)"
  "${ROOT_DIR}/ops/jobs/nightly-worklists.sh" \
    >> "${LOG_DIR}/nightly-worklists-${started_at}.log" \
    2>&1 || true
  sleep "$INTERVAL_SECONDS"
done
