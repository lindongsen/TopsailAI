---
maintainer: AI
author: DawsonLin
status: done
created: 2026-11-18
---

# A zero execution deadline reports unknown certainty for a command that never ran

## Symptom

An intent whose `ExecuteBeforeAtMS` is zero is rejected before the adapter is called, but the
receipt reports `effect_certainty=unknown` instead of `not_applied`. The operator is told the effect
is uncertain when the code has proven the command was never applied.

## Evidence

Two guards read the same field with different consequences.

`internal/endpoint/executor.go:119`:

```go
if intent.ExecuteBeforeAtMS > 0 && e.now().UnixMilli() > intent.ExecuteBeforeAtMS {
```

A zero value makes this condition false, so the pre-admission expiry check is skipped.

`internal/endpoint/executor.go:249`:

```go
deadlineBudget := intent.ExecuteBeforeAtMS - e.now().UnixMilli()
if deadlineBudget <= 0 {
    return unknownReceipt(intent, requestHash, "expired_after_validation"), nil
}
```

With a zero value, `deadlineBudget` is `0 - now`, which is negative, so this branch returns
`unknownReceipt`. `unknownReceipt` (`executor.go:586-588`) hardcodes
`EffectCertainty: protocol.EffectUnknown` and `Outcome: "unknown"`.

Measured by probe against the real executor with a fixture adapter:

```text
zero deadline:
  err=<nil> phase=receipt_recorded outcome=unknown
  error_code=expired_after_validation effect=unknown
  adapter was NOT called

positive deadline already in the past:
  err=<nil> phase=receipt_recorded outcome=expired
  error_code=expired_before_execution effect=not_applied
  adapter was NOT called
```

Both cases provably never reached the adapter, and only one of them says so.

## Why the zero value is reachable

Nothing rejects it. `internal/server/commands.go:249` guards with
`if fresh && intent.ExecuteBeforeAtMS > 0 && intent.ExecuteBeforeAtMS <= time.Now().UnixMilli()`,
so a zero value also skips the Server's expiry handling and the command is dispatched normally.
`internal/protocol/command.go:28` declares the field as a plain `int64` with no validation, and
`HashVersion`/`Hash` (`command.go:277-279`) include it without checking it.

A client that omits `execute_before_at_ms` from its JSON therefore produces a zero value, and
`internal/tui/command_actions.go:82` is the only producer that always sets it. Any other client,
including a hand-written request or a future adapter, can omit it.

## Impact

The command is not executed, so there is no safety consequence. The defect is the reported
certainty: `unknown` means "the effect may or may not have happened", which forces an operator to
investigate a command that provably did nothing. It also contradicts the reachable path, where the
same outcome is reported as `not_applied`, so two commands that both never ran are described
differently depending on which guard caught them.

`unknown` is also the value that forbids automatic retry, so a command that is safe to retry is
labelled as unsafe to retry.

## Root cause

`unknownReceipt` is the correct constructor for "we do not know what happened". It was reused for a
case where the code does know: the adapter was never invoked. The post-admission budget check
returns the unknown constructor because it was written for the case where admission already
happened and the provider might have been reached, but at `:249` the adapter call is still ahead of
it, so nothing has been applied.

## Resolution

Fixed by option A: the post-validation expiry now reports a certain, unapplied effect and records
the receipt durably, without changing which commands execute.

### What changed

`internal/endpoint/executor.go` — the post-validation budget check now builds the receipt with
`EffectCertainty = protocol.EffectNotApplied` and `Outcome = "expired"`, and returns it through
`recordEarlyRejection` instead of returning it directly.

The durable write is not cosmetic. A probe against the real executor showed that the old code
returned the receipt without recording it, so the journal stayed at `endpoint_admitted`:

```text
before the fix, zero deadline:
  returned: outcome=unknown code=expired_after_validation effect=unknown
  journal_phase=endpoint_admitted
  replay:   outcome=unknown code=invocation_recovery_unknown effect=unknown

after the fix, zero deadline:
  returned: outcome=expired code=expired_after_validation effect=not_applied
  journal_phase=receipt_recorded
  replay:   outcome=expired code=expired_after_validation effect=not_applied
```

A label-only change would therefore have been incomplete: the replay path would still have reported
`invocation_recovery_unknown`, which claims the adapter might have run.

### A worse consequence the issue did not record

The `unknown` receipt leaves the Server command `executing`, and `executing` is not terminal. A probe
against the real storage layer measured it:

```text
zero+unknown      after_receipt="executing" after_sweep="executing" swept=0
zero+not_applied  after_receipt="rejected"  after_sweep="rejected"  swept=0
past+not_applied  after_receipt="rejected"  after_sweep="rejected"  swept=0
```

`ReconcileExpiredCommands` (`internal/storage/server/commands.go:121`) carries
`AND deadline_at_ms > 0`, so a zero-deadline row is never swept, and `PurgeExpiredCommands` only
deletes terminal rows, so it is never purged either. The Endpoint had already given its final answer,
so no second receipt could rescue it. The command was stuck permanently.

Option A fixes this as a side effect: `not_applied` maps to `rejected`
(`internal/storage/server/command_queries.go:151-153`), which is terminal.

### Decision on the two questions

1. **Zero stays legal and means "no deadline".** Four readers already agree on that
   (`internal/server/commands.go:249`, `internal/storage/server/commands.go:121`, the generic CLI
   adapter's `boundedContext`, and `internal/endpoint/executor.go:119`). Only the post-validation
   check disagreed, so the outlier was corrected rather than the majority. Rejecting zero at
   admission was rejected as an option because it would contradict the Server's own design and break
   any client that omits the field.
2. **`:249` reports `not_applied`.** Implemented as described above.

### Verification

New `internal/endpoint/executor_deadline_certainty_test.go`, four tests:

- `TestExpiredDeadlineReportsCertainNotAppliedEffect` — table-driven over `{zero, past}`, asserting
  the provider was reached zero times, the error code, `not_applied`, `outcome=expired`, and the
  durable journal state.
- `assertDurableExpiry` — requires `phase=receipt_recorded` and the stored receipt to carry the same
  code and certainty.
- `TestReplayedExpiredDeadlineKeepsTheCertainOutcome` — proves a replay does not fall back to
  `invocation_recovery_unknown`.
- `TestLiveDeadlineStillReachesTheProvider` — positive control, so deleting the deadline check
  entirely cannot pass.

Three deliberate breakages, each restored afterwards:

| Breakage | Failure |
|---|---|
| Revert to `return unknownReceipt(...)` | `effect certainty="unknown", want "not_applied": the provider was never called, so the effect is certain` and `replay error code="invocation_recovery_unknown", want "expired_after_validation"` |
| Keep the label but return the receipt directly | `journal phase="endpoint_admitted", want "receipt_recorded": a returned-only receipt leaves the command replayable as unknown` |
| Delete the `deadlineBudget <= 0` check | `the provider was reached 1 times, so the reported certainty cannot be trusted` |

Package results: `internal/endpoint` 7.775s, `internal/storage/server` 109.188s, `internal/protocol`
0.002s, `internal/server` 1.790s, `src/main/agent-cluster-endpoint` 0.259s — all green. `go build
./...`, `go vet` and `gofmt` clean.

### Documentation

`docs/API.md` and `docs/agent-cluster-protocol.md` now state the zero-value meaning, both expiry
codes, and that both carry `not_applied`. Neither code appeared anywhere in `docs/` before.

New `src/main/agent-cluster-endpoint/deadline_contract_guard_test.go`, three tests, because the
regression is prose that no code path can observe. Three deliberate breakages confirmed it is not
vacuous: removing "no deadline" from `docs/API.md`, renaming `expired_after_validation` in the
protocol document, and changing `not_applied` to `unknown` each failed with a message naming the
missing statement.

### Live data

The defect is latent, not active. Copied `/opt/agent-cluster/data/server/server.sqlite` to
`/tmp/live_server_probe.sqlite` (a direct query returns `database is locked`): 431 commands, **0**
with a zero deadline; `expired_after_validation` and `expired_before_execution` appear **0** times in
`/opt/agent-cluster/logs/`. The TUI is the only producer and always sets five minutes, so only a
hand-written request or a future client can reach this path.

## Related

- `issues/endpoint-command-journal-unbounded-growth.md` — this defect was found while analysing
  retention, and an earlier version of that issue wrongly claimed a zero value would execute the
  command. The probe that disproved it is recorded there.
- `internal/endpoint/executor.go:586-588` — `unknownReceipt`, the constructor that hardcodes
  `EffectUnknown`.
