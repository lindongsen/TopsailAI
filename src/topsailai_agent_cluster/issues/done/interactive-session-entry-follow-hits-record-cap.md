---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: topsailai_agent_cluster
programming_language: go
---

# Entering session scope ends the automatic tail with `provider_error`

## Trigger

Human report, verbatim:

```
cli的交互模式，从workspace scope 进入 session scope的时候，会报这个错误：log.follow> follow ended: provider_error
```

## Observed behaviour

Entering session scope arms a live tail (`internal/tui/navigation.go:102`,
`autoLogsOnSessionEntry`). The tail ends almost immediately with the terminal code
`provider_error`, rendered as `log.follow> follow ended: provider_error`
(`internal/tui/follow.go:117`). The recovery path then prints
`follow ended: provider_error; showing one snapshot instead`
(`internal/tui/navigation.go:175`), so the operator sees the error line first and a
snapshot second.

## Expected behaviour

Entering a session shows its trailing output and then keeps streaming. A session
with more history than the REPL line budget must not be reported as a provider
fault.

## Producer evidence

`/opt/agent-cluster/logs/endpoint/ac.ai-dev.log` (686 lines) contains 40 entries of:

```
"msg":"follow provider output","error":"provider stream: provider stream record limit exceeded: 128"
```

The complete distribution of `follow provider output` errors in that log is:

| Count | Error |
|---|---|
| 40 | `provider stream: provider stream record limit exceeded: 128` |
| 9 | `resource generation does not match` |
| 4 | `provider stream ended: context deadline exceeded` |
| 1 | `adapter ...` |

The record limit is therefore the dominant follow failure, and it is the only one
whose message matches the reported symptom.

## Root cause

The Endpoint caps a Provider CLI stream at 128 record frames, cumulatively, for the
whole life of the stream:

- `src/main/agent-cluster-endpoint/adapter_factory.go:28` declares
  `genericCLIMaxRecords = 128` and passes it as `Config.MaxRecords` at line 102.
- `internal/adapter/genericcli/adapter.go:576` copies it into every request
  `Budget.MaxRecords`.
- `internal/adapter/genericcli/runner.go:196-200` increments a counter over the
  whole stream and fails at the 129th record frame.

The REPL asks for 300 trailing lines, and the provider emits one record per line:

- `internal/tui/interactive.go:31` sets `DefaultInteractiveMaxLines = 300`.
- `providers/topsailai/follow.go:41-62` encodes one `record` frame per output line.
- `providers/topsailai/runtime_operations.py:173-175` emits the initial tail lines
  as records before the live poll begins.

So the initial tail alone can emit up to 300 records while the adapter allows 128.
The failure is deterministic for any session whose trailing output exceeds 128
lines, not a consequence of a busy session.

Real session logs on this host confirm the bound is exceeded routinely: the largest
files under `/root/.topsailai/workspace/task/` hold 134121, 48364, 38746, 34191,
23870, 22787, 22567, 17028, 12025, 10342 and 9432 lines.

## Why the error is misclassified

`internal/endpoint/follow.go:113-115` maps every error that is not cancellation,
`ErrUnsupported` or `ErrBusy` onto `provider_error`. A budget exhaustion is a
cluster-side limit, not a provider fault, so the operator is sent to investigate a
provider that behaved correctly.

## The advertised provider limit is never used

`providers/topsailai/descriptor.go:42` advertises `MaxRecords: 10_000`, but the
descriptor's `Limits` are only validated (`internal/providercli/validation.go:559`)
and never intersected into the request budget. The Endpoint's 128 always wins, so
the descriptor's own bound is dead data for this field.

## Second defect of the same class

`internal/adapter/genericcli/runner.go:181-185` applies the 1 MiB
`maxStdoutBytes` budget cumulatively to the whole stream as well. A long follow that
writes more than 1 MiB of frames fails with
`provider stdout byte limit exceeded`, which is the same misclassification applied
to a byte bound. `max_records` and `max_stdout_bytes` are documented as per-invocation
budgets, but on a streaming follow they behave as lifetime caps.

## Impact

- Entering session scope is unusable for any session with more than 128 lines of
  output, which is most real sessions.
- The operator is told the provider failed, so the investigation starts in the wrong
  component.
- The recovery snapshot hides the loss: the operator sees a bounded snapshot and may
  not realise the live tail never ran.

## Regression scope

- `internal/adapter/genericcli/stream_lifecycle_guard_test.go:66` pins the current
  record-limit message and must be updated with the chosen bound.
- `internal/providerconformance/runner.go:100-101` enforces the same limit for
  conformance and is a separate site.
- `internal/tui/follow_test.go:95` and `internal/tui/follow_recovery_test.go:81`
  assert the `provider_error` rendering and must keep passing for a genuine provider
  failure.

## Open decision

Whether a live follow may be unbounded in record count, bounded only by the byte
budget and the deadline, or must keep a cap that is reported as its own terminal
code with snapshot recovery. Both halves are likely required: the cap must not
truncate a healthy stream, and an exhausted cap must not be called a provider
failure.

## Resolution

Resolved in `b9abd540`. `scanStream` (`internal/adapter/genericcli/runner.go:174-205`) no
longer accumulates a record count, so a live follow is bounded by bytes and by its
deadline only. The comment at the site records why: a record count truncates a healthy
stream whose only fault is being long, and the REPL asks for 300 trailing lines while the
runner used to allow 128.

The second defect of the same class was fixed with it. The cumulative byte budget now
returns `adapter.ErrOutputLimit` instead of a bare error, so the Endpoint names a local
bound rather than blaming the provider.

`max_records` stays in the request as a provider-side budget, and
`internal/providerconformance/runner.go` keeps its own limit for conformance, which is a
separate site and was not changed.

Verified by `internal/adapter/genericcli/stream_lifecycle_guard_test.go`, which asserts a
stream carrying more records than `max_records` is accepted.
