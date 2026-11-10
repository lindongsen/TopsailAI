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

## The cluster defines the abstraction first; adapters follow it

Directed by the human on 2026-11-09, quoted verbatim:

> 你要注意，cluster是个抽象层，你得设计自己的接口，再去对接adapter。别管provider是怎么做的，你不用学它，你要有自己的抽象模型，抽象层。

Directed by the human on 2026-11-09, quoted verbatim:

> 你把这种原则，这种开发方式，记到文档里，cluster始终是抽象层，通用框架，行为模式要先自己定，不要去照着adapter/provider来定。

This is a standing design rule for every future change, not a note about one feature.

The cluster is the abstraction layer and the general framework. Its resources, operations, result
documents, error codes, safety classes and authorization scopes are defined by the cluster itself,
from the cluster's own model of what an operator needs. An adapter then maps that contract onto
whatever a provider happens to offer. The direction is always cluster -> adapter. A provider's
vocabulary, numbering, file layout, flags or record format must never become the shape of the
cluster contract.

Consequences that MUST hold for every new capability:

- Name the abstract resource and the abstract operation first, in cluster terms, before reading any
  provider source. If the design cannot be stated without naming a provider, it is not a design yet.
- Provider detail is confined to the adapter mapping section of `docs/agent-cluster-adapters.md` and
  to adapter code. It never appears in `internal/protocol`, in a Server route, in a stored document
  or in a CLI help body.
- A provider's own numbering, index or row number is presentation, never an identity. The cluster
  mints its own opaque ID through `adapter.ResourceMapper`, and a bare number typed by an operator is
  resolved client-side against the last rendered list, exactly as `resume <row>` already works.
- A capability that the cluster needs as a first-class operation must be a standard operation with
  its own name, safety class and permission. It must not be reachable only through the generic
  `ctl.<action>` escape hatch, because that hatch exists for provider-specific actions.
- Reuse an existing cluster pattern rather than inventing a new one. A new read surface is a new
  instance of the history pattern (optional adapter interface, protocol query/result pair, channel
  frame pair, Server route with a scope rule, client method), not a new pattern.
- Adding or replacing an adapter must require no protocol, Server, database schema or CLI change. If
  it does, the contract was shaped by the adapter and must be redesigned.

Why this is recorded: the first design of the session model-selection command was written by reading
the provider's registry file, its selection function and its numbered text output, and then copying
that shape into the cluster. The result was a design that could not be stated without naming provider
files, that inherited a provider numbering scheme as if it were an identity, and that would have
required a provider change to produce a structured menu. The human rejected the direction, not the
feature. The corrected design defines `ModelProfile`, `agent.model.list` and `agent.model.select` in
cluster terms and confines every provider detail to one adapter section. See
`.task/plan_20261109T150000_session-model-command.md`.
