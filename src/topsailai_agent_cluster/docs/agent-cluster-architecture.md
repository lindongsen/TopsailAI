---
maintainer: AI
author: DawsonLin
status: discussion-draft
created: 2026-10-27
---

# Unified Agent Management Architecture

## Document index

- `docs/agent-cluster-architecture.md`: goals, boundaries, topology, storage, security, container deployment and design decisions; discussion draft.
- `docs/agent-cluster-protocol.md`: abstract resources, capability negotiation, APIs, commands, synchronization and recovery; discussion draft.
- `docs/agent-cluster-adapters.md`: Endpoint-private TopsailAI mapping and integration questions; discussion draft.
- `docs/agent-cluster-database.md`: three Server business tables, constraints, transactions and retention; discussion draft.
- `docs/agent-cluster-history.md`: provider session history read, resume addressing and the inventory join; implemented contract.
- `docs/API.md`: implemented Server HTTP surface and response envelope; implemented contract.
- `docs/Environment_Variables.md`: every variable, its flag, its default and the three deployment configuration sources; implemented contract.
- `docs/cli-command-surface-rules.md`: rules the operator CLI command surface must follow; implemented contract.
- `docs/agent-cluster-endpoint-access-policy.md`: the Endpoint-local policy directory that decides which cluster operations each caller may exercise on an Endpoint; discussion draft.

The `agent-cluster-*.md` documents are discussion drafts, not an approved final specification;
the documents marked as an implemented contract describe behaviour that exists in the code.
Naming, machine-level Endpoint scope, required lifecycle support and the absence of periodic stdout
snapshot refresh are human-confirmed decisions; other proposals remain under discussion.
Implementation and verification planning is tracked separately in
`.task/plan_20261027T153140_agent-cluster-delivery.md` (project-relative path).

## Human requirements and sources

The human supplied these requirements:

> 我需要一个统一的、标准的、agents管理方式。
> topsailai 这个cli，我可以通过这个cli去获得 agent 的任务信息，session信息，stdout 等等。
> server和endpoint都有一个进程，都会提供API接口，endpoint会去调用cli来获得信息。
> 通过server端的cli(tui)可以看到所有endpoints的agent工作情况，可以给对应的endpoint去发送指令。
> server/endpoint 做得足够通用，接口是抽象的，topsailai这个cli是一种adaptor，对接到endpoint里面。
> server/endpoint 的接口是抽象的，通过endpoint去对接各种各样的agent。
> 请制定一个技术方案，写到文档里面，我们再多探讨。

Source note: topsailai-data object `myidea-agent-cluster-server-endpoint`, retrieved on 2026-10-27. It proposes Server/Endpoint management, task control, instruction dispatch, status observation, abstract model interfaces, and agents running at endpoints. The original note is unchanged.

Additional evidence: installed `topsailai --help`, `runtime --help`, `workspace --help`, and CLI documents `topsailai.md` and `topsailai_send_control.md`. Only help and documentation were queried; no runtime inventory or control operation was executed. The workspace contained `.tmp/` and `.topsailai/`, with no existing implementation or project README.

## Confirmed naming and first-release scope

The human confirmed:

> 第一版需要有 启动/恢复/停止 agent； 第一版 stdout 不需要定时刷新快照；endpoint的边界是机器，操作系统里面有一个endpoint的进程，可以对接多个adapter（不同的agents）
> 我同意，请更新设计文档。此外，要把设计文档保存到 docs/ 文件夹中。其它文档仍然在 .task/ 里面。

The naming proposal was accepted: product **Agent Cluster**; project/repository `topsailai_agent_cluster`; three independent executable commands `agent-cluster-server`, `agent-cluster-endpoint` and `agent-cluster-cli`; service names match the Server/Endpoint commands; first adapter ID `topsailai`. Do not use an `agent-cluster` executable with role subcommands. Each command is independently launched; internal libraries may be shared. Adapters initially run inside the Endpoint process, not as separate services. SQLite support is now required; language and transport choices remain proposals.

The human clarified the three related names, quoted verbatim:

> topsailai是本地管理agent的入口，agent-cluster-cli是跨机器管理agents，topsailai2就是跨机器管理的意思

| Name | Scope | Meaning |
|---|---|---|
| `topsailai` | Local | Entry point that manages agents on the local machine |
| `agent-cluster-cli` | Cross-machine | Operator CLI that manages agents across machines through the Server |
| `topsailai2` | Cross-machine | Installed symlink alias of `agent-cluster-cli`, carrying the cross-machine meaning |

`topsailai` and `agent-cluster-cli` are therefore not interchangeable: the former is the provider CLI that manages local agents, the latter is the cluster operator CLI. `topsailai2` is an alias of `agent-cluster-cli`, not a separate implementation.

Start/resume/stop are mandatory MVP platform capabilities. A provider that lacks a safe implementation must report the gap, but the first-release TopsailAI lifecycle gap cannot be deferred as an optional feature. No periodic stdout snapshot refresh is required. Continuous output follow is required as an explicit operator action in both the interactive REPL and the standalone command; it is a live tail over the existing authenticated channel, not a background refresh and not a durable subscription. Design documents live in `docs/`; planning, execution checklists and evidence remain in `.task/`.

## Recommendation

Build a provider-neutral management plane with a versioned resource model and capability contract. TopsailAI is the first provider implementation, not the definition of the protocol. The protocol is a proposed project standard, not a claim of compatibility with an existing industry standard.

```text
Operator CLI / TUI / future Web UI
                 |
          Server public API
                 |
   Registry + inventory projection + command router + audit
                 |
  Endpoint-initiated authenticated persistent connection
                 |
      Endpoint API and local execution authority
                 |
       Adapter registry and provider bindings
           /             |               TopsailAI CLI      Other CLI        SDK / HTTP agent
```

The CLI/TUI is a separate client process, even when installed on the server machine. It never reads endpoint files, invokes provider CLIs, or bypasses the Server API. Server and Endpoint each have an API-serving process; adapters run inside the Endpoint process initially. Provider CLIs are bounded child processes, not additional permanent platform services.

## Strict Server and Endpoint abstraction boundary

Human requirement:

> server不能关心任何的adapter，server和endpoint的交互只有抽象的、标准的api接口。endpoint来关心adapter就行。

Server knows only Endpoint identity, standard Agent/Session/Task/LaunchProfile resources, standard operation schemas, current inventory and command evidence. It never manages an adapter registry/configuration, imports adapter code, selects adapters or routes execution by adapter/binding identifiers. It may persist and expose Endpoint-reported adapter identity/type/version summaries within sessions_json as descriptive data. Standard API versioning is the sole network integration boundary. Adding/replacing an adapter must not require Server code, database schema or API changes.

Endpoint exclusively owns adapter discovery/configuration, local provider IDs, health details and selection. It translates local observations into the standard inventory and maps opaque public resource/profile IDs back to private adapters. A LaunchProfile is a standard execution preset, not a public adapter alias: its local implementation can change without changing the public model. Server may validate standard resource capabilities but cannot interpret provider-specific operations or parameters. MVP has no provider-specific network passthrough. Internal Endpoint adapter contracts are not Server-facing APIs.

The database proposal is revised from four tables to three: no `endpoint_adapters` table or adapter column in commands. See `docs/agent-cluster-database.md` for the authoritative table design. Supporting authentication/migration infrastructure is separate from these three business tables.

## The cluster defines the abstraction first

Human direction:

> 你要注意，cluster是个抽象层，你得设计自己的接口，再去对接adapter。别管provider是怎么做的，你不用学它，你要有自己的抽象模型，抽象层。

> 你把这种原则，这种开发方式，记到文档里，cluster始终是抽象层，通用框架，行为模式要先自己定，不要去照着adapter/provider来定。

The cluster is the abstraction layer and the general framework. Its resources, operations, result
documents, error codes, safety classes and authorization scopes are defined by the cluster itself,
from the cluster's own model of what an operator needs. An adapter then maps that contract onto
whatever a provider happens to offer. The direction is always cluster to adapter, never the reverse.

This is a design rule, not a preference. A provider's vocabulary, numbering, file layout, flags or
record format must never become the shape of the cluster contract, because the contract is what the
Server, the stored documents, the API and the CLI are built on. A contract shaped by one provider
cannot survive a second provider, and the whole point of this architecture is that a second provider
requires no Server, schema or CLI change.

The rule has five consequences for every new capability:

- Name the abstract resource and the abstract operation first, in cluster terms, before reading any
  provider source. A design that cannot be stated without naming a provider is not a design yet.
- Provider detail is confined to the adapter mapping section of `docs/agent-cluster-adapters.md` and
  to adapter code. It never appears in `internal/protocol`, in a Server route, in a stored document
  or in a CLI help body.
- A provider's own numbering, index or row number is presentation, never an identity. The cluster
  mints its own opaque ID through `adapter.ResourceMapper`, and a bare number typed by an operator is
  resolved client-side against the last rendered list, exactly as `resume <row>` already works.
- A capability the cluster needs as a first-class operation is a standard operation with its own
  name, safety class and permission. It must not be reachable only through the generic
  `ctl.<action>` escape hatch, which exists for provider-specific actions.
- Reuse an existing cluster pattern rather than inventing a new one. A new read surface is a new
  instance of the history pattern, not a new pattern.

The rule also decides where a defect belongs. A cluster-side mapping that looks operation-agnostic is
a cluster defect even when the only shipped adapter cannot reach it, because the contract is what a
second adapter will be written against. Conversely, a provider limitation is an adapter gap and must
be reported as an explicit capability gap rather than absorbed into the cluster contract.

This was learned by getting it wrong. The first design of the session model-selection command was
written by reading the provider's registry file, its selection function and its numbered text output,
and then copying that shape into the cluster. The result could not be stated without naming provider
files, inherited a provider numbering scheme as if it were an identity, and would have needed a
provider change to produce a structured menu. The human rejected the direction, not the feature. The
corrected design defines `ModelProfile`, `agent.model.list` and `agent.model.select` in cluster terms
and confines every provider detail to one adapter section. See
`.task/plan_20261109T150000_session-model-command.md`.

## Component boundaries

| Component | Owns | Must not own |
|---|---|---|
| Server | Endpoint registry, standard capabilities/resources, caller authentication and request routing, latest inventory, standard command routing, audit | Adapter registry/configuration/selection or provider-specific interpretation of reported metadata, provider flags, local paths, PID selection, agent execution, operation authorization |
| Endpoint | Local inventory authority, provider bindings, execution journal, local policy, bounded collection, stream relay | Cross-endpoint scheduling or assumptions about Server UI |
| Adapter | Provider discovery, identity mapping, semantic translation, supported operations, output normalization | Server credentials, network routing, cluster RBAC |
| CLI/TUI | Selection, filtering, status display, confirmation, user intent | Backend polling logic or provider-specific shell commands |

An Endpoint represents one machine: one Endpoint daemon runs in its operating system and hosts multiple adapters/provider bindings for different agents. Do not deploy one Endpoint per account or per adapter. Two bindings of the same provider may use different locally approved roots or execution identities. Cross-account execution requires an explicit least-privilege local policy, not unrestricted impersonation. A binding has a stable ID. A single Server manages many machine Endpoints.

MVP supports start/resume/stop requests by invoking the corresponding Adapter CLI, alongside collecting its returned inventory. Endpoint and Agent are independent: Endpoint is a controller, not an Agent parent process, supervisor or lifecycle owner. Endpoint startup/shutdown/restart does not start, stop, adopt or restart Agents. The provider CLI/runtime is responsible for actual Agent launch, persistence and termination. Endpoint reports only returned evidence; command delivery or CLI exit alone cannot prove Agent readiness or task completion.

That independence is a statement about **control**, not about **process survival**. It holds only when the
Endpoint process and the Agent processes have separate lifecycle boundaries. When they share one, the
boundary decides their fate together and the Endpoint's intent is irrelevant: recreating a container
that hosts both kills every Agent inside it, exactly as restarting a shared systemd unit or a shared
process group would. The Endpoint never issues a stop in that case, yet the Agents die anyway.

This was observed, not hypothesised. The `ai-dev` Endpoint ran inside the same container as the Agents
it launched, and recreating that container at `2026-11-09T01:22:39Z` destroyed both running Agents
while the Endpoint had sent no command. The records and their output survived, because they live on a
mounted volume rather than in the container. See
`issues/endpoint-container-restart-kills-agents-and-hides-records.md`.

Deployment consequence: a container that hosts its own Agents must not be recreated as routine
maintenance, because that is an Agent outage rather than an Endpoint restart. A deb install therefore
installs and does not restart the container. Where Agents must survive an Endpoint restart, the Agents
have to run outside the Endpoint's lifecycle boundary, and that is a deployment decision the protocol
cannot make for the operator.

## Transport and connectivity

The channel is one authenticated TLS WebSocket carrying registration, heartbeat, bounded inventory synchronization, commands and small event frames. It is versioned and direction-agnostic: either side may dial, because a real deployment may only have one working network path.

Three directions are implemented and selected by `AGENT_CLUSTER_CHANNEL_DIRECTION`:

| Direction | Who dials | When to use |
|---|---|---|
| `endpoint-initiated` (default) | Endpoint dials Server | Server is reachable, Endpoint is behind NAT or a firewall |
| `server-initiated` | Server dials Endpoint | Endpoint is reachable, Server cannot be reached from the Endpoint side |
| `bidirectional` | Both sides dial | Neither side can be assumed reachable from the other |

In the `endpoint-initiated` direction the Server opens the channel listener and the Endpoint dials it, so no inbound Endpoint port is exposed. In the `server-initiated` direction the Server opens no channel listener and instead dials each configured Endpoint, so the Endpoint needs no outbound route to the Server. All directions use the same frames, the same handshake and the same fencing rules; only the dialing side differs.

In the `bidirectional` direction both sides dial at the same time, so the cluster converges on whichever link is established last. Convergence needs no extra fencing mechanism: the Server is the sole generation authority, and it acquires the generation inside the same lock that installs the peer, so install order equals generation order. The Endpoint keeps the highest generation it has seen and closes the superseded link. A failed dial never evicts a healthy link, because a generation is proposed during the handshake and committed only after it succeeds.

`AGENT_CLUSTER_TLS_SHARED_CERTIFICATE` makes every Endpoint present the Server certificate, so only one certificate has to be maintained. The certificate then no longer proves which Endpoint is connecting: Endpoint identity becomes an assertion in the hello frame, trusted because the peer holds the shared certificate. This is acceptable only when every Endpoint is equally trusted, and must never be described as per-Endpoint authentication. The mode is opt-in, so the default deployment keeps the certificate-to-Endpoint binding.

The `hello` frame carries an `initiator` field so each side can reject a connection that dialed the wrong side instead of silently accepting it. An empty `initiator` is the legacy Endpoint-initiated handshake and remains valid.

The Server remains the sole authority for the connection generation in both directions. In the `server-initiated` direction the Server proposes a generation in `hello` and the Endpoint adopts it, so fencing behaves identically either way. A dialer proposes with `Peek` and commits with `Acquire` only after the handshake succeeds, so a failed dial never fences a healthy peer.

Each side verifies the certificate of the side it accepts. In the `endpoint-initiated` direction the Server validates the Endpoint identity. In the `server-initiated` direction the Endpoint validates the Server identity, and the dialing Server validates the Endpoint certificate by name.

Server dial addresses are operator configuration, not protocol data: `AGENT_CLUSTER_ENDPOINT_DIAL_ADDRESSES` maps `endpoint_id=wss://address` pairs. A command can never choose where the Server connects.

Both components expose HTTP APIs. Server exposes the operator API and, in the `endpoint-initiated` direction, the Endpoint connection entry point. Endpoint exposes the same local application services over a loopback-only API for health, inventory, command status and diagnostics. Remote access to the Endpoint API is disabled by default. It is not a second bypass around the Endpoint access policy: any enabled direct write path requires the same caller token, the same journal and the same policy checks.

Transport bindings must preserve command IDs, target identity, revisions, the caller's
`endpoint-token` and result semantics.

Use HTTP requests for queries and command admission, SSE for TUI state/command updates, and a separate demand-driven output subscription for selected sessions. Large output must not block command/heartbeat delivery; use bounded priority queues and independent output flow control, or a separate output connection if required by load testing.

## Authority and truth

- Endpoint is authoritative for observations and command admission/execution at that endpoint.
- Provider runtime is authoritative for agent behavior. Endpoint cannot infer task success from its own successful CLI invocation.
- Server holds a last-observed inventory projection, not live truth during disconnection.
- Server is authoritative for caller identity and cluster admission, and for routing a request to the
  addressed Endpoint. It is not authoritative for whether an operation is permitted: that decision
  belongs to the Endpoint that would perform the work.
- An unavailable observation is `unknown/stale`, not an empty inventory or a failed agent.
- TUI presents connection health, observation freshness, agent state and task state separately.

For MVP use one active Server with durable storage, not active-active routing. Reconnect and process generation rules still apply. HA later needs a shared command journal and an execution-authority lease/fencing design; adding a load balancer alone is insufficient.

## Storage and retention

Server must support SQLite and stores one latest Session inventory JSON field per Endpoint, not one row per Session. Each valid newer report atomically replaces that field in the database immediately, without a deferred batch flush. No Session snapshot history, per-session upserts, incremental resource event log or historical removal tracking is required. Separate endpoint metadata and command intents/results/audit retain their own purposes. Endpoint privately stores stable identity, resource/provider mapping, current inventory revision and command deduplication journal. Provider output stays provider-owned by default; fetch bounded snapshots on demand rather than mirroring all stdout centrally.

Recommended implementation starting point: Go services and TUI, OpenAPI-defined HTTP contracts, JSON WebSocket frames, required SQLite support as the initial deployment. Go and transport choices remain recommendations; PostgreSQL is not an MVP requirement. Use portable libraries and application-level serialization for complex values. Embed migrations in binaries. Do not require Redis, Kafka or Kubernetes for MVP.

Explicit provisional limits: terminal command results and audit summaries retained for 30 days, command notification replay, if retained, for 24 hours subject to byte quota (never containing old Session inventories), deduplication tombstones for at least the command validity window plus maximum replay/reconnect allowance. Output caches default to 15 minutes and a per-endpoint byte quota. Configure record, byte and age bounds; reject admission or resynchronize rather than silently evicting active commands. Never purge active or unresolved execution records solely because they are old. Provide operator inspection and explicit archive/reconciliation for unresolved records.

Unregistering an Endpoint revokes its credential and removes or clears its single current Session inventory according to explicit unregister policy, without creating inventory history; it never deletes provider workspaces or terminates agents. Each component cleans only resources it owns. Cleanup events are audited.

## Session reporting and latest-only persistence

Human direction:

> 使用单独的命令吧，如：agent-cluster-server，agent-cluster-endpoint, agent-cluster-tui，不要子命令的形式了。
> endpoint应该需要定期上报session信息（对应topsailai的workspace 子命令的那个列表信息，类似如此），上报这些信息到server。
> server应该处置这些信息，要支持sqlite，保存到数据库中，并且能够实时更新数据库。server端也要能主动去拉取endpoint的信息。
> 这些session信息保存到一个字段就行，不用拆开去存，这样能保证每次更新后，表里面都是最新的数据，就不需要复杂的历史数据管理。

Naming note: the third command was later implemented as `agent-cluster-cli`, because it serves both the interactive REPL/TUI and the noninteractive subcommands. The human quote above is preserved verbatim; the implemented name is `agent-cluster-cli`.

Endpoint periodically collects and reports a complete current inventory, initially proposing a configurable 10-second interval with jitter. It reports after reconnect and can refresh after lifecycle changes. This concerns Session list information, NOT stdout polling. Endpoint merges its private adapter observations into one standard inventory document containing opaque resource IDs, normalized Agent/Session/Task summaries and aggregate collection health. The document may include standard adapter identity/type/version/health summaries and Session-to-adapter associations. These are descriptive report data, not provider-specific execution schemas or Server routing instructions. For TopsailAI the source is `topsailai workspace list --json --local`; do not store raw local paths or confidential metadata indiscriminately.

Server also initiates fresh collection via a correlated refresh request over the active authenticated Endpoint channel. This is an active pull even when Endpoint initiated the network connection. No public inbound port is required; an optional direct authenticated Endpoint HTTP route can use the same collector. Operator refresh and a configurable Server-side reconciliation scheduler use this path. Push and pull feed the same validation/version-check/database transaction. Merely returning a cached list must be labelled cached and must not satisfy a requested fresh collection.

Use a latest-only `endpoint_session_state` table with one row per Endpoint. `sessions_json` (TEXT) holds the entire current standard Session inventory document; no Session fields are split into SQL columns. Supporting row metadata: `endpoint_id` (primary key), `schema_version`, `source_generation`, `snapshot_revision`, `observed_at_ms`, `received_at_ms`, `create_at_ms`, `update_at_ms`. Timestamps and revisions use BIGINT-compatible integer types; `schema_version` and `source_generation` are TEXT, and the implemented `source_generation` value is the fixed marker `endpoint-local` rather than a Server-issued generation. Endpoint reachability and last collection error live in endpoint metadata, not fabricated Session entries. Validate JSON and schema in the application; do not require vendor JSON query functions.

Latest means the latest successfully accepted composite report, not that every source is freshly observed. Each Adapter collects independently with bounded time/output/concurrency. Successful results replace only that Adapter section in the Endpoint composite; failed sections retain last-known returned data with stale/error metadata. Never block healthy Adapter publication on another Adapter. Endpoint then publishes one structurally complete JSON document, and Server still atomically replaces one field without merging Adapter data. If a source has never succeeded its data is unknown, not an empty list. A successful empty source result clears only that source section. Endpoint obtains collection scope and facts exclusively from Adapter CLI results and formats them; it does not independently scan Agent processes/files or impose a running-only/resumable-only selection policy.

Every successful accepted update performs one transactional conditional INSERT/UPDATE, including revision and timestamps. Serialize/compare updates per Endpoint; newer collection revisions win regardless of push/pull arrival order. Acknowledge only after commit; publish a lightweight inventory-changed notification only after commit. On storage failure return failure, retain the old document and allow a retry of the same revision. Restart restores the latest row directly. There is no Session-history cleanup job or restoration of old snapshots. SQLite may retain physical old pages/WAL until checkpoint/reuse; latest-only logical storage is not a promise of forensic secure erasure.

## Security baseline

- Enroll an Endpoint with a one-time short-lived credential; issue an endpoint-bound client certificate. Authenticate persistent channels with mTLS; require TLS for remote APIs.
- Use caller authentication to admit a caller to the cluster, and nothing more. The Server verifies the `server-token`, that the addressed Endpoint exists, and that a live channel reaches it; it then forwards the request unchanged. It does not authorize operations, so it can neither grant nor revoke what an Endpoint serves.
- A CLI presents two independent credentials: the `server-token`, verified by the Server and terminating there, and the `endpoint-token`, verified by the Endpoint and forwarded opaquely by the Server. A request without an `endpoint-token` is refused by the Endpoint rather than falling back to a default policy.
- The CLI resolves each Endpoint's token from its own configuration file, never from the Server. Distribution stays local because a Server-side path would make the Server a token holder, and a holder can hand tokens out. The map lives in the same per-user file that already carries the Server URL and the `server-token`, so one precedence rule and one parser cover every setting. A CLI with no entry for the addressed Endpoint refuses locally as a configuration error instead of sending an unauthenticated request.
- Revocation closes existing sessions and invalidates queued dispatch; certificates rotate without changing endpoint identity.
- Never expose an arbitrary remote shell, executable path, environment override, filesystem path, socket path or unvalidated raw provider action in the generic API. The only command execution surface is the standard `command.exec` operation, which runs one argv array matched against an Endpoint-global allowlist in a session working directory with a minimal environment, bounded lifetime and bounded output. It is not a shell: no command string is parsed, no shell is invoked, and arguments are confined to the resolved directory.
- Provider binaries and binding configuration are trusted local admin configuration. Execute argv directly without a shell, under a least-privilege account; bound child lifetime and output and clean up exact owned processes.
- Journal/audit references and payload hashes, not full prompts, secrets or complete stdout by default. Restrict output access, encrypt stored sensitive payloads and use bounded retention.
- Treat stdout and provider metadata as untrusted: strip terminal control sequences for TUI rendering, cap frame/text size and nesting, and redact sensitive local metadata from fleet listings.
- Existing CLI PID/liveness checks are not authenticated process identity. MVP assumes trusted local per-user provider storage; do not claim protection against a hostile local user or compromised Endpoint.
- An Endpoint decides which cluster operations it serves, through one local policy directory. Each file describes exactly one token and is selected by the `endpoint-token` that caller presents, so the policy is per-token rather than per-Endpoint. The token is the only dimension that can select a policy: a caller Endpoint ID is asserted rather than proven, and a policy keyed on it would let any caller claim the most permissive identity. A token file declares the `endpoints` that accept it, the `scopes` it is granted and the `permissions` it is granted; `scopes` and `permissions` are additive, while `endpoints` is the only narrowing declaration and is verifiable because the Endpoint knows its own identity. One file set therefore serves the whole fleet. The directory defaults to permissive when absent, refuses a token with no matching file, and can deny one token explicitly. Tokens are provisioned by the operator through a maintenance script rather than issued by the Server, because a Server holding the token table would become a second authorizer. A refused operation returns the shared `policy_denied` code with the operation named, the scope vocabulary stays closed so an existing policy file never fails to load, and a `permissions` entry naming an operation the Endpoint does not serve is accepted with a load warning so one file set serves a version-skewed fleet. See `docs/agent-cluster-endpoint-access-policy.md`.

## Scale assumptions and cost model

Provisional target: 100 Endpoints, 20 active sessions per Endpoint, 100,000 retained historical resource summaries, 10 concurrent operators and 10 watched output panels cluster-wide. Validate and amend these assumptions before implementation approval.

At a 10-second inventory refresh, one batched provider discovery per binding per cycle is approximately 10 CLI discovery launches/second across a fleet with one binding per Endpoint. Never run a full discovery separately for every session or every operator. Local provider discovery may still scan retained history: current CLI pagination/incremental discovery is not verified and may be the limiting cost. Measure it at representative history size before promising this target; do not compensate with ever faster polling.

A 10-second heartbeat yields approximately 10 fleet heartbeats/second. MVP does not periodically refresh stdout snapshots, so no recurring stdout polling workload is budgeted. Explicit output requests remain bounded and shared where appropriate. Continuous output follow is implemented as an explicit operator action, so its workload is bounded by operator behaviour rather than by a timer: the Endpoint admits at most 8 concurrent follows and rejects an excess request instead of queueing it, and the Server bounds pending follows per connection. A follow therefore cannot multiply discovery cost, and it cannot starve commands, heartbeats or inventory reports on the shared channel. Inventory refresh is independent of stdout follow. Use bounded worker pools, jitter, cache, adaptive backoff and per-binding quotas.

Proposed initial budgets: cached first TUI page under 1 second, command durable admission p95 under 500 ms, command dispatch p95 under 2 seconds on a healthy LAN excluding provider execution, inventory freshness under 15 seconds in steady state. Endpoint queries use deterministic pagination and indexed endpoint/update-time filters. Session filtering reads the current JSON documents in the application, with bounded endpoint selection and result budgets; do not promise indexed global Session-state queries without a measured cost model. Cross-request pagination that observes changed revisions returns resync_required rather than retaining old snapshots; no live fleet fan-out on first render. Confirm with representative load evidence, not small fixtures.

## Discussion decisions

Recommended defaults: Endpoint-initiated transport; capability-based adapters; one active Server; required start/resume/stop lifecycle management; machine-scoped Endpoint; explicit delivery uncertainty; no periodic stdout snapshot refresh; no arbitrary remote shell. Command execution is limited to the standard `command.exec` operation: one argv array matched against an Endpoint-global allowlist, confined to the session working directory, with a minimal environment, bounded lifetime and bounded output. Provider control is limited to the advertised `ctl.<action>` family, each with a fixed payload schema and an explicit permission scope.

Open decisions and rollout acceptance are in the Adapter document. These drafts require human discussion before implementation. No agent lifecycle behavior, public interface or deployment has been changed.

## Confirmed controller and reporting model

Human clarification:

> 保持数据库简单，但不要把所有 Adapter 的可用性绑在一起。-> 同意
> endpoint和agent没有必然关系，endpoint只是发送指令而已！endpoint和agent是各自独立的，endpoint只是个控制器，给agent发指令、发消息的控制器而已。
> endpoint 怎么采集，采集哪些信息，全靠对应的 adapter 的命令行返回的结果，它不关心，它只做采集的动作、格式化数据结构的行为。
> 同意 “不引入 Session 历史或复杂消息系统”

Controller responsibilities are CLI invocation, standard formatting, independent collection scheduling, transport, policy and command delivery evidence. Provider-specific discovery/scope and Agent process management belong to Adapter CLI/runtime. Endpoint owns only its bounded invocation helpers and transport resources, never the Agents reached through those tools. Local last-known per-Adapter cache is a latest-value cache, not Session history; on cache loss report unknown, not fabricated emptiness.

## Implemented container deployment

The Server also runs as a container image built from `docker/Dockerfile`. This section describes the
implemented image, not a proposal. The image is a deployment form of the Server only; an Endpoint runs
as a node process installed by the Debian package or the bundle, never inside this image.

This image is not the only container in a real deployment. An Endpoint may itself run inside a
container, and the `ai-dev` Endpoint does. That is a supported deployment, but it carries the lifecycle
risk described in the component boundaries section: recreating that container kills every Agent it
launched, because the container is their shared lifecycle boundary. The image below is therefore a
statement about the Server only, and it says nothing about where an Endpoint or its Agents run.

The image uses the same `/opt/agent-cluster` tree as the package, and every mount point is the same
path on both sides, so a host path and a container path are never two names for one file:

| Path | Package | Image | Note |
|---|---|---|---|
| `/opt/agent-cluster/bin/` | role binaries | `agent-cluster-server` | entry point |
| `/opt/agent-cluster/conf/` | conffiles | absent | the image is configured by environment variables |
| `/opt/agent-cluster/certs/` | TLS material | mounted read-only | `ca.pem`, `server.pem`, `server-key.pem` |
| `/opt/agent-cluster/data/` | SQLite state | mounted read-write | `server.sqlite` |
| `/opt/agent-cluster/logs/` | rotated log files | present, unused | logs go to stderr |
| `/opt/agent-cluster/run/` | pid file | absent | the container runtime supervises the process |

`conf/` and `run/` are deliberately absent rather than empty. `internal/config/config.go` reads only
the process environment and never a `node.conf`, and the container runtime owns process supervision,
so creating those directories would suggest a conffile or a pid file is honoured inside the container
when it is not. The image therefore differs from a package only where the difference is real.

The image fixes the database path and the three TLS paths in `ENV`, so a run command supplies only
the token and the mounts. `AGENT_CLUSTER_LOG_OUTPUT` is `stderr`, because a container should not own a
log file: the Docker log driver rotates it, and the rotation settings in
`docs/Environment_Variables.md` do not apply.

The container runs as the unprivileged uid `10001` and listens on every interface. A loopback-only
bind would make the published port unreachable from other containers, which is the point of
publishing it: endpoints dial a bridge gateway address and never depend on the container's own IP,
which changes on every recreate.

The state directory is shared with the host Endpoint, so ownership is granted per entry rather than
recursively. The directory and `server.sqlite` belong to uid `10001`, while `endpoint.sqlite` keeps
its own owner, so the container cannot read it. A recursive `chown` would hand the endpoint database
to the container and weaken the isolation that keeps it unreadable there. SQLite reports a permission
failure as `out of memory (14)`, which hides the real cause.

The runtime stage installs no packages, because this host's resolver forwards
`dl-cdn.alpinelinux.org` to unreachable public resolvers and `apk add` fails with a DNS lookup error.
Busybox already provides the account and probe tools, and the CA bundle is copied from the build
stage, so the image also builds on an air-gapped host.

Recreating the Server container resets the in-memory connection generation, so every Endpoint must
restart before it can reconnect. That is the same fencing behaviour described in the transport
section, not a container-specific defect.
