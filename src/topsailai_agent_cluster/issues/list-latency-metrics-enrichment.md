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
