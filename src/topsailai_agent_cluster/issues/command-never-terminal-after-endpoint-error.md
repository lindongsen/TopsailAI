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

## Suggested resolution

Record a terminal receipt on every pre-execution failure instead of returning a bare error. The
existing `recordEarlyRejection` helper already does this for other early branches
(`internal/endpoint/executor.go:69`, `:81`), so the mapping-lookup and adapter-not-configured
branches should use the same path with an explicit error code such as `target_not_found` or
`adapter_not_configured`. Then `executeFrame` should not publish a receipt whose `CommandID` is
empty; treat that as an internal error and skip publication rather than sending a frame the Server
must reject.

## Prevention

- A test that submits a command for an unmapped resource ID and asserts the durable status becomes
  `rejected` with a bounded error code, and that the CLI returns without consuming the full wait
  budget.
- A guard in `executeFrame` that refuses to publish a receipt with an empty `CommandID`, so a future
  early-return path cannot silently produce an unpersistable frame.
