#!/usr/bin/env bash
set -euo pipefail

SUBSTRATE_ROOT="${RELATIONSHIP_SUBSTRATE_ROOT:-/Users/braydon/projects/experiments/relationship-substrate}"
STATE_SYSTEM_ROOT="${STATE_SYSTEM_ROOT:-/Users/braydon/projects/experiments/state-system}"
FLEET_MANIFEST="${STATE_SYSTEM_FLEET_MANIFEST:-/Users/braydon/projects/personal/b-state/fleet-refresh/instance-refresh.json}"
FLEET_OUTPUT_DIR="${STATE_SYSTEM_FLEET_OUTPUT_DIR:-/Users/braydon/projects/personal/b-state/fleet-refresh}"

cd "$SUBSTRATE_ROOT"

printf '%s substrate cycle started\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
"$SUBSTRATE_ROOT/ops/jobs/substrate-cycle.sh"
printf '%s substrate cycle completed\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"

printf '%s State System fleet refresh started\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
"$STATE_SYSTEM_ROOT/scripts/run-fleet-refresh.sh" "$FLEET_MANIFEST" "$FLEET_OUTPUT_DIR"
printf '%s State System fleet refresh completed\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
