# State System Quality Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the State System source contracts and scheduling so all four instances report honest, current, evidence-backed state instead of merely regenerating metadata packages.

**Architecture:** Source adapters will emit canonical source-owned watermarks and honest freshness statuses. LFW relationship routes will be restored through its instance-owned route registry. The Relationship Substrate will run on its six-hour cadence, while the personal b-state package will refresh hourly so its one-hour freshness policy is meaningful.

**Tech Stack:** POSIX shell, macOS `date`, Python State System CLI, JSON route registries, PostgreSQL Relationship Substrate, macOS launchd, existing shell and unittest validation.

## Global Constraints

- `probe_only` timestamps must never be reported as `fresh`.
- MsgVault freshness must use the archived corpus watermark, not the scheduler checked-at time.
- Raw remote or personal corpora must not be copied into another instance; federation remains query-only.
- Package generation timestamps must not be treated as source-content freshness.
- Failed adapter runs must remain visible in reports and logs without triggering a retry storm.
- Quality validation must resolve declared evidence and route contracts; package size or reference counts alone are not proof of content quality.

---

### Task 1: Repair source adapters

**Files:**
- Modify: `/Users/braydon/projects/work/lfw/state-system/fleet-refresh/refresh-supporting-sources.sh`
- Modify: `/Users/braydon/projects/work/navicyte/navicyte-workspace/state-system/fleet-refresh/refresh-supporting-sources.sh`
- Modify: `/Users/braydon/projects/work/synth/state-system/fleet-refresh/refresh-supporting-sources.sh`
- Modify: `/Users/braydon/projects/personal/b-state/fleet-refresh/refresh-supporting-sources.sh`

**RED validation:**

```bash
bash /Users/braydon/projects/work/lfw/state-system/tests/validate-caroline-relationship-index.sh
# Expected: exit 1 because the current package has no governed LFW route.

grep -RniE 'illegal time format|fresh cannot be proven by probe_only' \
  /Users/braydon/Library/Logs/state-system-fleet-refresh \
  /Users/braydon/projects/work/{lfw/state-system,navicyte/navicyte-workspace/state-system,synth/state-system}/fleet-refresh/fleet-refresh-report.json
# Expected: the current RFC3339 and probe-only failures are present.
```

**Implementation:**

- Add the existing `iso_seconds` normalization function to the Navicyte adapter and use it in both LFW and Navicyte `msgvault_latest` functions for RFC3339 values such as `2026-07-17T15:26:09Z`.
- Leave the MsgVault watermark basis as `source_content`, retaining the latest archived `sent_at` value and message count.
- Change Synthyra’s local workspace record from `fresh` to `unknown` while retaining `watermark_basis=probe_only` and its explanatory status reason.
- Change the b-state relationship latest-watermark comparison from the invalid `\gt` test token to a valid POSIX string comparison, preserving the existing PostgreSQL corpus watermark logic.

**GREEN validation:**

```bash
sh -n /Users/braydon/projects/work/lfw/state-system/fleet-refresh/refresh-supporting-sources.sh
sh -n /Users/braydon/projects/work/navicyte/navicyte-workspace/state-system/fleet-refresh/refresh-supporting-sources.sh
sh -n /Users/braydon/projects/work/synth/state-system/fleet-refresh/refresh-supporting-sources.sh
sh -n /Users/braydon/projects/personal/b-state/fleet-refresh/refresh-supporting-sources.sh
```

Run each adapter with a fixed `STATE_SYSTEM_FLEET_CHECKED_AT` and assert no parser or probe-only exception, the expected status/basis pair, and a source-content MsgVault watermark. Then run the focused State System freshness tests.

---

### Task 2: Restore LFW governed routes

**Files:**
- Create: `/Users/braydon/projects/work/lfw/state-system/question-routes/lfw-relationship.json`
- Test: `/Users/braydon/projects/work/lfw/state-system/tests/validate-caroline-relationship-index.sh`

**Implementation:**

Create an instance-owned `question-routes` registry containing the two routes preserved in the older E2E package:

- `question_route.lfw.relationship_follow_up_triage`
- `question_route.lfw.federated_relationship_index`

The federated route must retain `source_instance_ref=state_instance.braydon_personal`, `source_ref=relationship_index:braydon_long_history`, `query_surface_ref=query_surface.federated.relationship_index.search`, `local_materialization=false`, the relationship-substrate tool action, source coverage, visible-gap behavior, and its governed answer contract. Do not add an LFW-specific branch to the generic package builder.

**RED validation:**

```bash
bash /Users/braydon/projects/work/lfw/state-system/tests/validate-caroline-relationship-index.sh
# Expected: current live package fails because routes/federation are absent.
```

**GREEN validation:**

```bash
python3 -m json.tool /Users/braydon/projects/work/lfw/state-system/question-routes/lfw-relationship.json >/dev/null
bash /Users/braydon/projects/work/lfw/state-system/tests/validate-caroline-relationship-index.sh
# Expected: PASS after rebuilding the LFW package.
```

---

### Task 3: Align launchd cadence

**Files:**
- Create: `/Users/braydon/Library/LaunchAgents/com.dbmcco.relationship-substrate.refresh.plist`
- Modify: `/Users/braydon/Library/LaunchAgents/com.dbmcco.state-system.b-state.fleet-refresh.plist`
- Modify: `/Users/braydon/projects/experiments/relationship-substrate/ops/jobs/README.md`

**Implementation:**

- Add a dedicated Relationship Substrate LaunchAgent that runs one bounded `substrate-cycle.sh` every six hours with the restored database and source paths.
- Change the b-state LaunchAgent to call the existing State System `run-fleet-refresh.sh` directly every hour. Keep its existing output directory and one-shot behavior; do not use `KeepAlive` for report-quality failures.
- Remove the dependency on the combined six-hour wrapper from the b-state LaunchAgent. The substrate corpus has a seven-day source-content policy, so the hourly b-state refresh can safely consume the latest available PostgreSQL watermark.
- Document the two launchd labels, intervals, logs, and the rule that the Herdr loop must remain stopped.

**Validation:**

```bash
plutil -lint /Users/braydon/Library/LaunchAgents/com.dbmcco.relationship-substrate.refresh.plist
plutil -lint /Users/braydon/Library/LaunchAgents/com.dbmcco.state-system.b-state.fleet-refresh.plist
launchctl bootout "gui/$(id -u)/com.dbmcco.relationship-substrate.refresh" 2>/dev/null || true
launchctl bootout "gui/$(id -u)/com.dbmcco.state-system.b-state.fleet-refresh" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" /Users/braydon/Library/LaunchAgents/com.dbmcco.relationship-substrate.refresh.plist
launchctl bootstrap "gui/$(id -u)" /Users/braydon/Library/LaunchAgents/com.dbmcco.state-system.b-state.fleet-refresh.plist
launchctl print "gui/$(id -u)/com.dbmcco.relationship-substrate.refresh"
launchctl print "gui/$(id -u)/com.dbmcco.state-system.b-state.fleet-refresh"
```

The substrate job must show a six-hour interval, the b-state job must show a one-hour interval, and no `substrate-loop.sh` process may remain.

---

### Task 4: Validate evidence quality

**Files:**
- Modify only if a focused validation requires it: `/Users/braydon/projects/experiments/state-system/tests/`
- Validate: all four live `fleet-refresh-report.json` files and instance package/read-model artifacts.

**Validation contract:**

For each package, verify that source readiness, evidence refs, freshness records, and routes are structurally present; every declared LFW route and federation pack must be present; all source-content watermarks must carry the correct basis; and all adapter failures must be represented in report/log output. Confirm that `requires_refresh_before_external_action` remains true whenever required source freshness is missing.

Run:

```bash
cd /Users/braydon/projects/experiments/state-system
python3 -m unittest discover -s tests
cd /Users/braydon/projects/work/lfw/state-system
bash tests/validate-caroline-relationship-index.sh
```

Add no numeric quality score. Content quality is established by resolving representative route/evidence contracts to source-owned records and explicitly retaining uncertainty.

---

### Task 5: Run and verify the fleet

Run the three corrected instance refreshes, the hourly b-state refresh, and one Relationship Substrate cycle. Verify:

- LFW, Navicyte, and Synthyra no longer fail for parser or probe-only reasons.
- LFW’s live package contains both governed routes and its federation pack.
- b-state’s source-freshness report is inside its one-hour window after the hourly run.
- Relationship Substrate remains fresh with PostgreSQL watermarks.
- Launchd reports no unexpected retry loop, and logs contain explicit success or failure markers.

Commit repository changes separately by repository, run the focused tests again, and push each changed git repository before completion.
