---
maintainer: AI
author: DawsonLin
---

# `send` latency is dominated by a redundant full provider discovery

## Trigger

Human report (verbatim):

> cli 的session scope 我发现send命令执行时间很长，原因是什么？

## Observed behavior

`agent-cluster-cli send <endpoint> <session> <message>` in the session scope takes 10-17 s against a
healthy local Endpoint, while the provider's own send call takes under 1 s. The delay is not the
message delivery itself.

## Measured breakdown (2026-11-07)

Live local cluster, Endpoint `ai-dev`.

| Stage | Elapsed |
|---|---|
| `topsailai workspace --format json` (host) | 11520 / 11290 / 13320 ms |
| `topsailai runtime send` (nonexistent session, no side effect) | 840 / 680 ms |
| `command_journal` delta, `message.send` | 10.1 - 17.4 s |
| `command_journal` delta, `agent.start` | 1.5 - 3.5 s |

`agent.start` carries no `Target`, so it skips the target revalidation entirely. Its 1.5-3.5 s delta
therefore isolates the discovery as the dominant term in the `message.send` cost.

## Root cause

`Executor.Execute` (`internal/endpoint/executor.go`) called `Adapter.Inspect` unconditionally for
every intent that carried a `Target`, before invoking the provider operation. The TopsailAI adapter
implements `Inspect` (`internal/adapter/topsailai/adapter.go`) by running a full `Discover`, i.e.
`topsailai workspace --format json`, and then scanning the returned sessions for the target.

That discovery is a complete provider history scan. It was executed purely to compare one generation
string that the Endpoint already holds in its own `source_cache` table. Every targeted `send`
therefore launched two provider CLI subprocesses where one is sufficient.

This is the same defect that `issues/logs-latency-redundant-discovery.md` fixed for `ReadOutput`.
`ReadOutput` was given a cache-first `revalidateGeneration` path, but `Execute` was never given the
same treatment. That asymmetry was the defect: the read path was optimized while the write path kept
paying the full discovery.

## Resolution (2026-11-07)

Implemented cache-first revalidation for command execution:

1. `adapterForIntent` now returns the resolved adapter ID alongside the adapter instance, so callers
   can read that adapter's own persisted snapshot without repeating the mapping lookup.
2. `Execute` branches on the operation. `agent.resume` keeps the live `Inspect`; every other targeted
   operation calls `revalidateGeneration`.
3. `revalidateGeneration` was generalized from `protocol.OutputSnapshotRequest` to
   `protocol.CommandTarget` so both the read and the command path share one implementation. The
   `ReadOutput` call site now passes a `CommandTarget`.

`agent.resume` deliberately keeps the live inspection because it authorizes on the **absence** of the
target, and an absence proof must come from the authoritative provider observation. A cached snapshot
can lag one collection cycle behind and would let a resume target a session that is already active
again. `target_observation_failed` and `target_still_active` are unchanged for that path.

Measured on the live local cluster after the change:

- cache hit (mismatched generation, provider never invoked): **0.11 / 0.22 / 0.32 s**, down from
  10-17 s
- forced cache miss (`stale=1`): **5.25 s**, still correctly rejected with
  `target_generation_mismatch`, so the fallback is preserved

## Prevention

Regression tests in `internal/endpoint/executor_test.go`:

- `TestExecuteSkipsDiscoveryWhenSnapshotAnswers` covers six cases and counts live inspections: 0 when
  the snapshot answers (match and mismatch), 1 when it cannot (stale, unknown data, resource absent,
  no row), and asserts the provider execution count in each case.
- `TestResumeStillInspectsLive` pins the deliberate exception, proving resume keeps its authoritative
  absence proof even when a fresh snapshot is present.

A negative control confirmed the test fails on the intended assertion (`live inspections=1, want 0`)
when the fix is reverted. The first revert attempt produced a build failure instead, which is not
valid evidence; the control was re-run with the unused variable neutralized so the failure landed on
the assertion.

## Related cross-project defect

`topsailai workspace --format json` spawns one `topsailai_session_info` subprocess per distinct
session (about 2.5 s each, 8 workers), which is why discovery takes 11-13 s. That belongs to the
provider project, not this repository, and is recorded here only as context for the measured cost.
