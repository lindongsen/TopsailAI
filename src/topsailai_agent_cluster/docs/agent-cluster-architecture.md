---
maintainer: AI
author: DawsonLin
status: discussion-draft
created: 2026-10-27
---

# Unified Agent Management Architecture

## Document index

- `docs/agent-cluster-architecture.md`: goals, boundaries, topology, storage, security and design decisions; discussion draft.
- `docs/agent-cluster-protocol.md`: abstract resources, capability negotiation, APIs, commands, synchronization and recovery; discussion draft.
- `docs/agent-cluster-adapters.md`: Endpoint-private TopsailAI mapping and integration questions; discussion draft.
- `docs/agent-cluster-database.md`: three Server business tables, constraints, transactions and retention; discussion draft.

These design documents are not implemented features or an approved final specification. Naming, machine-level Endpoint scope, required lifecycle support and the absence of periodic stdout snapshot refresh are human-confirmed decisions; other proposals remain under discussion. Implementation and verification planning is tracked separately in `.task/plan_20261027T153140_agent-cluster-delivery.md` (project-relative path).

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

Start/resume/stop are mandatory MVP platform capabilities. A provider that lacks a safe implementation must report the gap, but the first-release TopsailAI lifecycle gap cannot be deferred as an optional feature. No periodic stdout snapshot refresh is required; this does not decide between explicit reads and continuous subscriptions. Design documents live in `docs/`; planning, execution checklists and evidence remain in `.task/`.

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

## Component boundaries

| Component | Owns | Must not own |
|---|---|---|
| Server | Endpoint registry, standard capabilities/resources, authorization, latest inventory, standard command routing, audit | Adapter registry/configuration/selection or provider-specific interpretation of reported metadata, provider flags, local paths, PID selection, agent execution |
| Endpoint | Local inventory authority, provider bindings, execution journal, local policy, bounded collection, stream relay | Cross-endpoint scheduling or assumptions about Server UI |
| Adapter | Provider discovery, identity mapping, semantic translation, supported operations, output normalization | Server credentials, network routing, cluster RBAC |
| CLI/TUI | Selection, filtering, status display, confirmation, user intent | Backend polling logic or provider-specific shell commands |

An Endpoint represents one machine: one Endpoint daemon runs in its operating system and hosts multiple adapters/provider bindings for different agents. Do not deploy one Endpoint per account or per adapter. Two bindings of the same provider may use different locally approved roots or execution identities. Cross-account execution requires an explicit least-privilege local policy, not unrestricted impersonation. A binding has a stable ID. A single Server manages many machine Endpoints.

MVP supports start/resume/stop requests by invoking the corresponding Adapter CLI, alongside collecting its returned inventory. Endpoint and Agent are independent: Endpoint is a controller, not an Agent parent process, supervisor or lifecycle owner. Endpoint startup/shutdown/restart does not start, stop, adopt or restart Agents. The provider CLI/runtime is responsible for actual Agent launch, persistence and termination. Endpoint reports only returned evidence; command delivery or CLI exit alone cannot prove Agent readiness or task completion.

## Transport and connectivity

Recommended default: Endpoint initiates an authenticated TLS WebSocket connection to Server. Registration, heartbeat, bounded inventory synchronization, commands and small event frames share a versioned channel. This works behind NAT without exposing an inbound Endpoint port.

Both components expose HTTP APIs. Server exposes the operator API and the Endpoint connection entry point. Endpoint exposes the same local application services over a loopback-only API for health, inventory, command status and diagnostics. Remote access to the Endpoint API is disabled by default. It is not a second bypass around Server authorization: any enabled direct write path requires explicit endpoint-local authorization and the same journal and policy checks.

Server-to-Endpoint HTTP push is an optional future transport for controlled networks, not an additional MVP requirement. Transport bindings must preserve command IDs, target identity, revisions, authorization context and result semantics.

Use HTTP requests for queries and command admission, SSE for TUI state/command updates, and a separate demand-driven output subscription for selected sessions. Large output must not block command/heartbeat delivery; use bounded priority queues and independent output flow control, or a separate output connection if required by load testing.

## Authority and truth

- Endpoint is authoritative for observations and command admission/execution at that endpoint.
- Provider runtime is authoritative for agent behavior. Endpoint cannot infer task success from its own successful CLI invocation.
- Server holds a last-observed inventory projection, not live truth during disconnection.
- Server is authoritative for operator identity, authorization and cluster admission.
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

Endpoint periodically collects and reports a complete current inventory, initially proposing a configurable 10-second interval with jitter. It reports after reconnect and can refresh after lifecycle changes. This concerns Session list information, NOT stdout polling. Endpoint merges its private adapter observations into one standard inventory document containing opaque resource IDs, normalized Agent/Session/Task summaries and aggregate collection health. The document may include standard adapter identity/type/version/health summaries and Session-to-adapter associations. These are descriptive report data, not provider-specific execution schemas or Server routing instructions. For TopsailAI the source is `topsailai workspace --format json`; do not store raw local paths or confidential metadata indiscriminately.

Server also initiates fresh collection via a correlated refresh request over the active authenticated Endpoint channel. This is an active pull even when Endpoint initiated the network connection. No public inbound port is required; an optional direct authenticated Endpoint HTTP route can use the same collector. Operator refresh and a configurable Server-side reconciliation scheduler use this path. Push and pull feed the same validation/version-check/database transaction. Merely returning a cached list must be labelled cached and must not satisfy a requested fresh collection.

Use a latest-only `endpoint_session_state` table with one row per Endpoint. `sessions_json` (TEXT) holds the entire current standard Session inventory document; no Session fields are split into SQL columns. Supporting row metadata: `endpoint_id` (primary key), `schema_version`, `source_generation`, `snapshot_revision`, `observed_at_ms`, `received_at_ms`, `create_at_ms`, `update_at_ms`. Timestamps and revisions use BIGINT-compatible integer types; `schema_version` and `source_generation` are TEXT, and the implemented `source_generation` value is the fixed marker `endpoint-local` rather than a Server-issued generation. Endpoint reachability and last collection error live in endpoint metadata, not fabricated Session entries. Validate JSON and schema in the application; do not require vendor JSON query functions.

Latest means the latest successfully accepted composite report, not that every source is freshly observed. Each Adapter collects independently with bounded time/output/concurrency. Successful results replace only that Adapter section in the Endpoint composite; failed sections retain last-known returned data with stale/error metadata. Never block healthy Adapter publication on another Adapter. Endpoint then publishes one structurally complete JSON document, and Server still atomically replaces one field without merging Adapter data. If a source has never succeeded its data is unknown, not an empty list. A successful empty source result clears only that source section. Endpoint obtains collection scope and facts exclusively from Adapter CLI results and formats them; it does not independently scan Agent processes/files or impose a running-only/resumable-only selection policy.

Every successful accepted update performs one transactional conditional INSERT/UPDATE, including revision and timestamps. Serialize/compare updates per Endpoint; newer collection revisions win regardless of push/pull arrival order. Acknowledge only after commit; publish a lightweight inventory-changed notification only after commit. On storage failure return failure, retain the old document and allow a retry of the same revision. Restart restores the latest row directly. There is no Session-history cleanup job or restoration of old snapshots. SQLite may retain physical old pages/WAL until checkpoint/reuse; latest-only logical storage is not a promise of forensic secure erasure.

## Security baseline

- Enroll an Endpoint with a one-time short-lived credential; issue an endpoint-bound client certificate. Authenticate persistent channels with mTLS; require TLS for remote APIs.
- Use operator authentication plus scopes such as view, read_output, send_message, control and endpoint_admin. Authorize each target and operation at Server admission and revalidate current permission immediately before dispatch.
- Endpoint rechecks identity, validity, local provider/workspace allowlists, target generation and allowed operation. Server authorization does not override local safety policy.
- Revocation closes existing sessions and invalidates queued dispatch; certificates rotate without changing endpoint identity.
- Never expose an arbitrary remote shell, executable path, environment override, filesystem path, socket path or unvalidated raw provider action in the generic API. The only command execution surface is the standard `command.exec` operation, which runs one argv array matched against an Endpoint-global allowlist in a session working directory with a minimal environment, bounded lifetime and bounded output. It is not a shell: no command string is parsed, no shell is invoked, and arguments are confined to the resolved directory.
- Provider binaries and binding configuration are trusted local admin configuration. Execute argv directly without a shell, under a least-privilege account; bound child lifetime and output and clean up exact owned processes.
- Journal/audit references and payload hashes, not full prompts, secrets or complete stdout by default. Restrict output access, encrypt stored sensitive payloads and use bounded retention.
- Treat stdout and provider metadata as untrusted: strip terminal control sequences for TUI rendering, cap frame/text size and nesting, and redact sensitive local metadata from fleet listings.
- Existing CLI PID/liveness checks are not authenticated process identity. MVP assumes trusted local per-user provider storage; do not claim protection against a hostile local user or compromised Endpoint.

## Scale assumptions and cost model

Provisional target: 100 Endpoints, 20 active sessions per Endpoint, 100,000 retained historical resource summaries, 10 concurrent operators and 10 watched output panels cluster-wide. Validate and amend these assumptions before implementation approval.

At a 10-second inventory refresh, one batched provider discovery per binding per cycle is approximately 10 CLI discovery launches/second across a fleet with one binding per Endpoint. Never run a full discovery separately for every session or every operator. Local provider discovery may still scan retained history: current CLI pagination/incremental discovery is not verified and may be the limiting cost. Measure it at representative history size before promising this target; do not compensate with ever faster polling.

A 10-second heartbeat yields approximately 10 fleet heartbeats/second. MVP does not periodically refresh stdout snapshots, so no recurring stdout polling workload is budgeted. Explicit output requests remain bounded and shared where appropriate. Whether continuous output subscription is required remains open; if selected, measure rate, backpressure and concurrent watcher cost separately. Inventory refresh is independent of stdout refresh. Use bounded worker pools, jitter, cache, adaptive backoff and per-binding quotas.

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
