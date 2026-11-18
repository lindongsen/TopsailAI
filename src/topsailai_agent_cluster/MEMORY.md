# Memory

Facts and decisions the human directed to be recorded for this project. AI self-learned lessons
belong in `LEARN.md`, not here.

## Server never holds an Endpoint credential secret

Directed by the human on 2026-11-18, wording normalized, meaning preserved:

> BDD scenarios must cover both bearer and HMAC authentication comprehensively. The Server must never store an Endpoint token, and in HMAC mode it must never see the Endpoint token or secret.

This is a standing trust-boundary rule. In bearer mode the Server may forward the presented Endpoint token opaquely for compatibility, but it must never persist it, index it, log it or use it as Server authority. In HMAC mode the CLI proves possession directly to the Endpoint: the Server may see and forward only the public key ID, timestamp, nonce, signature and request digest needed by the Endpoint to verify the proof. The full `key_id.secret` pair and its secret part remain exclusively in CLI configuration and the Endpoint-local policy file.

Trigger: adding or changing Endpoint authentication, request envelopes, logs, persistence, tests or troubleshooting surfaces.

Action: keep Server DTOs, storage and logs free of Endpoint tokens and secrets; verify bearer and HMAC independently in BDD; add negative assertions that HMAC requests and Server evidence contain neither the pair credential nor its secret; reject a signature failure as authentication without falling back to bearer or consulting policy.

Why this prevents recurrence: a Server that can read or retain the Endpoint secret becomes a second Endpoint authorizer and can mint valid proofs, which breaks the architecture's separation of routing from local authority. Testing only success or only one mode can miss a transport field, diagnostic or persistence path that silently leaks the credential.

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

## Point out an existing convention instead of inventing a parallel one

Directed by the human on 2026-11-10; wording normalized, meaning preserved:

> 此外，如果是已经存在的通用做法，你要提醒我。保持标准化和复用性也是很重要的。要记住。

This is a standing rule for every change, not a note about one prompt. Before adding a constant, a
helper, a format, a naming scheme or a control flow, search the project for the same concept. If a
convention already exists, reuse it and tell the human that it exists. If none exists, say so before
creating one. If the existing convention is itself inconsistent, raise that as a decision for the
human instead of quietly starting a second one.

The rule exists because this was violated in the bare-`send` confirmation work. A new constant
`sendAnswerHint = "(y/N)"` was added while `confirmationHint = "[y/N]"` already existed in
`internal/tui/style.go`. The duplicate was not a harmless extra line: `answerHintIndex` had to accept
two spellings and take the last match, and the CLI advertised its accepted answers two different ways
depending on the command. The human corrected it with `用[y/N]吧，统一起来`, after which
`sendAnswerHint` was deleted, `answerHintIndex` collapsed to a single `strings.LastIndex`, and
`sendConfirmPrompt` became `"send.confirm" + confirmationHint + "> "`. The code got shorter and the
divergence became structurally impossible.

Consequences that MUST hold:

- Reuse the existing constant, helper or pattern, and name it when reporting the change, so the human
  can confirm the reuse was the right call.
- Never introduce a second spelling, a second constant or a second code path for a concept the
  project already models. A duplicate is a future divergence, not a local convenience.
- When the existing convention looks wrong or incomplete, report it and ask. Do not fork it silently
  and do not "improve" it in passing.
- When a change makes an existing abstraction reusable, prefer wiring the new case into that
  abstraction over copying its behaviour, so one definition keeps serving every caller.

## Quote the human's meaning, not their disfluency

Directed by the human on 2026-11-10, wording normalized:

> 原话不通顺的话也不要照抄。

A recorded human statement must preserve what the human decided. It must not preserve typing
artefacts, missing punctuation, run-on clauses or a stray leading word that only made sense in the
middle of a conversation. Normalize the wording, keep the meaning, and label the quote honestly as
normalized rather than verbatim.

This corrects an over-literal habit. The rule "preserve the human's own words" was being applied as
"copy the message byte for byte", so a recorded quote began with an unrelated instruction from the
same message and read as broken Chinese. The decision it carried was clear; the transcription was
not. The same problem appeared twice in the plan document for the bare-send confirmation prompt.

Consequences that MUST hold:

- Preserve the decision, the constraint and the intent. Those are the facts that must survive.
- Fix grammar, punctuation and spacing, and drop fragments that belong to a different instruction in
  the same message.
- Label the result as normalized, for example `wording normalized, meaning preserved`, so a reader
  never mistakes it for a verbatim transcript.
- Never paraphrase into a different decision. Normalizing wording is allowed; changing what the human
  asked for is not.
- Keep the original wording when the exact phrasing is itself the subject, such as a command name, a
  prompt string or a UI label the human typed deliberately.

## Commit each completed logical unit immediately

Directed by the human on 2026-11-12, wording normalized, meaning preserved:

> 逻辑单元完成并验证后，就可以提交。

For the current workspace-clean task and future project work, a logical unit may be committed as soon
as its implementation and relevant tests are complete, its complete diff has been reviewed, and no
known blocker remains. Do not wait for every later unit in a multi-unit task, and do not include
unrelated concurrent changes in that commit.

## Interactive CLI behaviour must prioritize usability

Directed by the human on 2026-11-12, wording normalized, meaning preserved:

> 所有 CLI 交互模式的行为都必须考虑易用性。

This is a standing design and review rule for every interactive CLI behaviour. The interactive surface
must reduce avoidable typing, lookup and repetition by using the operator's current scope, recently
rendered rows, numbered choices, prompts, context-derived defaults and short discoverable forms where
those choices remain unambiguous.

Convenience must reuse the canonical operation rather than create different semantics, and it must not
weaken exact target selection, authorization, destructive confirmation, generation checks, capability
checks or visible failure reporting. When convenience and certainty conflict, fail closed and explain
the shortest safe next step. Help, completion, examples, errors and composed-path tests must describe
and verify the same convenient behaviour.

`clean <row|session>` is the reference pattern: the operator may use the visible list row for speed or
a Session identifier when no table is available; the row is resolved locally to the real target and is
never treated as durable identity.

## Every interactive CLI input must be recorded in history

Directed by the human on 2026-11-12, wording normalized, meaning preserved:

> CLI 交互模式中提交的所有输入都需要记录到 history。

This is a standing rule for the entire interactive CLI, not only the top-level REPL. Every accepted
nonblank submission is persisted in bounded private JSONL history, including command lines,
confirmation answers, guided choices and wizard answers. Rejected, overflowed and blank input is not a
submitted value and is not recorded.

Recording does not imply recall. REPL commands are recallable with Up/Down; prompt and wizard answers
are recorded for history but never offered as commands or future prompt defaults. This distinction
prevents a context-specific answer such as `y` or `3` from becoming an accidental command or repeated
destructive confirmation.

## Every deployment uses `/opt/agent-cluster` as its single product root

Directed by the human on 2026-11-12, wording normalized, meaning preserved:

> 所有节点和角色的部署路径都必须是 `/opt/agent-cluster`；gd-dev 也不能使用单独的产品根目录。

This is a standing deployment rule for every host, container and role. Server, Endpoint and CLI files
must all live below `/opt/agent-cluster`. Role-specific subdirectories are allowed when identities,
configuration files or certificate names would otherwise conflict, but parallel product roots such as
`/opt/agent-cluster-gddev` and `/opt/agent-cluster-gw` are not allowed.

The current gd-dev deployment is noncompliant: its Server uses `/opt/agent-cluster`, while its Endpoint
and rebuilt CLI use `/opt/agent-cluster-gddev`, and an older CLI remains under
`/opt/agent-cluster-gw`. These paths are migration sources, not approved conventions. Do not delete
them until the unified layout is running and rollback evidence exists.

The Server and Endpoint packages currently conflict and install overlapping configuration and
certificate paths. Resolve that package/layout defect with role-specific paths below the standard root;
do not preserve the defect by documenting a second installation root. This prevents each node from
inventing a different layout and keeps deployment, upgrades, diagnostics and rollback commands
consistent across the fleet.

## Providers implement a standard Adapter CLI in independent projects

Directed by the human on 2026-11-12, wording normalized, meaning preserved:

> Adapter 是 Endpoint 的抽象层并定义标准。Endpoint 调用标准 Adapter 函数，Adapter 直接启动
> provider CLI；provider CLI 按标准包装请求和行为，再自行对接 provider 业务。Cluster 不关心
> provider CLI 后面的命令行、API、SDK 或其他实现方式。

This supersedes the earlier same-repository linkable Go provider proposal. The mandatory call direction
is:

```text
Endpoint service -> Endpoint-owned Adapter -> generic CLI Adapter -> provider CLI -> provider business
```

The direct provider process invocation is an Endpoint implementation mechanism such as Go
`exec.CommandContext`; it is not the public Cluster operation `command.exec`. Public `command.exec`
remains the Endpoint-native, operator-requested allowlisted command surface.

Directed by the human on 2026-11-12, wording normalized, meaning preserved:

> Provider CLI 在 MVP 中是本地可信组件，但不提供安全沙箱隔离。Provider CLI 作为独立组件和
> 独立项目维护，先放在 `providers/` 下，其中 `topsailai` 对接 TopsailAI 业务命令行，`mock`
> 用于测试。

The provider projects are:

```text
providers/
├── topsailai/
└── mock/
```

They share the repository but have independent build metadata, dependencies, tests, versions and
executable artifacts. They are not imported or compiled into Endpoint. `providers/topsailai` may call
the installed TopsailAI CLI and understand its native fields; the generic CLI Adapter may not.
`providers/mock` is both the conforming reference and the locally configured fault injector for
conformance and integration tests. Remote requests can never select a mock fault mode.

Directed by the human on 2026-11-12, wording normalized, meaning preserved:

> Provider CLI 使用独立安装包；Endpoint package 不依赖任何具体 provider。Mock 只作为测试构建产物，不进入默认生产安装。

The initial package boundary is `agent-cluster-endpoint` plus the optional
`agent-cluster-provider-topsailai`; the Endpoint package has no dependency on that or any future
provider package. `providers/mock` produces a test artifact only and is excluded from default
production packages and installations. Provider releases use versioned artifacts and are activated by
an explicit Endpoint-local binding change after protocol compatibility checks; installation alone does
not restart the Endpoint or silently replace the active executable. Keeping the previous versioned
artifact and binding path provides rollback.

For the MVP, provider CLI trust is operational trust, not enforced isolation. Process separation gives
module, dependency and fault isolation; a provider running under the Endpoint OS identity is not
sandboxed from files that identity can read. Supporting hostile providers later requires a separate
OS-user, filesystem, credential, network and sandbox/container design. Even trusted providers remain
subject to strict framing, bounded I/O, deadlines, exact process cleanup and local-only executable
configuration.

Directed by the human on 2026-11-12, wording normalized, meaning preserved:

> Keep `adapter_id`; it already identifies one configured Adapter instance, so introducing
> `binding_id` would only rename the same concept. Do not retain the old `CommandAdapter` as a legacy,
> fallback or parity implementation.

`adapter_id` remains the stable Endpoint-local identity of one configured Adapter instance. Multiple
Adapter instances may use the same `provider_type` or provider executable implementation. Resource
mapping therefore uses `(adapter_id, resource_kind, provider_resource_key)`: the necessary migration
adds the resource kind; it does not rename Adapter identity.

The independent Provider CLI replaces the current command-based and compiled-in provider paths rather
than running beside them as supported alternatives. Acceptance is against the Cluster contract,
fixtures, BDD, integration tests and bounded live smoke evidence, not an old/new implementation parity
suite. Once the replacement unit lands, the old `CommandAdapter`, its argv protocol, the compiled-in
TopsailAI factory path and provider-command templates are removed in that same reviewed unit. They are
not rollback targets. Rollback means selecting a previously verified versioned Provider CLI artifact
for the same `adapter_id`.

Endpoint must be able to start, connect and report health with zero configured Adapters. Provider
activation is an Endpoint-local per-adapter replace operation driven by `agent-clusterctl`; installing a
Provider package alone never activates it or restarts the whole Endpoint.

Endpoint retains all Cluster authority: authorization, local policy, command journal, deduplication,
`ResourceMapper`, effective capabilities, Cluster IDs and complete `ExecutionReceipt` construction.
Provider CLI requests carry provider-private keys, expected generations, standard functions, typed
payloads, deadlines and budgets. They do not carry Cluster resource authority, complete
`ImmutableIntent` objects or complete receipts. A mutating provider call revalidates
`expected_generation` in the same execution path; a prior `inspect` alone is not sufficient.

Directed by the human on 2026-11-12, wording normalized, meaning preserved:

> 只读能力使用统一的 `query` framing，但 query 名称以及请求和结果 schema 必须由 Cluster
> 标准定义。

The query registry is closed and versioned. Providers may advertise support for registered queries but
cannot add arbitrary provider-namespaced queries. Mutations use `execute`; provider-specific approved
controls remain `ctl.<action>`. Effective control actions are the intersection of provider-described
actions and Endpoint-local approval, while provider-native argv remains inside the provider project.

Trigger: the first provider-seam design treated an in-process Go interface, the external provider
protocol and provider business invocation as one boundary, which risked serializing Cluster authority
into a provider request and keeping native command templates in Endpoint configuration.

Action: keep the Endpoint-internal Adapter contract and external JSON/JSONL protocol as separate seams;
map provider keys to Cluster IDs only in Endpoint; compose complete receipts only in Endpoint; keep
provider commands inside provider projects; and validate the boundary with an executable mock and
closed query schemas.

Why this prevents recurrence: a process boundary alone does not create abstraction. Explicit ownership
prevents a new provider from depending on Cluster internals, prevents a provider result from claiming
journal authority, and lets a provider be replaced through installation and local binding configuration
without changing Endpoint, Server, storage, public API or operator CLI source.

## Server never sends requests to an offline Endpoint

Directed by the human on 2026-11-12, wording normalized, meaning preserved:

> Endpoint 进入 offline 状态后，Server 不再向它发送请求。

This is a standing routing rule. The authoritative in-memory channel peer is the send boundary: when
heartbeat expiry or transport disconnection removes that peer, every command, query, output read,
follow and refresh must fail immediately as offline instead of being written, queued or retried.
Persisted `connection_state` is an operational projection and must not create a second send path.
A later authenticated reconnect installs a new fenced peer and restores request delivery through that
new connection only.

## Mutation authority stays host-scoped; cross-host work goes through resume

Directed by the human on 2026-11-16, wording normalized, meaning preserved:

> 方案 B：改文档，不改代码。

The `--local` host scope is decided per read, not per phase. Five production reads exist and the split
is three that pass `--local` and two that do not:

| Read | `--local` | Why |
|---|---|---|
| `discover` (`read.go:78`) | yes | the inventory lists only what this host can control |
| `resolveWorkspaceTarget` (`read.go:307`) | yes | follow, output and query address this host's output and state |
| `workspaceAuthority` (`mutation_authority.go:48`) | yes | mutation authority stays on rows this host can confirm |
| `inspect` (`read.go:104-125`) | no | a session recorded on another host must still be judged for liveness |
| `sessionAuthority` (`mutation_authority.go:151`) | no | the session registry is not host-partitioned |

`workspace.clean` and `agent.drive.stop` mutate or delete provider state, so they must stay confined to
rows this host can verify. Cross-host work has one supported path: `agent.resume` with a session-scoped
key, which reads the session registry and never passes `--local`. Do not widen `workspaceAuthority` to
compensate, because that would extend a destructive operation's reach to every row in a shared task
directory.

The document `docs/agent-cluster-adapters.md` previously described the split by phase ("discovery uses
`--local`, revalidation does not"), which was wrong because revalidation has two reads and only one
omits it. The document now states the per-read rule, and `workspaceAuthority`'s own doc comment records
the same reason at the site that implements it.

## `list` must always read only the Server's existing data

Directed by the human on 2026-11-17, wording normalized, meaning preserved:

> 同意，认可。list 在任何情况下，永远都只能拿 server 现成的数据。

This is a standing rule for every `list` surface, scope and flag, not a note about one column. `list`
renders only the inventory the Server already persisted. It never triggers Endpoint collection, never
triggers a provider read, and never waits on an Endpoint.

The rule exists because the `MESSAGES` column was read live at render time through
`MetricsEnricher`, one batch request per render, even though the counts were already available from
the same provider command discovery runs. The human rejected that design: the data should be
reported, not read on demand.

Consequences that MUST hold:

- Every column `list` renders must be carried by the periodic inventory report. A missing fact is
  added to the report, never read at render time.
- An unmeasurable fact is reported as absent and renders as `-`, never as `0`.
- `refresh` stays the only path that forces a fresh collection, and it is a separate command with
  its own budget and failure reporting, not a `list` mode.
- A new `list` read surface must be proven to issue zero Endpoint requests by counting provider
  invocations, not by observing a fast render.

The rule is recorded in `docs/agent-cluster-architecture.md` under
"`list` reads only the Server's persisted inventory".

## CLI Server failover sticky state is per operator, not per project directory

Directed by the human on 2026-11-18, wording normalized, meaning preserved:

> sticky 文件就保持 per-operator，不用按项目目录分。

The CLI remembers the last Server profile that answered in one file per operator, at
`${HOME}/.topsailai/.topsailai_agent_cluster.server-profile`, overridable with
`AGENT_CLUSTER_CLI_SERVER_PROFILE_STICKY_FILE`. It is never partitioned by project
directory.

Two reasons, and both are load-bearing:

- It reuses the convention this CLI already has. Per-user CLI state lives together under
  `.topsailai`, beside the configuration file and the input history
  (`inputHistoryRelativePath` in `src/main/agent-cluster-cli/input_history.go`). A second
  partitioning scheme would be a second spelling of "where this operator's CLI state
  lives", and the two would drift.
- The file is advisory, so a wrong entry self-corrects. `preferSticky` ignores a name that
  is no longer configured, and the next successful invocation overwrites the file. A
  misremembered Server therefore costs one probe, not a broken invocation.

Partitioning by project directory would add a state file per project and buy no behaviour
difference, because the preference is already self-correcting and already reported when it
is used or ignored.

Consequence that MUST hold: do not add a project-directory dimension to this file. If a
future requirement genuinely needs two independent selections at once, that is a new
decision to raise with the human, not an extension of this one.

## Each provider folder is an independent workspace

Directed by the human on 2026-11-18, wording normalized, meaning preserved:

> 我认为 providers 里面的项目的文件夹结构不友好，你要把每个provider的文件夹当做是独立的工作空间一般看待。

> mock folder is an independent workspace, topsailai folder is also an independent workspace.

Every folder directly under `providers/` is a workspace in its own right, not a package directory
inside the cluster project. A reader who opens one provider folder must find everything needed to
understand, build, test and diagnose that provider without reading the cluster Makefile or the cluster
documentation.

The required shape of every provider workspace:

```text
providers/<name>/
├── README.md      # what this provider is, how to build, test and run it
├── project.yaml   # workspace metadata: workspace, ProjectFolder, ProjectRootFolder, ProjectCode, language
├── Makefile       # build vet fmt test check clean, artifacts under .tmp/
├── go.mod         # module root, because Go requires the module root to be the workspace root
├── go.sum         # when the module has dependencies
├── issues/        # provider-owned issue records, when the provider has any
└── src/           # package main and its unit tests, because Go requires tests beside their package
```

Two constraints are structural rather than stylistic, and neither may be traded away for tidiness:

- `go.mod` stays at the workspace root. Moving it into `src/` would make `src/` the module root and
  break every import path and every `go build ./src` invocation.
- Unit tests stay in `src/` beside the code they test. Go requires a test file to live in the package
  directory, so a separate `tests/` folder inside a provider would not compile.

Consequences that MUST hold:

- The cluster builds a provider as `./src` from the provider workspace root, never as `.` and never by
  importing the module. `providers/mock` and `providers/topsailai` are separate modules with separate
  dependency graphs, versions and artifacts.
- A provider workspace owns its own build entry point. The cluster `Makefile` may call it, but the
  provider `Makefile` must also work when run directly with `make -C providers/<name>`.
- Provider build artifacts go to that provider's own `.tmp/`, so one provider's build cannot overwrite
  another's.
- Provider-specific detail stays inside the provider workspace. `docs/agent-cluster-adapters.md` remains
  the only cluster document that describes a provider, and no provider vocabulary enters
  `internal/protocol`, a Server route, a stored document or a CLI help body.
- A new provider is created by copying this shape, not by adding files to an existing provider folder.

Why this is recorded: the previous layout put 41 `.go` files at the root of `providers/topsailai` and 7
at the root of `providers/mock`, with no README, no Makefile and no workspace metadata. Nothing in
either folder said how to build or test it, so the only way to learn was to read the cluster Makefile,
which is the wrong place to look for a component that is supposed to be independent.
