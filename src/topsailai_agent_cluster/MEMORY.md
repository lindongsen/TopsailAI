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

## Tests live in the Makefile, split by component and by test kind

Directed by the human on 2026-11-09, quoted verbatim:

> 测试要写到 Makefile 里面，按组件区分，按测试种类区分。例如：公共的，server的，endpoint的，etc..；单元测试，bdd测试，集成测试, etc..

Directed by the human on 2026-11-09, quoted verbatim:

> 组件级别 或者 较大范围的测试 都应该使用 make 去做，你记到项目记忆里面

So the Makefile is the single entry point for tests, and it exposes two independent axes:

- By component, for unit tests: `test-unit-common`, `test-unit-server`, `test-unit-endpoint`,
  `test-unit-cli`, aggregated by `test-unit`.
- By test kind: `test-unit`, `test-bdd`, `test-integration`, `test-packaging`, `test-harness`,
  aggregated by `test-all`. `test` stays the untagged default suite.

Component-level and larger-scope test runs MUST go through a `make` target rather than an ad-hoc
`go test` invocation. A `make` target carries the package group, the build tags and the working
directory in one place, so every agent and every run verifies a component the same way. An ad-hoc
`go test ./internal/...` silently drops the `integration testhooks` tag or picks up a package that
belongs to another component, and the difference is invisible in the output.

The component groups are explicit package lists, not directory patterns, because package ownership is
not directory nesting: `internal/channel` is shared by Server and Endpoint, so it belongs to common and
must not be verified twice, while `internal/adapter` is Endpoint-only even though it sits beside shared
packages. A new package therefore has to be assigned to a group deliberately.
