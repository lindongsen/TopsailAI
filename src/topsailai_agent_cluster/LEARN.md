# Learn & Memory Of Project

## Verify the producer of a value before claiming a defect is reachable

Trigger: while reviewing `StatusLabel`, the cluster-side mapping of `signal_sent` was found to be
operation-agnostic, and this was reported to the human as "send, interrupt and ctl actions can
display `stop request sent`". That claim was wrong. The real provider emits `signal_sent` from
`workspace kill` only; `runtime send` emits `pipe_written`, `runtime control` emits
`control_acknowledged`, and `runtime btw` emits `injection_queued`.

Action: before asserting that a defect is reachable, trace the value back to its producer and
enumerate every site that can emit it. For a cross-project boundary, read the producing project's
source, not only the consuming project's mapping. State reachability as "verified by producer
source at <path:line>" or mark it explicitly as unverified.

Why this prevents recurrence: the consuming side can only show which values it accepts, never which
values the producer actually sends. A mapping that looks operation-agnostic is not evidence that
every operation reaches it. Checking the producer converts a plausible inference into a fact, and
prevents reporting a latent design smell as an active user-visible bug.

## StatusLabel hardcodes "stop" onto a generic delivery boundary

Trigger: `internal/tui/model.go:107-109` returns `stop request sent` whenever
`DeliveryBoundary == signal_sent && !ExitConfirmed`, before the status switch and without
considering the operation.

Current status: latent, not reachable today. The only shipped adapter maps `signal_sent` from
`workspace kill`, which is `agent.stop`, so the wording is correct for every receipt that reaches
the guard. The genuinely stop-specific provider states `stopped` / `already_stopped`
(`internal/adapter/topsailai/adapter.go:642-648`) set `ExitConfirmed = true` and never trigger it.

Why it is still a defect: `signal_sent` is a generic boundary (`internal/protocol/command.go:82`),
and the shared helper `internal/adapter/command.go:164-165` maps it for every adapter, so a second
adapter reporting `signal_sent` for a non-stop operation would display the wrong wording with no
cluster-side code change. The `default` branch at `adapter.go:666-667` reaches the same boundary for
an unrecognized `delivery_state` carrying `signal_sent: true`.

Why it cannot be fixed locally: `protocol.ExecutionReceipt`
(`internal/protocol/command.go:124-141`) has no `Operation` field, so `StatusLabel` cannot
distinguish operations. A fix needs either a new receipt field (protocol and stored `receipt_json`
compatibility) or an operation parameter on every call site.

Do not conflate: `internal/storage/server/command_queries.go:131` tests the same condition for a
different and correct purpose, keeping the command at `executing` when a signal was sent but exit
was not confirmed. The two sites must not be merged.

Tests encoding the current assumption: `internal/tui/model_test.go:24` passes an empty receipt, so
it cannot detect the operation ambiguity; `tests/bdd/steps_tui.go:28,225` asserts the wording for a
scenario that genuinely submits a stop.

Decision: documented only. Revisit at the second-adapter milestone, where adding `Operation` to the
receipt becomes the natural choice. Recorded in
`issues/statuslabel-signal-sent-mislabels-operation.md`.
