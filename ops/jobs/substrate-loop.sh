#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${RELATIONSHIP_SUBSTRATE_ROOT:-/Users/braydon/projects/experiments/relationship-substrate}"
INTERVAL_SECONDS="${RELATIONSHIP_SUBSTRATE_JOB_INTERVAL_SECONDS:-21600}"
LOG_DIR="${ROOT_DIR}/output/jobs"
mkdir -p "$LOG_DIR"

while true; do
  started_at="$(date -u +%Y%m%dT%H%M%SZ)"
  "${ROOT_DIR}/ops/jobs/substrate-cycle.sh" \
    >> "${LOG_DIR}/substrate-loop-${started_at}.log" \
    2>&1 || true
  sleep "$INTERVAL_SECONDS"
done
