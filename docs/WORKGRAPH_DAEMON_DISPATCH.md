# Workgraph Daemon Dispatch

The Codex daemon path is intended to run without Anthropic credentials:

```bash
wg service start --executor codex --model gpt-5.3-codex --max-agents 2 --force
```

The dispatcher override controls normal task agents, but Agency assignment and
evaluation scaffolds are separate inline system tasks. With `auto_assign`,
`auto_evaluate`, or `flip_enabled` enabled, those scaffolds can still use the
configured Agency models (`claude:haiku`) and inline `claude` executor wrappers.
On machines without an Anthropic key, that path logs lightweight Anthropic
failures and can preempt the Codex worker slots.

For Codex-only background enrichment, keep these local Workgraph settings off:

```toml
[agency]
auto_evaluate = false
auto_assign = false
flip_enabled = false
```

Also make the effective task-agent route Codex. In this repo the dispatcher
`--executor codex` CLI override was not enough by itself; the daemon still
resolved normal task spawns through the default/Agency executor path until the
local config was updated.

```bash
wg config --local --executor codex --no-reload
wg config --local --dispatcher-executor codex --model codex:gpt-5.3-codex --coordinator-model codex:gpt-5.3-codex --auto-evaluate false --auto-assign false --flip-enabled false --no-reload
wg config --local --set-model task_agent codex:gpt-5.3-codex --no-reload
wg config --local --set-model default codex:gpt-5.3-codex --no-reload
wg config --local --set-model evaluator codex:gpt-5.3-codex --no-reload
wg config --local --set-model assigner codex:gpt-5.3-codex --no-reload
```

`wg config --show` should then report:

```text
[agent]
  executor = "codex"
  model = "codex:gpt-5.3-codex"

[dispatcher]
  executor = "codex"
  model = "codex:gpt-5.3-codex"

[agency agents]
  task_agent = ...gpt-5.3-codex...
```

If already-created `.assign-*`, `.flip-*`, or `.evaluate-*` tasks remain in the
graph, they may still be ready and can be dispatched until they are completed,
failed, or the graph is cleaned up. The config above prevents creating more of
that Agency work during Codex daemon runs; it does not rewrite existing graph
tasks.

## Existing Assignment Blockers

Before starting a Codex daemon while manual workers are active, inspect the
current graph:

```bash
wg blocked repair-workgraph-daemon-dispatch
wg blocked research-outreach-proposals
wg ready
wg agents --alive
```

The failure reproduced with these blockers:

```text
Task 'repair-workgraph-daemon-dispatch' is blocked by:
  .assign-repair-workgraph-daemon-dispatch ... [Open]
Task 'research-outreach-proposals' is blocked by:
  .assign-research-outreach-proposals ... [Open]
```

`wg ready` was also dominated by `.flip-*`, `.assign-*`, and `.evaluate-*`
system tasks. Starting the daemon in that state lets the dispatcher spend its
two worker slots on existing Agency scaffolds instead of background enrichment.

Use one of these recovery paths before restarting the daemon:

1. If a human or tmux worker has already accepted the assignment, mark only the
   matching assignment blocker done:

   ```bash
   wg done .assign-repair-workgraph-daemon-dispatch
   wg done .assign-research-outreach-proposals
   ```

2. If the system task is stale or should not run on this machine, fail it with a
   concrete reason so the blocker is visible in history:

   ```bash
   wg fail .assign-repair-workgraph-daemon-dispatch --reason "Manual tmux worker owns this task; Codex daemon runs with Agency automation disabled"
   ```

   Use `wg done`, not `wg fail`, when the downstream task should become
   runnable after a manual assignment decision.

3. If `.flip-*`/`.evaluate-*` tasks dominate `wg ready`, do not start the daemon
   with `--max-agents 2` until those tasks are completed, failed, or explicitly
   accepted as the work to run. Config disables future scaffolds, not existing
   graph nodes.

After blockers are cleared, verify the Codex daemon path:

```bash
wg service start --executor codex --model gpt-5.3-codex --max-agents 2 --force
sleep 7
wg service status
tail -n 80 .workgraph/service/daemon.log
```

## Remaining Spawn-Stability Gap

On 2026-05-14, after clearing stale `.assign-*`, `.flip-*`, and `.evaluate-*`
tasks and updating local routing, the daemon resolved the enrichment task to
Codex:

```text
SpawnPlan executor=codex ... task=continue-organization-enrichment
```

The service still exited during or immediately after the spawn and left an
empty `.workgraph/agents/agent-15/` directory. Until that daemon-level spawn
stability issue is fixed, use a supervised tmux `codexd` worker in an isolated
git worktree for long-running enrichment, and keep Workgraph as the task state
ledger with `wg --dir /path/to/main/.workgraph ...`.
