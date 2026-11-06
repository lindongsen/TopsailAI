---
maintainer: AI
author: DawsonLin
---

# A command rejected before receipt recording never becomes terminal

## Trigger

Observed while measuring `send` latency on the live local cluster (2026-11-07). A `send` to a
nonexistent session returned `dispatched` after a full 10 s, although the Endpoint had rejected it
immediately at the resource-mapping lookup with no provider call at all.

## Observed behavior

`agent-cluster-cli send <endpoint> does-not-exist-xyz <message>` took **10.04 / 10.02 / 10.03 s** and
printed `dispatched`. The Endpoint log recorded the failure at the mapping stage:

```text
resource mapping for "does-not-exist-xyz" not found
```

No provider subprocess was launched, so the real work took milliseconds. The 10 s is the CLI's
`defaultWaitTimeout` (`internal/tui/actions.go:16`), not provider latency.

The command also stayed `dispatched` in the Server database and `accepted` in the Endpoint journal,
never converging to a terminal state.

## Root cause

`Executor.Execute` (`internal/endpoint/executor.go:71-74`) returns a bare error when
`adapterForIntent` fails, **before** any receipt is recorded:

```go
instance, adapterID, err := e.adapterForIntent(ctx, intent)
if err != nil {
    return protocol.ExecutionReceipt{}, err
}
```

`executeFrame` (`internal/endpoint/service.go:345-367`) logs that error but then continues with the
zero-value receipt and publishes it anyway:

```go
receipt, err := s.executor.Execute(ctx, *frame.Intent, hash)
if err != nil {
    s.logError("execute command", err)
}
...
s.pendingReceipts[receipt.CommandID] = receipt   // CommandID is ""
s.channel.SendFrame(ctx, channel.Frame{... Receipt: &receipt ...})
```

The Server then rejects the frame in `ApplyReceipt`
(`internal/storage/server/command_queries.go:96-99`) because the empty ID matches no stored intent:

```text
command "" does not match a stored intent
```

So the rejection is never persisted. `WaitForTerminal` (`internal/tui/wait.go:18-41`) does treat
`rejected` as terminal, but the stored status never becomes `rejected`, so the loop polls until the
10 s context deadline and returns the last non-terminal state. The operator sees `dispatched` for a
command that was refused before execution.

## Impact

- Every command that fails before receipt recording costs the operator the full wait budget while
  reporting a non-terminal status.
- The durable record is wrong: a command that provably never reached the provider is left looking
  in-flight, so an operator cannot distinguish "still running" from "refused at admission".
- This is a correctness defect, not only a latency defect. It is independent of the discovery cost
  fixed in `issues/send-latency-redundant-discovery.md`.

## Resolution

Implemented on 2026-11-07. A pre-execution failure is now classified as either a **decision about
the target** (recorded as a durable terminal rejection) or an **infrastructure failure** (still a
bare error, because it says nothing about the target's validity):

- `internal/storage/endpoint/mapping.go` exports `ErrResourceNotFound`; `LookupResourceID` wraps it,
  so a missing mapping is distinguishable from a database failure.
- `internal/endpoint/executor.go` adds a `resolutionError` type carrying a bounded standard error
  code. `adapterForIntent` returns `target_not_found`, `adapter_not_configured` or `target_required`
  for the three resolution decisions, and a plain wrapped error for a genuine storage failure.
- `Executor.Execute` converts a coded resolution failure into `rejectedReceipt` plus
  `recordEarlyRejection`, and does the same for a `Describe` failure (`capability_unavailable`).
  Nothing was invoked in either case, so `EffectCertainty` is `not_applied` and the Server maps the
  receipt to `StatusRejected`, which `IsTerminalState` already treats as terminal.
- `internal/endpoint/service.go` `executeFrame` refuses to publish a receipt whose `CommandID` is
  empty, so a future early-return path cannot emit a frame the Server must reject.

Verified end to end on the live local cluster: `send` to an unmapped resource now returns
`status: rejected`, `error_code: target_not_found`, `effect_certainty: not_applied` in
**0.11 / 0.32 / 0.21 s** (previously 10.04 / 10.02 / 10.03 s), and the Server log no longer records
`command "" does not match a stored intent`.

## Prevention

- `TestExecuteRecordsTerminalRejectionForUnmappedResource` and
  `TestExecuteRecordsTerminalRejectionForUnconfiguredAdapter` assert the durable journal entry is
  `receipt_recorded` with the expected bounded error code, `not_applied` effect certainty and a
  `rejected` outcome.
- `TestServiceDoesNotPublishReceiptWithoutCommandID` asserts the transport carries zero receipt
  frames when the executor returns an unusable receipt.
- `TestExecutorRejectsMissingTargetBeforeProvider` was updated to the new contract: a missing target
  returns a nil error plus a terminal rejection, not an error.
- Each fix was reverted once to confirm the corresponding test fails on its intended assertion
  rather than on an unrelated error. The first attempt at the `executeFrame` negative control passed
  while the guard was removed, because the fixture intent omitted `CapabilityRevision` and
  `CanonicalHash` returned before the guard; adding the field made the control fail as intended
  (3 frames published, want 0).
