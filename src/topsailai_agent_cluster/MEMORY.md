# Memory

Facts and decisions the human directed to be recorded for this project. AI self-learned lessons
belong in `LEARN.md`, not here.

## StatusLabel hardcodes "stop" onto a generic delivery boundary

Directed by the human on 2026-11-08: record the `StatusLabel` finding in the project memory
document.

### Current behaviour is correct, and that is not the same as being right

`internal/tui/model.go:107-109` returns `stop request sent` whenever
`DeliveryBoundary == signal_sent && !ExitConfirmed`, before the status switch and without
considering the operation.

It is correct today. The only shipped adapter maps `signal_sent` from `workspace kill`, which is
`agent.stop`, so every receipt that reaches the guard really is a stop. The genuinely stop-specific
provider states `stopped` / `already_stopped`
(`internal/adapter/topsailai/adapter.go:642-648`) set `ExitConfirmed = true` and never trigger it.

### Why it is still a defect

`signal_sent` is a generic delivery boundary (`internal/protocol/command.go:82`), and the shared
helper `internal/adapter/command.go:164-165` maps it for every adapter. A second adapter reporting
`signal_sent` for a non-stop operation would display the wrong wording with no cluster-side code
change. The `default` branch at `internal/adapter/topsailai/adapter.go:666-667` reaches the same
boundary for an unrecognized `delivery_state` carrying `signal_sent: true`.

### Why it cannot be fixed locally

`protocol.ExecutionReceipt` (`internal/protocol/command.go:124-141`) has no `Operation` field, so
`StatusLabel` cannot distinguish operations. A fix needs either a new receipt field, which changes
the protocol and stored `receipt_json` compatibility, or an operation parameter on every call site.

### Do not conflate the two identical conditions

`internal/storage/server/command_queries.go:131` tests the same condition for a different and
correct purpose: it keeps the command at `executing` when a signal was sent but exit was not
confirmed. The two sites must not be merged.

### Tests encoding the current assumption

`internal/tui/model_test.go:24` passes an empty receipt, so it cannot detect the operation
ambiguity. `tests/bdd/steps_tui.go:28,225` asserts the wording for a scenario that genuinely submits
a stop.

### Decision

Documented only. Revisit at the second-adapter milestone, where adding `Operation` to the receipt
becomes the natural choice. Full record in
`issues/statuslabel-signal-sent-mislabels-operation.md`.

## LEARN.md and MEMORY.md are separate documents

Directed by the human on 2026-11-08: `LEARN.md` is what the AI learned itself; `MEMORY.md` is what
the human decided should be recorded. They must remain two real files, never a symlink to one
another, and both are loaded into agent context.
