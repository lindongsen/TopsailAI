---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: topsailai_agent_cluster
programming_language: go
---

# StatusLabel hardcodes "stop" for a generic delivery boundary

## Trigger

Discovered while implementing CLI action progress hints. The new progress rows reuse
`StatusLabel`, which prompted a review of how the label maps durable evidence to wording.

## Severity: latent, not currently reachable

An earlier analysis claimed that `message.send`, `execution.interrupt` and the `ctl.<action>`
family could display `stop request sent`. **That claim was wrong and is corrected here.**

The real TopsailAI provider emits `signal_sent` from exactly one command:

| Provider command | `delivery_state` | Source |
|---|---|---|
| `runtime send` | `pipe_written` | `cli/cli_topsailai/runtime_operations.py:233` |
| `runtime control <action>` | `control_acknowledged` | `cli/cli_topsailai/runtime_operations.py:238` |
| `runtime btw` | `injection_queued` | `cli/cli_topsailai/runtime_operations.py:245` |
| `workspace kill` | `signal_sent` | `cli/cli_topsailai/workspace_kill_cli.py:226` |
| `workspace driver start/stop` | `launched` / `stopped` / `status_read` | `cli/cli_topsailai/workspace_driver_cli.py:109,119,132` |

`workspace kill` is the `agent.stop` operation. Therefore, with the current single adapter, the
label `stop request sent` is **correct** for every receipt that reaches it.

## The actual defect

`internal/tui/model.go:107-109` returns the stop wording before the status switch and before any
operation is considered:

```go
if receipt.DeliveryBoundary == protocol.DeliverySignalSent && !receipt.ExitConfirmed {
    return "stop request sent"
}
```

`signal_sent` is a generic delivery boundary (`internal/protocol/command.go:82`), not a
stop-specific state. The label hardcodes an operation name onto a boundary that carries no
operation. It is correct today only because one provider happens to use that boundary for one
operation.

Assignment sites, all operation-agnostic:

| Site | Meaning |
|---|---|
| `internal/protocol/command.go:82` | Enum definition, generic |
| `internal/adapter/command.go:164-165` | Shared adapter helper: any provider response with `signal_sent` and no confirmed exit |
| `internal/adapter/topsailai/adapter.go:633-634` | Provider `delivery_state` mapping, operation-agnostic |
| `internal/adapter/topsailai/adapter.go:666-667` | `default` branch for an unrecognized `delivery_state` with `signal_sent: true` |

The genuinely stop-specific path, `internal/adapter/topsailai/adapter.go:642-648`
(`stopped`, `already_stopped`), sets `ExitConfirmed = true` at line 648 and never triggers the
guard.

## When it becomes reachable

1. **A second adapter.** The architecture explicitly plans multiple adapters per Endpoint
   (`docs/agent-cluster-architecture.md`, machine-scoped Endpoint with multiple provider bindings).
   Any adapter that reports `signal_sent` for a non-stop operation will display `stop request sent`.
   The shared helper at `internal/adapter/command.go:164-165` makes this the default mapping for
   every adapter, not an opt-in.
2. **A provider change.** If TopsailAI later reports `signal_sent` for `hard_interrupt` or any
   control action, the label lies immediately, with no code change on the cluster side.
3. **The `default` branch.** An unrecognized `delivery_state` combined with `signal_sent: true`
   maps to the same boundary, so an unexpected provider response also lands on the stop wording.

## Why it cannot be fixed locally

`protocol.ExecutionReceipt` (`internal/protocol/command.go:124-141`) has no `Operation` field. Its
fields are `CommandID`, `RequestHash`, `CommandRevision`, `EndpointInstanceID`, `Phase`,
`DeliveryBoundary`, `EffectCertainty`, `Outcome`, `ErrorCode`, `ErrorMessage`, `StartedAtMS`,
`FinishedAtMS`, `ProviderRequestRef`, `ProviderResponse`, `ProviderResponseTruncated` and
`ExitConfirmed`. `StatusLabel` therefore cannot distinguish a stop from any other operation.

A fix requires either adding `Operation` to the receipt (protocol and stored `receipt_json` change,
with a compatibility decision for existing rows) or passing the operation as a parameter (signature
change across every call site, with the correctness burden moved to callers).

## Blast radius

`StatusLabel` is called from:

- `internal/tui/command_actions.go:113` — final receipt of a mutating command
- `internal/tui/commands.go:173` — final receipt of a command submission
- `internal/tui/wait.go:65` — the progress stage rows added by the progress-hint change

The first two predate the progress-hint work. The third inherits the same mapping.

## Do not conflate with the correct use of the same condition

`internal/storage/server/command_queries.go:131` tests the same condition for a different and
correct purpose: it keeps the command status at `executing` when a signal was sent but exit was not
confirmed. That behaviour must be preserved. The two sites are not duplicate code and must not be
merged.

## Tests that encode the current assumption

- `internal/tui/model_test.go:24` — `TestStatusLabelDoesNotOverstateEvidence` asserts
  `StatusLabel(StatusFinished, ExecutionReceipt{DeliveryBoundary: DeliverySignalSent}) ==
  "stop request sent"`. The test name claims conservative wording while hardcoding the stop label
  for an operation-free receipt. It passes an empty receipt, so it cannot detect the operation
  ambiguity.
- `tests/bdd/steps_tui.go:28` — step `^signal sent without exit confirmation is displayed as stop
  request sent$`, asserted at `tests/bdd/steps_tui.go:225`. The driving scenario
  (`features/real_boundary.feature`) submits a stop command, so the assertion is correct for that
  scenario but encodes the wording as universal.

Any fix must update both.

## Options

| Option | Change | Trade-off |
|---|---|---|
| A | Add `Operation` to `ExecutionReceipt` and make the label operation-aware | Cleanest; requires protocol and stored `receipt_json` compatibility handling |
| B | Pass the operation into `StatusLabel` as a parameter | No schema change; every call site must pass it correctly |
| C | Document only, revisit when a second adapter lands | No risk now; the defect stays latent |

Recommended: C for the current release, because the label is correct for the only shipped adapter
and a protocol change for a latent defect is not justified yet. Revisit at the second-adapter
milestone, where A becomes the natural choice.

## Status

Open, latent. Not fixed. The current single-adapter behaviour is correct, so this is a design
hardening item rather than a user-visible defect. Requires a human decision on the option before
implementation.
