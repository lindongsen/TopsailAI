---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: topsailai_agent_cluster
programming_language: go
---

# `history` fails intermittently with `502 provider_error` because a read competes with the collection cycle

## Trigger

Human report (verbatim):

```
workspace> history
1. ai-dev / ac.ai-dev / ac.ai-dev
2. gd-dev / ac.gd-dev / ac.gd-dev
3. topsail / ac.topsail / ac.topsail
4. topsailai-dev / ac.topsailai-dev / ac.topsailai-dev
Choose an endpoint number or enter an endpoint ID; empty/cancel cancels.

answer> 1 (ai-dev / ac.ai-dev / ac.ai-dev)
error: server request failed (502): provider_error: provider history read failed
```

The human added that it happens easily, so this is a frequent condition rather than a rare race.

## Observed behavior

`history` against a healthy Endpoint sometimes returns `502 provider_error` with the message
`provider history read failed`, and succeeds on an immediate retry. Nothing about the target changes
between the two attempts.

The Endpoint log is the direct evidence, because the Endpoint is the component that refuses the read.
`/opt/agent-cluster/logs/endpoint/ac.ai-dev.log` contains **10** `query adapter history` errors, and
**all 10** are `provider adapter capacity exhausted: discovery`. There is no other history error cause
in that log, so the 502 the operator sees has exactly one origin on this host:

```
$ grep -c '"msg":"query adapter history"' ac.ai-dev.log
10
$ grep '"msg":"query adapter history"' ac.ai-dev.log | grep -c "capacity exhausted"
10
$ grep '"msg":"query adapter history"' ac.ai-dev.log | grep -v "capacity exhausted" | wc -l
0
```

The ten refusals, with their timestamps and the message that names the refused operation:

| Time (+08) | Refused operation |
|---|---|
| 2026-11-16T08:33:44.780924893 | `query adapter history` |
| 2026-11-16T08:33:56.370814876 | `query adapter history` |
| 2026-11-16T08:34:13.771676899 | `query adapter projects` |
| 2026-11-16T09:06:56.62445438 | `query adapter history` |
| 2026-11-16T09:10:47.235632462 | `query adapter history` |
| 2026-11-16T09:10:47.485311121 | `query adapter history` |
| 2026-11-16T09:15:33.659070227 | `query adapter history` |
| 2026-11-16T09:15:33.809603121 | `query adapter history` |
| 2026-11-16T09:15:33.915857254 | `query adapter history` |
| 2026-11-16T09:15:34.06359022 | `query adapter history` |

One raw line, unmodified:

```json
{"time":"2026-11-16T09:06:56.62445438+08:00","level":"ERROR","source":{"function":"topsailai_agent_cluster/internal/endpoint.(*Service).logError","file":"topsailai_agent_cluster/internal/endpoint/service.go","line":593},"msg":"query adapter history","error":"provider adapter capacity exhausted: discovery"}
```

Two facts follow from the timestamps and are worth stating because they explain "easy to reproduce":

- The refusals cluster in bursts of two to five within a few hundred milliseconds
  (`09:15:33.659`, `.809`, `.915`, `09:15:34.063`, `.264`). A burst is one operator retrying, or one
  client issuing several reads, while a single collection cycle holds the only discovery slot.
- `query adapter projects` is refused by the same mechanism, so this is not a history-specific defect.
  Every read-only provider query shares the discovery class and therefore the same single slot.

The HTTP-level reproduction was **not** executed for this record: no Server was listening on this host
at investigation time (`ss -ltnp` showed no agent-cluster listener, and no CLI configuration existed),
so the 502 status and its message are taken from the human's report and from the Server source at
`internal/server/history.go:90`, not from an observed response. The Endpoint-side refusal is observed
directly in the log above.

## Root cause

Two independent layers, and both must be fixed for the operator to see a correct answer.

### Layer 1: the deployed Endpoint predates the capacity-wait fix

`history` is a read-only provider query, and `typedQuery` classifies it as a discovery invocation:

- `internal/adapter/genericcli/adapter.go:453` calls
  `a.call(ctx, classDiscovery, providercli.FunctionQuery, ...)`.
- The periodic inventory collection also uses that class:
  `internal/adapter/genericcli/adapter.go:133` calls
  `a.call(ctx, classDiscovery, providercli.FunctionDiscover, ...)`.

The effective discovery concurrency is **1**:

- The TopsailAI provider declares `Discovery: 1`
  (`providers/topsailai/descriptor.go:44-49`), confirmed by running the installed provider's
  `describe`, which reports `"concurrency":{"total":8,"discovery":1,"mutation":1,"follow":4}`.
- The Endpoint ceiling is `Discovery: 2`
  (`src/main/agent-cluster-endpoint/adapter_factory.go:45`).
- `effectiveConcurrency` takes the minimum, so one discovery invocation runs at a time.

The collection cycle runs every 5 s (`defaultCollectionDelay`,
`internal/endpoint/service.go:68`) and holds that single slot for the whole provider discovery. Measured
on this host with three runs each, one discovery costs 0.84/0.82/0.80 s
(`topsailai workspace list --json --local`, 2907 bytes) and one history query 0.72/0.79/0.81 s
(`topsailai project list_sessions --json`, 13088 bytes). Taking the medians, the collection occupies
roughly 0.82 / (5 + 0.82) ≈ 14% of wall time, which is why a manual `history` collides often enough to
look reproducible.

Commit `6e00bb89 fix: wait for adapter capacity inside the caller budget` added
`scheduler.acquireWithin`, which retries inside the caller's own deadline instead of failing on the
first refusal. It is an ancestor of `HEAD` and present in source
(`internal/adapter/genericcli/scheduler.go:88`, called at `adapter.go:315` and `adapter.go:524`).

The deployed binary does not contain it:

- `/opt/agent-cluster/bin/agent-cluster-endpoint`, mtime `2026-11-16 06:00:06`,
  `vcs.revision=7b57076a05103b3c1bd9e4c8f3a514a66d1fa9fb`, `vcs.time=2026-11-15T21:48:25Z`.
- `strings` on that binary reports **0** occurrences of `acquireWithin`, while
  `git show 7b57076a:./internal/adapter/genericcli/adapter.go` shows both call sites still using the
  non-blocking `acquire`.
- `7b57076a` is 10 commits behind `HEAD` (`git rev-list --count 7b57076a..HEAD`), and `6e00bb89` is
  one of those 10 (`git merge-base --is-ancestor 6e00bb89 HEAD` succeeds).

So the running Endpoint refuses the read on the first collision instead of waiting for the slot, which
is exactly the behaviour the fix removed.

### Layer 2: the read path has no capacity classification, so the operator is told the provider broke

A capacity refusal is a transient collision with another invocation of the same Adapter instance. It
says nothing about the target and nothing about the provider, and the same request succeeds unchanged
once the competing invocation finishes. Both layers of the cluster report it as a provider fault:

- `internal/endpoint/history.go:34` (`Executor.History`) and `internal/endpoint/history.go:66` (the
  service frame handler) both set `result.ErrorCode = protocol.HistoryProviderError` whenever the
  adapter returns any error and no code was already set, so a capacity refusal becomes `provider_error`
  at two independent sites. Fixing only one leaves the other flattening the same fact.
- `internal/server/history.go:90` is the `default` branch of `writeHistoryResultFailure`. It has cases
  for `history_unsupported`, `history_response_too_large`, `endpoint_unavailable` and `policy_denied`,
  but none for a capacity condition, so it returns `502 provider_error` with the fixed message
  `provider history read failed` and no detail.

The Server switch already documents this exact defect class once. The comment above
`writeHistoryResultFailure` (`internal/server/history.go:70-75`) records that a disconnected endpoint
"fell through to the provider default and told the operator to investigate a provider that was never
reached", which is why the `endpoint_unavailable` case exists. A capacity refusal is the same class of
mistake with a different cause, and it is still falling through the same default.

The operator therefore reads "the provider failed" and has no way to learn that the correct action is
to retry, or that the Endpoint was merely busy collecting inventory.

`internal/adapter/adapter.go:23` already defines `adapter.ErrBusy` for exactly this distinction, and
`internal/endpoint/executor.go:560` already uses it through `observationFailureCode` for the preflight
observation sites. The history read path was not updated, so the same fact is classified on one path and
flattened on another.

## Why the tests missed it

- `internal/adapter/genericcli/scheduler_test.go` covers `acquireWithin` waiting and giving up, but it
  tests the scheduler in isolation. It cannot detect that the deployed binary lacks the function.
- `internal/endpoint/history_test.go` uses a stub adapter that returns a fixed error, so it never
  produces a capacity refusal and never asserts how one is classified.
- `internal/server/history_test.go` covers the codes the switch already handles. A code the switch does
  not handle is by definition untested, and the `default` branch makes that omission invisible.
- No test asserts that a read-only query and the collection cycle can both complete. `adapter_test.go`
  is the only test file that mentions both `FunctionQuery` and `FunctionDiscover`, and it exercises them
  in separate sequential tests (`TestTypedQueriesMapProviderKeysWithoutPublishingThem` and
  `TestAdapterMapsDiscoveryAndRejectsUnknownAttributes`), never concurrently. A grep for
  `concurren|contention|simultaneous` across `internal/adapter/genericcli/*_test.go` returns nothing, so
  the contention itself is unverified at any layer.

## Fix

Layer 1 is a deployment gap, not a source defect: rebuild and redeploy the Endpoint from `HEAD` so the
binary contains `6e00bb89`.

Layer 2 is a source defect and is not yet fixed:

- Classify a capacity refusal on the history read path as `adapter_busy` rather than `provider_error`,
  using the existing `adapter.ErrBusy` sentinel so the mapping has one definition. Both flattening
  sites must change: `Executor.History` (`internal/endpoint/history.go:34`) and the service frame
  handler (`internal/endpoint/history.go:66`). A shared helper is preferable to two copies, because
  this issue exists precisely because one path was updated and the other was not.
- Add an `adapter_busy` case to `writeHistoryResultFailure` returning a retryable status with a message
  that names the condition, instead of falling through to the provider default.
- Keep `provider_error` for every other adapter error, because only a capacity condition is provably
  unrelated to the target.

## Verification

Executed for this record:

- `go test ./internal/adapter/genericcli/ -run 'Scheduler|Capacity' -count=1` → `ok`, so the
  `acquireWithin` fix exists in source and is exercised by tests.
- `grep -rn acquireWithin internal/adapter/genericcli/` → definition at `scheduler.go:92`, call sites at
  `adapter.go:315` and `adapter.go:524`, plus four test references.
- `go version -m /opt/agent-cluster/bin/agent-cluster-endpoint` → `vcs.revision=7b57076a...`,
  `vcs.time=2026-11-15T21:48:25Z`.
- `strings /opt/agent-cluster/bin/agent-cluster-endpoint | grep -c acquireWithin` → `0`, so the deployed
  binary does not contain the fix.
- `git merge-base --is-ancestor 6e00bb89 HEAD` → succeeds; `git rev-list --count 7b57076a..HEAD` → `10`.
- Endpoint log: 10 `query adapter history` errors, all 10 `capacity exhausted`, 0 with any other cause.
- Provider descriptor, obtained by running the installed provider binary's `describe` with a valid
  `deadline_at_ms` and `payload`:
  `"concurrency":{"total":8,"discovery":1,"mutation":1,"follow":4}`, and `history.messages` is
  advertised, so the refusal is capacity rather than an unsupported query.
- Provider cost, three runs each: discovery 0.84/0.82/0.80 s, history 0.72/0.79/0.81 s.

Not executed, and therefore not claimed:

- No HTTP-level reproduction. No Server was listening on this host during the investigation
  (`ss -ltnp` showed no agent-cluster listener) and no CLI configuration existed, so the `502` status
  and the `provider history read failed` message come from the human's report and from
  `internal/server/history.go:90`, not from an observed response.
- No post-redeploy acceptance run, because the redeploy has not happened yet.

## Resolution

All three layers were resolved in source and deployed before this record was closed. The record is
kept because the investigation evidence is still useful, not because any work remains.

1. Layer 1 (deployment gap): the deployed Endpoint is now
   `vcs.revision=b33157dcd2e4acc07214d93f78c32ae8b982b6fd`, built `2026-11-16 10:27:06 +0800` with
   `vcs.modified=true`. `strings` on that binary reports three occurrences of `acquireWithin`, so the
   wait-inside-the-caller-budget fix is present. The `7b57076a` binary this record described is gone.
2. Layer 2 (classification): `2a3057bc fix: classify adapter capacity as retryable on read paths`
   added `protocol.AdapterBusy` and the `adapter_busy` case in `writeHistoryResultFailure`
   (`internal/server/history.go:90-93`), which returns `503` with a retryable message instead of
   falling through to the `provider_error` default. `readFailureCode` now classifies both flattening
   sites through the single `adapter.ErrBusy` sentinel.
3. Layer 3 (design decision): `b33157dc fix: give operator reads their own adapter capacity class`
   answered the open question by giving reads their own class. `Inspect`, `Resolve`, `ReadOutput`,
   `Query` and `Describe` now use `classRead`, so a read never competes with the periodic collection
   for the discovery slot. `TestDiscoveryCycleCannotDelayAnOperatorRead`
   (`internal/adapter/genericcli/scheduler_background_test.go:20`) proves a read succeeds while a
   discovery slot is held.

The human decision behind layer 3 is recorded in
`.task/plan_20261116T094500_operator-reads-own-capacity-class.md` (status `done`): only an offline
Endpoint may affect an operation, so background collection must never share capacity with operator
work.

## Related

`issues/resume-rejected-as-target-observation-failure-when-adapter-busy.md` documents the same Layer 1
deployment gap and the same `ErrBusy` distinction on the `resume` path. This issue is the read-path
instance: the deployment gap is shared, but the read path additionally has no capacity classification at
all, so it reports a provider fault where `resume` at least reports a target observation failure.
