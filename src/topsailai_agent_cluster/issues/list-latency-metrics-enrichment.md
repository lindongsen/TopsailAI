---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
---

# `list` takes 5-10 s because message-count enrichment serializes behind one provider call per row

## Trigger

The operator reported that the `list` command is very slow. Measured on 2026-11-17 against the live
Server at `172.19.1.1:53680` with 13 inventory rows across three Endpoints.

## Measured behaviour

| Command | Elapsed (3 runs) |
|---|---|
| `list --json` | 0.05 / 0.03 / 0.04 s |
| `list --brief` | 9.13 / 10.07 / 10.04 s |
| `list` (full table) | 10.07 / 10.09 / 10.08 s |
| `list --endpoint ac.topsailai-dev` (1 row, no provider session id) | 0.03 s |
| `list --endpoint ac.topsail` (6 rows) | 5.02 s |
| `list --endpoint ac.ai-dev` (6 rows) | 5.03 s |

Per-call cost, measured directly:

| Measurement | Result |
|---|---|
| One `GET /api/v1/metrics` with a valid endpoint token | 1160 / 1040 / 1059 ms |
| Provider CLI `describe` (process startup only) | 5 / 6 / 9 ms |
| Provider business CLI `topsailai runtime control call_instruction ... agent.tokens` | 1290 / 1087 / 1256 ms |
| `topsailai --help` (interpreter startup only) | 508 / 396 / 396 ms |
| 2 concurrent metrics, same Endpoint | 2772 ms (serial would be ~2200) |
| 2 concurrent metrics, different Endpoints | 1716 ms (parallel would be ~1100) |
| 3 concurrent metrics, same Endpoint | 3337 ms (serial would be ~3300) |

## Root cause

The whole latency is the per-row live message-count enrichment. Inventory loading and rendering are
free: `list --json` returns in 0.04 s and takes the same code path up to the enrichment call.

Three compounding causes, each verified:

1. **One provider process pair per row, ~1.1 s each.** The Endpoint adapter starts
   `agent-cluster-provider-topsailai` (Go), which starts the `topsailai` business CLI (a bash wrapper
   around Python). The business call `runtime control call_instruction ... agent.tokens` costs
   1.09-1.29 s. Provider process startup alone is only 5-9 ms, so the cost is the business CLI, not
   the Go provider.

2. **The Endpoint channel loop handles every request frame inline.** `internal/endpoint/service.go:461`
   is `channelLoop`, and `internal/endpoint/service.go:540` calls `s.metricsFrame(ctx, frame)` directly
   with no goroutine, unlike `startFollow` at line 548 which does spawn one. `metricsFrame`
   (`internal/endpoint/metrics.go:85`) then runs the provider read synchronously at line 103. So the
   client's 8-way fan-out (`internal/tui/metrics.go:31`, `metricsWorkers = 8`) collapses to serial
   execution at the Endpoint. Confirmed by measurement: 3 concurrent same-Endpoint reads took 3337 ms
   instead of ~1100 ms.

3. **Enrichment is unconditional and the budget arithmetic guarantees truncation.**
   `internal/tui/metrics.go:48` returns a closure whenever the API implements `metricsReader`, and
   `internal/tui/commands.go:128-129` calls it before rendering. With `metricsRowBudget = 5 s`
   (`internal/tui/metrics.go:36`) and ~1.1 s per serialized call, only about four rows complete per
   wave. The observed timings are exactly the wave count times the budget:

   - 12 measurable rows / 8 workers = 2 waves x 5 s = 10 s (observed 10.07 s)
   - 6 measurable rows / 8 workers = 1 wave x 5 s = 5 s (observed 5.02 s)

   The remaining rows render `-`. In the observed full table, 5 of 12 measurable rows showed counts
   (`5/102`, `2/65`, `4/138`, `2/59`, `2/66`) and 7 showed `-`.

## Secondary defects

- **`--brief` pays for data it never prints.** `briefColumnKeys`
  (`internal/tui/table.go:146-150`) excludes `columnMessages`, so the measured counts are discarded,
  yet `--brief` still costs 9-10 s.
- **The Endpoint channel loop is single-threaded for all request frames.** `metricsFrame`,
  `messagesFrame`, `historyFrame`, `detailFrame`, `modelCatalogFrame`, `outputFrame` and `executeFrame`
  all run inline, so one slow provider read delays heartbeats, inventory publication and command
  dispatch on the same connection. This is broader than `list`.
- **`maxMetricsRows = 50`** (`internal/tui/metrics.go:27`) is far above what the 10 s command budget
  (`internal/tui/interactive.go:858-860`) can service serially, so the bound does not protect the
  command.
- **No caching.** The same session's counts are re-read on every `list`, even seconds apart.
- **The design comment is contradicted by behaviour.** `internal/tui/metrics.go:33-35` states "a slow
  provider must cost one cell, never the whole command". In practice it costs the whole command.

## Impact

`list` is the primary operator surface. A 10 s wait on every invocation, with roughly half the
MESSAGES column silently unmeasured, makes the column unreliable as well as slow. The same
serialization also delays heartbeats and command dispatch on the shared channel.

## Fix direction (not yet decided)

Options differ materially in scope and need a human decision:

- Minimal: skip enrichment when `options.Brief` is set or when the rendered layout has no
  `columnMessages`.
- Correctness: dispatch request frames off the Endpoint `channelLoop` under the existing scheduler, so
  one slow provider read cannot stall heartbeats, commands or other reads.
- Cost: reduce the ~1.1 s per row (avoid the bash/Python double startup), cache counts briefly, or read
  counts only for rows the operator explicitly asks about.

## Verification limitation

The measurements used the fleet operator token from the Endpoint policy file. The first attempt used no
endpoint token and was refused with `policy_denied` in 0.04 s, which is not a valid timing; those
numbers were discarded rather than reported.

## Resolution of the minimal direction

The minimal direction was implemented and committed as `8516e863`
(`perf: skip message count enrichment when the layout omits the column`).

The guard asks the rendered layout rather than the flag. `layoutPrintsColumn`
(`internal/tui/table.go`) walks `layoutColumns`, which is the single authority for
what a render prints, so a future layout that drops `MESSAGES` for a reason other
than `--brief` is covered without a second condition. The enrichment site is
`internal/tui/commands.go:135`, inside `renderListRows`, which is the only render
path and therefore covers the interactive REPL, the standalone CLI and `refresh`.

Four tests were added in `internal/tui/table_brief_enrichment_test.go`. The pair
that matters is `TestBriefRenderDoesNotReadMessageCounts` with
`TestFullRenderStillReadsMessageCounts`: the brief case alone would also pass if
enrichment had been removed unconditionally, so the full case is what proves the
condition rather than the removal. Both brief tests were confirmed to fail when
the guard was removed, reporting `read message counts for
[endpoint-1/provider-session-1]` and `staged measured counts &{Inbound:7
Outbound:3}`, then passed again after the guard was restored.

### What this direction does not fix

The other two root causes remain, and they are why the measured latency on this
host is still seconds rather than the 0.04 s the issue recorded:

- The Endpoint `channelLoop` still runs seven request frames inline
  (`internal/endpoint/service.go:574-590`), so concurrent reads serialize.
- The per-row provider read still costs about a second, and on this host it
  currently fails outright: the Endpoint log records `query adapter metrics` with
  `TopsailAI CLI failed: exit status 3` and `exit status 6` for every attempt.

### Verification limitation on this host

The live timing comparison could not reproduce the issue's absolute numbers,
because the environment itself had degraded: `list --json`, which never performs
enrichment, measured 18-38 s, and the raw provider metrics query failed on every
attempt. Absolute latency is therefore not evidence here.

What the live run does establish is the relative effect, measured by alternating
brief and full against the same Endpoint so load drift affects both:

```
pair1: brief=6114ms  full=23371ms  ratio=3.82
pair2: brief=12400ms full=17582ms  ratio=1.42
pair3: brief=13319ms full=17845ms  ratio=1.34
pair4: brief=16592ms full=23578ms  ratio=1.42
```

Brief is consistently faster, and the rendered output confirms the mechanism: the
brief table prints `NO | SESSION_NAME | ENDPOINT` with no `MESSAGES` header, while
the full table still prints the column. The deterministic proof is the unit test
pair, not the wall clock.

## Resolution of the cost direction: one batch read per Endpoint

The cost direction was implemented and committed as `27796790`
(`feat: add batch message count read across cluster layers`). It replaces the
per-row provider read with one set read per Endpoint, so the number of provider
processes no longer grows with the number of rendered rows.

The path is complete at every layer, verified by reading each one:

| Layer | Implementation |
|---|---|
| TUI capability | `metricsBatchReader` (`internal/tui/metrics_batch.go:18`) |
| TUI grouping | `groupTargetsByEndpoint` (`:85`) keeps one group per Endpoint and preserves row order |
| TUI dispatch | `readMetrics` (`:53`) fans out per Endpoint group through `metricsWorkers` |
| TUI preference | `resolveEndpointGroup` (`:102`) tries the set read first and falls back to per-row only for members the set read did not answer |
| TUI budget | `metricsBatchBudget = 10 * time.Second` (`:29`) |
| Client | `APIClient.GetMetricsBatch` (`internal/client/metrics.go:43`) posts `/api/v1/metrics/batch` |
| Server route | `mux.HandleFunc("/api/v1/metrics/batch", h.metricsBatch)` (`internal/server/http.go:115`) |
| Server handler | `MetricsBatchRequester.RequestMetricsBatch` (`internal/server/metrics_batch.go:68`), bounded by `protocol.MaxMetricsBatchSessions` (`:56`) |
| Endpoint frame | `FrameMetricsBatchRequest` (`internal/channel/frames.go:69`) handled by `metricsBatchFrame` (`internal/endpoint/metrics.go:191`), budget 8 s (`:30`) |
| Adapter | `Adapter.MetricsBatch` (`internal/adapter/genericcli/adapter.go:522`) issues one `session.metrics.batch` query on `classRead` |
| Provider | `metricsBatch` (`providers/topsailai/query.go:433`) runs **one** `workspace list --json --local --include-runtime` and reads every requested session from that single document; bound `maxMetricsBatchSessions = 200` (`:38`) |

The provider batch is one process invocation, not a loop of invocations.
`runtimeMessageCounts` (`providers/topsailai/query.go:480`) is shared by the single
and batch paths, so the two granularities cannot drift.

Ten tests cover the batch path in `internal/tui/metrics_batch_test.go`, and all
pass: one batch call per Endpoint, row-index mapping, fallback for unanswered
members, fallback when the batch fails, fallback when the batch reports an error
code, dropping members that carry an error code, deduplicating repeated sessions,
a batch-only client, and the two render cases.

### The improvement is not visible in the running fleet

The deployed binaries predate the batch commit, so every batch request fails and
the client falls back to the per-row path. This is why the live latency is still
seconds even though the code is correct.

| Evidence | Result |
|---|---|
| `POST /api/v1/metrics/batch` against the running Server | **404 page not found**, while `GET /api/v1/endpoints` returns 200 |
| `strings` on the Server container binary for `metrics/batch` | 0 matches |
| `strings` on the installed Endpoint binary for `metrics_batch_request` | 0 matches |
| Endpoint binary mtime | 2026-11-17 12:18 |
| Server container binary mtime | 2026-11-17 04:22 |
| Batch feature commit `27796790` | 2026-11-17 19:13 |
| Endpoint process start times | 13:04:34, 13:04:36, 16:23:37 |
| Server process start time | 18:46:43 |
| `metrics batch` lines in the Endpoint log | 0 |

Every running process started before the batch feature existed, and the installed
binaries do not contain the frame or route names. The Server binary file has also
been removed from the host path while the process still holds its inode, so a
rebuild is required rather than a restart alone.

Live measurement on the stale fleet, for the record:

```
list (full)  run1 2.70 s   run2 2.58 s   run3 2.68 s
list --brief            0.00 s
```

Six of seven rows carried real counts (`15/70`, `10/125`, `4/66`, `5/119`,
`11/125`, `2/108`); one row on the `topsailai` Endpoint showed `-`. These numbers
describe the fallback path, not the batch path, so they are not evidence about the
batch implementation.

### Deployment is deliberately deferred

Rebuilding and restarting was not performed. Three provider sessions were running
at the time (`wa-5421006dfe45`, `wa-e46ae362e1bb`, `wa-ac0881d97da4`), and two of
the three Endpoints run inside Docker containers (`ai-dev`, `topsailai-dev`).
Recreating a container that hosts its own Agents kills them, which is the incident
recorded in `issues/done/endpoint-container-restart-kills-agents-and-hides-records.md`.
The human chose to record the state rather than restart, so the deployment step
remains open and must be scheduled when no Agent is running.

### What remains open after both directions

- The Endpoint `channelLoop` still runs ten request frames inline
  (`internal/endpoint/service.go:571-590`); only `startFollow` (`:592`) spawns a
  goroutine. This is now a concurrency defect in its own right, not the cause of
  `list` latency, because the client no longer depends on per-row reads. The
  largest single blocker is `FrameInventoryRefresh` (`:571`), whose collector
  budget is 30 s (`src/main/agent-cluster-endpoint/main.go:194`), three times the
  metrics budget the issue originally focused on.
- The per-row fallback still costs about a second per row and is still reachable
  whenever the set read does not answer a member, so the fallback cost matters
  until the batch path is deployed.
- One row on the `topsailai` Endpoint renders `-`. The cause is not yet
  determined and must be re-checked after the binaries are refreshed, because the
  stale fleet cannot distinguish a provider-side absence from a genuine failure.

## Re-measured after the batch path was deployed: the fallback is the remaining cost

Measured on 2026-11-17 22:00-22:10 against the same live Server at `172.19.1.1:53680`. The fleet has
been redeployed since the previous section, so the batch path is now active and the earlier
"deployment is deliberately deferred" state no longer describes the running system.

### The batch path is live

| Evidence | Result |
|---|---|
| `POST /api/v1/metrics/batch` with no credentials | **401 unauthorized** (previously 404 page not found) |
| `strings` on `/opt/agent-cluster/bin/agent-cluster-endpoint` for `metrics_batch_request` | 1 match |
| Endpoint binary mtime | 2026-11-17T19:58, after batch commit `27796790` at 19:13 |
| `query adapter metrics batch` lines in the Endpoint log | 0, so the batch call itself is not failing |
| `POST /api/v1/metrics/batch` for `ac.topsail` (7 ids) | 5 of 7 members answered with real counts |

### The remaining latency is the per-row fallback, multiplied

One consistent measurement window, all commands against the same fleet:

| Command | Elapsed |
|---|---|
| `list --json` | 19 ms |
| `list --brief` | 18 ms |
| `list` (full table) | 7598 ms |
| `list --endpoint ac.topsail` (7 rows) | 5744-7958 ms |
| `list --endpoint ac.ai-dev` (3 rows) | 7598-8061 ms |
| `list --endpoint ac.topsailai-dev` (0 rows) | 18 ms |

The cost model fits both windows exactly. One `list` performs one batch scan plus one full scan per
member the batch did not answer, and those scans serialize at the Endpoint:

```text
elapsed = (1 batch + unanswered members) x scan cost
```

| Endpoint | Unanswered | Scan cost | Predicted | Measured |
|---|---|---|---|---|
| `ac.topsail` | 2 of 7 | 1.90 s | 5.70 s | 5.744 s |
| `ac.ai-dev` | 3 of 3 | 1.90 s | 7.60 s | 7.598 s |
| `ac.topsail` (earlier window) | 2 of 7 | 1.00 s | 3.00 s | 2.993 s |

The scan cost is host-load dependent and was measured at 0.89-0.96 s and 1.90-2.29 s in two different
windows, which is why the same command took 2.99 s and 5.74 s at different times. Absolute latency is
therefore not a stable number; the multiplier is.

### The fallback cannot succeed, so its cost is pure waste

This is the decisive finding, and it is a defect rather than a tuning problem.

The batch drops a member when `runtimeMessageCounts` returns an error
(`providers/topsailai/query.go:459-467`). The per-row fallback then calls the single-session read,
which runs the **same** command and the **same** predicate:

| Path | Provider command | Predicate |
|---|---|---|
| Batch (`providers/topsailai/query.go:449`) | `workspace list --json --local --include-runtime` | `runtimeMessageCounts` (`:480`) |
| Single (`providers/topsailai/query.go:403`) | `workspace list --json --local -s SESSION --include-runtime` | `runtimeMessageCounts` (`:480`) |

The `-s` filter does not reduce the cost, because the provider still scans the whole task directory:

```text
single(-s) 892 / 896 / 928 ms
full scan  915 / 956 / 964 ms
```

So the fallback pays a full scan to re-evaluate a condition that already failed on the same data. It
cannot produce a count, and the row still renders `-`. The Endpoint log confirms the outcome: every
fallback attempt logs `query adapter metrics` with
`provider provider_error: provider did not report runtime message counts`, repeatedly, and the
`ac.ai-dev` table shows `-` for all three rows.

The provider's own comment at `providers/topsailai/query.go:459-463` states the reason the member is
dropped: "The provider result carries no per-member error field, so the only honest way to report an
unmeasurable member is to leave it out; the single-session read is the surface that names the reason."
That reasoning is what creates the waste: leaving the member out is indistinguishable from not asking,
so the caller must re-ask, and re-asking cannot succeed.

### Why the members are unmeasurable

`runtimeMessageCounts` rejects a row whose `runtime.state` is not `ok`
(`providers/topsailai/query.go:487`). The provider document on this host reports
`runtime_state=rejected` for two of the seven `ac.topsail` rows, which is exactly the two members the
batch omitted. The `ac.ai-dev` rows are on a different host and are not in this host's local document
at all, so all three are omitted there.

### Corrected statement of the remaining causes

The previous section listed the inline `channelLoop` as "a concurrency defect in its own right, not the
cause of `list` latency". That is now wrong for the fallback path: because the fallback reads are
dispatched inline at `internal/endpoint/service.go:582-584`, the client's 8-way fan-out
(`internal/tui/metrics.go:31`) collapses to serial execution at the Endpoint. Measured peak concurrent
business scans during one `list` was 2, not 8. The inline dispatch is therefore a direct multiplier of
the fallback cost, not merely a separate defect.

### Fix direction for this remaining cost

- Stop falling back when the batch already ran the same scan. A member the batch omitted is
  unmeasurable, not unasked, so the caller should render `-` immediately instead of re-reading.
- Or add a per-member error code to the provider batch result, so "not measured" and "not asked" become
  distinguishable and the fallback is only used for the genuinely unasked case.
- Either way, the `MESSAGES` column should not cost a provider scan per unmeasurable row, and the
  Endpoint `channelLoop` should not run these reads inline.

No code was changed for this re-measurement.

## Review of the fix in `09d31dbf`

Reviewed commit `09d31dbf feat: report message counts in the inventory so list reads only persisted data`
(ancestor of `staging` HEAD `318b6213`). 30 files, +558 / -1624.

### What the change does, verified by reading the diff

- Discovery now runs `workspace list --json --local --include-runtime`
  (`providers/topsailai/read.go:130`), so counts ride in the periodic report.
- `rowMessageCounts(item)` (`providers/topsailai/query.go`) is shared by discovery and the on-demand
  read, so the two paths cannot disagree.
- `sessionAttributes.Messages` -> `protocol.Session.Messages` -> `SessionRow.Messages` -> cell.
- Absence stays absent and renders `-`; a measured zero renders `0/0` (`internal/tui/table.go:747`).
- All six `EnrichRows` call sites removed; `MetricsEnricher`, `CachedMetricsEnricher`, `MetricsCache`,
  `metrics.go`, `metrics_batch.go` and their tests deleted.
- Byte bound raised from 1 MiB to `maxMetricsBatchBytes` (4 MiB) because the document is now the same
  one the metrics read used.

This matches the human's standing rule recorded in `MEMORY.md`: `list` renders only the Server's
persisted inventory and never triggers a provider read.

### Verified clean

- `go build ./...` and `go vet ./...` pass in the project module and in `providers/topsailai`.
- No dangling references to the deleted symbols; only one historical comment in
  `src/main/agent-cluster-cli/refresh_test.go:225`.
- `--include-runtime` genuinely changes provider output: without it every row is `"runtime": null`,
  with it rows carry `runtime.state` and `runtime.data`.
- The provider CLI silently accepts an unknown flag, so a provider older than `--include-runtime`
  degrades to absent counts instead of failing the collection. The version-skew claim holds.
- Server channel decode is lenient (`json.Unmarshal`, `internal/channel/server.go:748`), so the new
  `messages` field is not rejected.
- `make test-unit-server` and `make test-unit-endpoint` pass.

### Measured cost of the trade

Discovery without the flag 0.60-0.64 s, with the flag 0.90-0.93 s: about +0.30 s (+48%) per
collection cycle. The cost moved from per-render to per-cycle, which is the correct trade under the
rule, but the number is not recorded in the docs.

### Blocking findings

1. **The inventory -> row link is untested.** Deleting `Messages: session.Messages`
   (`internal/tui/model.go:91`) leaves the whole `internal/tui` suite green (37 s run, `ok`). The
   existing tests build `SessionRow` literals directly (`table_messages_test.go:72`), so they prove
   the cell renders a value that was handed to it, never that `ListRows` carries it from inventory.
2. **The discovery -> report link is untested.** Replacing the attach with `_ = counts`
   (`providers/topsailai/read.go:251`) leaves the whole provider suite green (`ok`, 0.5 s), i.e. the
   feature can be silently disabled. The provider tests only changed the expected call string to
   include `--include-runtime`; none asserts that counts appear in the observation.
3. **`MEMORY.md` states a consequence that no test enforces.** It requires "a new `list` read surface
   must be proven to issue zero Endpoint requests by counting provider invocations". No such test
   exists.

### Non-blocking findings

- `GetMetrics` and `GetMetricsBatch` now have no production caller; only
  `tests/bdd/steps_endpoint_query_permission.go:232` uses `GetMetrics`. No CLI or TUI command exposes
  them, so the doc comment "an operator who explicitly asks for the counts right now" describes a
  surface that does not exist. Either add it or state the routes are retained for external callers.
- Live verification is impossible: `agent-cluster-endpoint` (22:59) and `agent-cluster-server`
  (23:26) predate the fix (23:42), and the endpoint binary contains no `include-runtime` string. No
  live latency claim can be made from this build.
- `make test-unit` fails in `internal/channel` (`TestFollowDeliversAFullTailToASlowConsumer`,
  `follow_end_termination_test.go:229`). Proven pre-existing: reproduced 1 failure in 5 runs in a
  detached worktree at `47e62683`, which predates the fix, with different tests failing there
  (`TestRunHeartbeatKeepsAcknowledgedServerHealthy`, `TestRequestFollowOverflowSendsCancelFrame`).
  The fix does not touch `internal/channel`.
- `make test-unit-cli` failed once in `internal/tui` at `send_auto_logs_test.go:206`
  (`TestUnitSendAutoFollowUsesTheTenLineBudget`, `maxLines=300 want=10`). Not reproducible: 30
  isolated runs pass in both trees, and 4 full-suite runs at HEAD pass. The change does not touch the
  send/follow path. Load-dependent, tracked by the existing `LEARN.md:1435` entry.
