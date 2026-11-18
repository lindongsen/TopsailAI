---
maintainer: AI
author: DawsonLin
status: open
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

## Required decision

Two independent questions, and they should be decided separately.

1. **Should a zero `ExecuteBeforeAtMS` be rejected at admission?** A command with no deadline can
   never expire, so it is admitted and dispatched with no time bound. Rejecting it with
   `invalid_target`-style validation would make the field mandatory. Alternatively, treat zero as
   "no deadline" explicitly and document it, which is what the current code effectively does.
2. **Should `:249` report `not_applied` instead of `unknown`?** This is a one-line change to build
   the receipt with `EffectNotApplied` and `Outcome: "expired"`, matching the reachable path. It is
   correct regardless of how question 1 is decided, because at that point the adapter has provably
   not been called.

## Prevention

The two guards read one field and disagree about what a zero value means. A table-driven test over
`ExecuteBeforeAtMS` values `{0, past, future}` asserting both the `error_code` and the
`effect_certainty` for each would have made the disagreement visible, because the zero and past
cases produce the same observable behaviour (adapter not called) but different labels. Asserting
only the error code is not enough: both cases return a receipt with no error, so the label is the
only difference.

## Related

- `issues/endpoint-command-journal-unbounded-growth.md` — this defect was found while analysing
  retention, and an earlier version of that issue wrongly claimed a zero value would execute the
  command. The probe that disproved it is recorded there.
- `internal/endpoint/executor.go:586-588` — `unknownReceipt`, the constructor that hardcodes
  `EffectUnknown`.
