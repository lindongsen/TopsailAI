---
maintainer: AI
author: DawsonLin
status: discussion-draft
created: 2026-10-27
---

# Abstract Resources and Protocol

## Resource model

| Resource | Meaning | Key fields |
|---|---|---|
| Endpoint | One machine with one registered OS management daemon and multiple adapters | endpoint_id, display_name, labels, instance_id, connection_state, observed_at_ms |
| LaunchProfile | Endpoint-published standard execution preset | launch_profile_id, display_name, profile_revision, permitted standard inputs |
| Agent | Provider runtime identity or logical worker | agent_id, generation, state, state_reason |
| Session | A conversation/execution context | session_id, agent_id, generation, state, observed_at_ms |
| Task | Optional unit of provider work | task_id, session_id nullable, parent_task_id nullable, state, progress nullable |
| Command | One admitted user intent | command_id, target, operation, payload_schema_version, deadline_at_ms, state |
| Observation | One typed state change or snapshot fact | endpoint_epoch, sequence, resource_id, resource_revision, observed_at_ms |
| OutputSource | Optional stdout/stderr/provider event source | source_id, target, kind, mode, cursor_support, retention_hint |

Agent, Session and Task are distinct: one agent may have several sessions; a session may have several tasks; a provider may have no task concept. Report an absent capability rather than inventing tasks. TopsailAI may need a synthetic logical worker identity per runtime binding/session; its exact mapping must be validated against real inventory before freezing the schema.

Use stable opaque cluster resource IDs scoped by Endpoint, privately mapped by Endpoint to adapter/provider IDs. Public IDs must not encode adapter routing semantics. Never use list row numbers, display names or bare PIDs as routing identities. Persist provider mapping; do not mint new IDs on each discovery. A PID can be a private locator hint but cannot be the sole generation proof. Provider ID reuse creates a new generation.

Separate endpoint connection state (`online`, `suspect`, `offline`) from observed agent state (`running`, `idle`, `waiting_input`, `stopped`, `unknown`) and task state (`pending`, `running`, `succeeded`, `failed`, `cancelled`, `unknown`). Map only states supported by actual evidence; publish only a standard bounded reason code/message, keeping provider-specific diagnostics local. Store observation time and Server receive time separately. Creation/update timestamps are UTC epoch milliseconds; durations/deadlines are not inferred from timestamps alone.

## Capability contract

Endpoint publishes standard versioned capabilities for itself, abstract resources and LaunchProfiles. Private adapter capabilities never appear on the wire. Minimum admission requirements are health and bounded discovery of at least one supported resource kind. The MVP platform must implement agent start/resume/stop. Endpoint reports precise standard resource/profile support; an unsupported lifecycle operation is an explicit integration gap, not a silent substitute. Task and output modes remain capability-dependent.

Each advertised operation includes a stable semantic name/version, target kinds, request and result JSON Schemas, payload limits, safety class, required permissions, execution/acknowledgement meaning, deduplication scope and platform prerequisites. Capability revisions are bound to admitted commands; a changed descriptor triggers revalidation, not silent reinterpretation.

Suggested semantic operations:

- `message.send`: submit literal user input; does not imply consumption.
- `context.inject`: queue side-context; distinct from normal user input.
- `execution.interrupt`: only advertise when the exact interrupt semantics are defined; there is no universal safe interrupt mapping.
- `session.read_messages`: read permitted conversation context.
- `runtime.health`: control-channel health, not model progress.
- `agent.start`, `agent.resume`, `agent.stop`: required MVP lifecycle operations, with standard agent/session linkage and execution-generation evidence.
- `output.snapshot`, `output.follow`: independent capabilities; the former never implies the latter.

Only operations and input/result fields defined by the negotiated standard API are exposed. No provider namespaces, raw control actions, adapter routing selectors or arbitrary provider execution schemas are accepted in commands. Inventory may carry adapter IDs and standard descriptive summaries as report data. A new common semantic operation requires an explicit versioned protocol amendment; provider-only controls remain local to Endpoint. Server validates standard schemas, not dynamically supplied provider instructions.

## Required agent lifecycle semantics

- `agent.start` targets Endpoint and opaque launch_profile_id/profile_revision. Endpoint validates the standard intent and invokes its configured Adapter CLI start operation; the CLI/runtime controls how the independent Agent starts. No arbitrary shell or remote executable configuration is accepted.
- `agent.resume` invokes the Adapter CLI resume operation for an exact durable resource reference. Do not emulate unsupported resume by creating a fresh conversation or by implementing an Endpoint process supervisor.
- `agent.stop` invokes the Adapter CLI stop operation for the selected target. Distinguish it from turn interruption. Endpoint does not directly kill or adopt Agent processes; any graceful/force policy and termination evidence come from the reviewed CLI contract. Report unsupported or unknown when that evidence is unavailable.
- Endpoint restart affects controller connections/collection, not Agent lifetime. It can rediscover returned resources through Adapter CLI and recover command delivery records; it never reparents, reattaches supervision or automatically restarts Agents.
- A crash after a CLI invocation can leave effects unknown. Query through Adapter CLI if a correlated query exists; otherwise report uncertainty without replaying side effects. The journal tracks controller intent/delivery, not ownership of Agent processes.
- Freeze public resource/profile revision and command identity. Endpoint-local mapping selects the CLI; Server retains only standard API semantics.

## Endpoint-private Adapter service boundary

These methods exist only inside Endpoint; Server cannot call them or reference binding/provider parameters. Conceptual language-neutral methods, not implementation source:

| Method | Contract |
|---|---|
| Describe(binding) | Return versioned capabilities, constraints and health prerequisites |
| Discover(binding, page_or_checkpoint, budget) | Return bounded resources and explicit completeness/revision evidence |
| Inspect(target, budget) | Revalidate exact provider mapping and target generation |
| Execute(command, frozen_target, budget) | Perform one allowed intent and report the actual acknowledgement boundary |
| QueryCommand(provider_command_ref, budget) | Optional provider reconciliation; unsupported is not failure |
| ReadOutput(target, source, cursor_or_tail, budget) | Return snapshot or cursor-based data with truncation/gap flags |
| Watch(binding, checkpoint, budget) | Optional provider event subscription |
| Close() | Release controller CLI invocation helpers, subscriptions and handles; never stop independent Agents |

Endpoint services, not Adapter, own durable command IDs, policy, audit and network protocol. Methods receive explicit context, cancellation and budgets. Configuration is read at process startup and passed into bindings. Adapter errors use normalized categories and bounded redacted diagnostics; unsupported semantics must not be emulated by unrelated destructive actions.

## Proposed HTTP surfaces

All paths below are proposed, not existing APIs. JSON responses use a common envelope: code, message, data, request_id, timestamp. Errors preserve stable machine codes; HTTP statuses are meaningful. Paginated responses carry next_cursor, snapshot_revision and has_more; sorting is deterministic with ID as a tie-breaker.

| API | Purpose |
|---|---|
| GET /api/v1/endpoints | Filtered, paginated Endpoint summaries and freshness |
| GET /api/v1/endpoints/{endpoint_id} | Endpoint aggregate health and last synchronization |
| GET /api/v1/endpoints/{endpoint_id}/capabilities | Standard Endpoint/resource operation descriptors |
| GET /api/v1/endpoints/{endpoint_id}/launch-profiles | Standard launch preset IDs, revisions and permitted standard inputs |
| PUT /api/v1/endpoints/{endpoint_id}/session-state | Authenticated Endpoint full report; commit latest JSON before acknowledgement |
| GET /api/v1/endpoints/{endpoint_id}/session-state | Read the persisted latest document with freshness/revision |
| POST /api/v1/endpoints/{endpoint_id}/session-state/refresh | Server initiates fresh collection; correlated response passes through the same persistence path |
| GET /api/v1/agents | Filter by endpoint, labels, standard state |
| GET /api/v1/sessions | Standard sessions with freshness, without provider filters |
| GET /api/v1/tasks | Optional task projection, not inferred work completion |
| POST /api/v1/commands | Admit one target-bound, capability-validated intent |
| GET /api/v1/commands/{command_id} | Durable delivery and result evidence |
| GET /api/v1/output/snapshot | Bounded output for an exact authorized source |
| GET /api/v1/events | Authorized SSE updates with replay ID |
| POST /api/v1/output/subscriptions | Admit a bounded demand-driven output subscription |
| DELETE /api/v1/output/subscriptions/{id} | Release only that owned subscription |

Enrollment, credential rotation and revocation are administrative operations specified in a later security contract. Endpoint local API exposes health/readiness, standard resources, command status and locally authorized command admission through the same internal services. Route naming can mirror the Server API under a local scope; exact local administration endpoints remain to be specified.

A command request contains client-generated command_id, endpoint_id, target kind/ID/generation (or launch_profile_id/profile_revision for start), operation/version, capability_revision, typed payload, expiry and optional expected_resource_revision. Server derives the operator identity and permissions from authentication, never from client-provided authority claims. HTTP 202 means Server admission only. A repeated ID with identical canonical intent returns its prior state; changed intent returns conflict. Owner/scope checks precede duplicate-result disclosure.

SSE uses resource changes, command updates and freshness events. Output subscriptions return an authorized stream reference. MVP does not periodically refresh stdout snapshots. Explicit snapshot requests are one-shot reads; continuous subscriptions, if approved and supported, must provide true stream semantics rather than timer-driven snapshots.

## Command lifecycle and uncertain effects

Track lifecycle separately from provider evidence:

```text
Server admitted -> dispatched -> Endpoint admitted -> executing -> finished
                 -> expired/rejected/cancelled_before_execution
```

Evidence fields include delivery boundary, effect certainty (`not_applied`, `acknowledged`, `unknown`), provider outcome (`succeeded`, `failed`, `not_reported`), and response details. Finished execution of a CLI call does not mean successful agent work. An acknowledged FIFO write can finish the transport command while provider outcome remains not_reported. An execution timeout may have unknown effects.

End-to-end delivery is at-least-once with bounded deduplication, NOT exactly-once execution:

- Server persists intent before replying 202. Endpoint persists admitted intent before invoking the provider.
- IDs are bound to authenticated issuer, scope, canonical payload hash and frozen target. Deduplicate repeated transport frames on both sides.
- Endpoint crash after provider invocation but before result persistence is an uncertain boundary. Reconcile through QueryCommand if the provider supports a correlated ID; otherwise expose unknown and require an explicit new operator decision. Never replay side effects merely because no result was stored.
- Reconnect resends retained intent with the same ID, never a new ID. Endpoint journal state decides whether to return the retained result, reconcile, or report unknown, not blindly execute again.
- A duplicate after dedup history expiry is not safe to execute. Commands have immutable expiry and an endpoint-bound admission token/validity window; reject expired or unverifiable replays and require a new intent ID.
- In-flight cancellation is capability-specific. A Server cancellation before Endpoint acceptance prevents dispatch. After acceptance, a cancellation request cannot claim that provider effects stopped.

Default offline policy: reject new mutating commands as endpoint_unavailable. A connected-to-disconnected race is reconciled by command status, not silently retried. Optional future offline queues require explicit opt-in, short TTL, target generation binding and revalidation. Never execute a stale message against a replacement session.

Endpoint reports the instance/epoch that admitted a command. On reconnect the Server grants one active connection generation; old channels are fenced. Endpoint accepts commands only on its current authorized connection and checks the generation immediately before provider invocation. Local daemon singleton locking prevents two local executors sharing identity/journal. This fences stale management dispatch, not an already-started external provider operation. Journal recovery reconciles that boundary rather than asserting cancellation.

Use absolute UTC expiry for interchange with a specified maximum clock skew, and monotonic remaining budgets for local operations. Fail closed when clock confidence is insufficient for mutating commands. Clock skew tolerance, maximum command validity and dedup retention must be specified together before implementation.

## Inventory and event synchronization

WebSocket handshake exchanges protocol major/minor, endpoint identity, instance_id, active connection generation and standard Endpoint capability revision. Reject incompatible major versions and negotiate optional minor features. Session synchronization uses full latest snapshots, not a persistent per-session event history.

The Server allocates a monotonically increasing source_generation on each accepted Endpoint connection, durably associated with endpoint identity. Endpoint serializes collection/publication across push and pull and increments snapshot_revision within that generation. Retries reuse the original revision and immutable document. Frames carry source_generation, snapshot_revision, observed_at_ms, schema_version, report_complete=true, collection_status (ok/degraded/failed) and the inventory document. Reject stale channels, lower generations/revisions and mismatched identities. An equal revision with identical content is an idempotent acknowledgement; different content is a conflict. Timestamps are for freshness, not ordering. A new generation publishes a newly assembled report, preserving per-source observation times and marking any retained data stale. Cached sections never become fresh merely because the report generation changed.

Proposed periodic report interval is 10 seconds with jitter, independently configurable from heartbeat. Server active pull sends `inventory.refresh` with request_id, standard inventory scope (MVP: the complete Endpoint inventory), deadline and fresh=true on the authorized connection. Endpoint coalesces concurrent refresh requests into one new/in-flight collection and serializes cycles so an older scan cannot publish after a newer scan. A pull result includes its request_id and accepted generation/revision. A refresh API response confirms only that a newly attempted collection report committed, and separately reports collection_status and per-source freshness/errors; it must not label degraded cached sections freshly collected. A strict all-fresh caller receives an explicit partial-collection result if any source failed; timeout/disconnection/database failure returns an explicit error with last-known revision available separately. A late valid result may still update the row, but does not retroactively turn a timed-out request into success. Bound per-endpoint refresh frequency and scheduler concurrency to avoid discovery amplification.

Endpoint independently invokes each configured Adapter CLI and assembles a complete report of successes, failures and unknown sources; one failed source does not block successful sources. Server may display/filter the reported adapter summaries, but does not independently discover adapters, interpret provider health semantics or decide collection completeness from private adapter logic. Both periodic push and active pull validate completeness, schema, configured byte/count/depth limits and authenticated Endpoint identity and standard resource ownership before an atomic conditional replacement of `endpoint_session_state.sessions_json`. Validate/reassemble any bounded transport chunks in memory under one snapshot ID; no partial database publication. Malformed/truncated/oversized report documents fail visibly and preserve the previous database field. Individual source collection failures instead produce a valid degraded report with stale last-known sections; report completeness is not all-source freshness. This captures a completed provider scan, not a transactional provider-wide instant.

Server persistence is the read authority for displayed inventory. GET Session/Agent/Task projections decode/filter this single latest document; they do not imply separate resource tables. On commit emit only endpoint_id and current revision in an inventory-changed notification. TUI reloads the current document, so missed/coalesced notifications need no old Session events. On disconnect/reconnect it reloads latest state; command notification recovery stays independent. Do not save previous JSON payloads in SSE replay or audit logs.

Initial reachability policy remains heartbeat every 10 seconds, suspect after 30 seconds, offline after 60 seconds. Collection errors update health separately and preserve the latest valid inventory. A successful empty inventory removes old entries by whole-field replacement, without per-session deletion tracking. Endpoint disconnection never synthesizes task failure. Reconnect requests a new complete report rather than inventory-history replay.

SQLite serializes write transactions; use bounded transaction lengths, a bounded busy retry policy and explicit database-error responses. Configure WAL/checkpoint and durability settings deliberately with the SQLite library; publish commit evidence rather than promising hard real-time I/O. The initial single active Server owns the database. Measure JSON serialization/whole-document replacement costs, collection duration, commit latency, database/WAL size and bounded query parsing under representative retained provider history. No per-Session SQL index or database-specific JSON features are needed for MVP.

## Output and backpressure

Real follow support requires an opaque cursor bound to source identity/generation plus an offset/sequence, rotation detection and bounded retention. Cursor expiry returns an explicit gap and recovery option. Do not derive a reliable cursor from a tail snapshot or deduplicate identical text lines: repeated lines can be legitimate.

Snapshot-only providers return snapshot_id, observation time, returned content and partial/truncation evidence. The TUI replaces the panel snapshot rather than appending inferred new lines. MVP performs no periodic stdout snapshot refresh. One-shot reads show their observation time; they promise neither complete history nor sub-second follow.

Bound frame bytes, queues, output rate, subscriptions per operator and per Endpoint, CLI concurrency and snapshot size. Reserve transport capacity for heartbeat/control. Backpressure on output drops or pauses only with explicit gap/status events; control admission fails visibly when full. Slow consumers expire their subscriptions and can re-query state. Secrets and escape sequences are never rendered as trusted terminal commands.

## Descriptive adapter report metadata

Standard inventory includes adapters summaries and Session adapter_id associations as defined in `docs/agent-cluster-database.md`. Server persists/returns this data inside sessions_json and may perform generic display/filtering/structural validation, but never interprets a provider_type to select code, execute controls or route a command. Adapter management and execution remain Endpoint-local. This corrects the earlier over-strict prohibition on all adapter identifiers in reports.

## Latest-only notifications without a message system

No Session event history, durable message broker or notification outbox is required. Inventory-change notifications are lightweight invalidations emitted after commit, not authoritative data. TUI reloads latest state on initial connection/reconnection. A bounded Server-instance notification sequence detects gaps/overflow and requests full latest-state reload; a periodic lightweight revision manifest on the state channel reconciles a missed final notification while connected, including a commit-to-notify failure. The manifest contains only current endpoint IDs/revisions, not old Session payloads or stdout. Subscribe-before-read plus revision comparison closes initial-load races. Server restart changes the stream instance and forces resync. Command status is recoverable through its durable query API independently of inventory notifications.

## Implemented adapter project launch query

`GET /api/v1/launch-options?endpoint_id=ID` returns the live start-capable adapter handler catalog. Adding `adapter_id=ID` queries that handler's managed projects. This authenticated read-only API forwards through the existing endpoint channel, binds the response to the exact connection generation and request ID, and waits at most 10 seconds. At most 64 launch queries may be pending. Responses use the existing API envelope; `data` contains `handlers` (adapter_id, display_name, revision), `projects` (name, path) and optional error_code. A failed project query is not an empty successful list. The UI permits manual folder input on project-list failure, while execution still revalidates the adapter revision.

Interactive `start [endpoint]` queries the live catalog, auto-selects a sole handler, then asks for a project number or literal folder and a literal initial task. Empty input or cancel aborts before submission. Answers do not enter command history. The existing explicit profile syntax is retained for compatibility. No extra static profile configuration is needed: the legacy launch_profile_id identifies the selected configured adapter and profile_revision carries its live capability revision. Inventory adapter summaries are not execution authority.

The TopsailAI handler invokes `project list --json`, never scans project folders or edits project registration/settings. Project responses are rejected above 1000 records or 256 KiB after provider capture; the existing provider runner captures stdout before this check, so this is not a subprocess-memory bound. Tasks are carried in the immutable start payload as `task`, validated as nonblank UTF-8 without NUL and at most 8192 bytes, and forwarded as one literal argv value. The interactive wizard accepts one input line; JSON payload callers may provide multiline tasks. Background submission is not readiness or task completion. Provider-side argv handling and real model availability remain separate integration prerequisites.
