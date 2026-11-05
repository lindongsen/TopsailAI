---
maintainer: AI
author: DawsonLin
status: discussion-draft
---

# Server Database Design

## Scope and authority

SQLite is required. The first release uses three business tables: endpoints, endpoint_session_state and commands. This refines the previously accepted table proposal in accordance with the human requirement that Server never concerns itself with adapters. There is no endpoint_adapters table or dedicated adapter_id/binding_id/provider_type SQL column. Endpoint-reported adapter summaries and Session adapter_id associations are allowed inside sessions_json. Executable configuration, private state and provider-specific control schemas remain Endpoint-local.

Server handles only versioned standard API resources and operations. Session information remains one complete JSON field per Endpoint, with no Session/Task/history tables. Command records remain independent because losing execution evidence could cause duplicate starts/stops. Authentication secrets and schema migration bookkeeping require their own infrastructure design; these three tables are not a claim that all security storage is specified.

## Common types and constraints

Use TEXT for identifiers/JSON and BIGINT-compatible integers for UTC epoch-millisecond timestamps and generation/revision values. SQLite stores integer values in its INTEGER storage class; do not use auto-increment Session IDs. All fields are NOT NULL unless explicitly nullable. Every table has create_at_ms and update_at_ms. Required values are validated rather than filled with fictitious defaults. Enable SQLite foreign keys on each connection. JSON validation, canonicalization and typed schema checks happen in the application without vendor-specific JSON query functions.

The lists below are schema contracts, not executable migrations. Embed eventual migrations into the service binary. Use explicit transactions, short writer critical sections and bounded busy retries. Validate expensive JSON outside the write transaction, then recheck generation/revision and authority inside it. Read-compare-write must not race an Endpoint reconnect.

## endpoints

One registered machine, independent of IP, hostname or process lifetime.

| Field | Type / constraint | Meaning |
|---|---|---|
| endpoint_id | TEXT primary key | Stable registration identity |
| name | TEXT | Operator-facing display name |
| hostname | TEXT | Latest reported hostname, never an identity proof |
| platform_json | TEXT | Standard OS, architecture and Endpoint software version |
| labels_json | TEXT | Standard user labels, not adapter configuration |
| enabled | INTEGER, CHECK 0 or 1 | Whether registration is enabled |
| source_generation | BIGINT, nonnegative | Server-issued current connection fencing generation; initially zero |
| instance_id | TEXT nullable | Current/last Endpoint process instance |
| capabilities_json | TEXT nullable | Latest standard Endpoint/resource operation descriptors, no provider schemas |
| capability_revision | TEXT nullable | Matching standard capability revision |
| launch_profiles_json | TEXT nullable | Latest standard opaque launch preset IDs/revisions and permitted standard inputs |
| last_seen_at_ms | BIGINT nullable | Latest authenticated communication time |
| last_inventory_error_json | TEXT nullable | Standard code, redacted message and attempt time; no adapter identity/raw output |
| create_at_ms | BIGINT | Registration time |
| update_at_ms | BIGINT | Latest persisted change |

Capabilities/profile data are nullable before the first handshake and become stale across disconnection; they never independently authorize an action. Endpoint revalidates current profile/capability revisions and local policy before execution. Public presets describe what may be started, not how a private adapter implements it.

Compute connection state using the active authenticated channel, Server process state and last_seen_at_ms. A persisted old timestamp cannot establish online status after Server restart. Metadata updates must patch only their fields and never overwrite a newer source_generation or health update using a stale whole-row object.

## endpoint_session_state

One row per Endpoint containing only its latest successfully accepted complete standard inventory. Before first successful collection, no row exists; this differs from a successfully observed empty list.

| Field | Type / constraint | Meaning |
|---|---|---|
| endpoint_id | TEXT primary key, foreign key endpoints | Owning machine |
| schema_version | INTEGER, positive | Standard inventory document version |
| source_generation | BIGINT, positive | Accepted source connection generation |
| snapshot_revision | BIGINT, positive | Monotonic collection revision within that generation |
| sessions_json | TEXT | Entire current standard inventory, never raw adapter-grouped CLI output |
| observed_at_ms | BIGINT | Endpoint collection completion time |
| received_at_ms | BIGINT | Server receipt time for the accepted update |
| create_at_ms | BIGINT | First accepted inventory time; unchanged on replacement |
| update_at_ms | BIGINT | Latest accepted replacement time |

Inside sessions_json, standard Agent/Session summaries have opaque IDs, generations, state, standard relationships and optional Task summaries; the document also includes standard descriptive adapter summaries and Session adapter_id associations, never executable adapter routing instructions. Endpoint aggregates independent Adapter CLI results and attests structural report completeness, separately from source freshness/success. Server validates the common schema, payload limits and Endpoint scope, not adapter internals. No session_count/running_count columns are required; compute derived values from current JSON under bounded query budgets.

Conditional replacement rules:

- Require enabled authenticated Endpoint, active connection generation and a complete valid document. Check generation against endpoints in the same transaction as publication.
- Insert on first success or replace the whole field only with a newer accepted generation/revision. No per-Session merges, deletions or old-document archives.
- Same generation/revision with canonically equal content returns the prior acknowledgement; changed content is a conflict. Ordering never depends on wall-clock timestamps.
- Valid empty source results clear that source data within the composite. Source failures retain that source last-known values and stale/error metadata while healthy sources update. Only malformed/truncated/oversized report documents retain the whole prior database row. A heartbeat or newly committed report does not refresh stale source observation times.
- Update payload, revision and timestamps together. Acknowledge and publish lightweight Endpoint/revision notification only after commit. On commit failure preserve prior state and report failure.

Restart reads this single row. Reconnect requires new fresh collection; no Session event replay or historical restoration. SQLite WAL/backups may retain previous physical bytes; logical latest-only storage is not secure erasure. Bound WAL through checkpoint policy and bound any backup retention without building inventory history into the application.

## Adapter metadata inside sessions_json

Human clarification:

> adapter的标识信息可以写到 记录session信息的那个字段里面。endpoint会采集各种adapter的信息，汇报给server

Keep the three-table design. The same sessions_json document contains an adapters array and a sessions array (plus optional standard agent/task summaries). This is one atomic latest snapshot, not a separately managed adapter registry.

| JSON location | Standard fields | Meaning |
|---|---|---|
| adapters[] | adapter_id, provider_type, display_name, version, health, collection_status, last_attempt_at_ms, last_success_at_ms, data_known | Endpoint-collected descriptive adapter instance summaries |
| sessions[] | session_id, adapter_id, generation, state and other standard Session fields | Session identity and its reported source adapter |

adapter_id is unique within an Endpoint and stable for a configured instance; provider_type describes the implementation family, not a Server plugin name. Multiple adapter instances can share a provider_type. An adapter with no sessions may still appear in adapters. Every reported Session adapter_id must refer to an adapter summary in the same complete document. Endpoint validates ownership and normalizes health into standard code/message/time fields; Server may validate generic shape/references and expose/filter these values without provider-specific branching.

Server stores these fields only inside sessions_json and returns them through the standard inventory API. TUI may show adapter names, types and Session groupings using generic rendering. Adding an unknown provider_type needs no Server release or schema migration. These labels are not authorization grants, launch profiles, executable paths or control routing selectors. Existing opaque resource/profile targeting remains unchanged: Endpoint resolves actual execution adapters locally.

Collect only bounded, redacted report metadata; do not include credentials, environment variables, local command lines or raw private configuration. Adapter metadata follows exactly the inventory revision/completeness rules and whole-document replacement/retention policy. Do not create independent adapter-history records or duplicate its latest values in SQL columns. A source collection failure preserves only its last-known section while allowing healthy sections to update; invalid whole reports preserve the prior database row. A structurally complete degraded report is valid, but must never claim all-source freshness.

## commands

One admitted standard management intent, independent of current Session membership.

| Field | Type / constraint | Meaning |
|---|---|---|
| command_id | TEXT primary key | Globally unique caller-generated ID; never reused |
| endpoint_id | TEXT foreign key endpoints | Destination machine |
| issuer_id | TEXT | Authenticated operator/service identity |
| operation | TEXT | Versioned standard operation such as agent.start/resume/stop |
| request_json | TEXT | Frozen standard target/profile ID and revision, generation, payload, capability revision and immutable deadline |
| request_hash | TEXT | Versioned canonical request digest for duplicate/conflict detection |
| state | TEXT | admitted, dispatched, endpoint_admitted, executing, finished, rejected, expired, cancelled_before_execution or unconfirmed |
| result_json | TEXT nullable | Standard delivery boundary, effect certainty, outcome and redacted error; no provider-specific response schema |
| deadline_at_ms | BIGINT | Immutable admission/execution validity deadline |
| finished_at_ms | BIGINT nullable | Terminal command lifecycle time, not task success |
| create_at_ms | BIGINT | Durable Server admission time |
| update_at_ms | BIGINT | Latest state change |

No adapter column and no foreign key to a Session table. agent.start targets Endpoint plus launch_profile_id/profile_revision. Other commands target opaque standard resource identity and expected execution generation. Endpoint alone resolves these references to a private adapter. Server authenticates the issuer, checks standard permissions/deadline/schema and routes to Endpoint; Endpoint is the final local execution authority.

Hash input includes immutable issuer/scope/target/operation/payload/deadline values. Compare canonical content as needed; do not disclose an existing command result before authorization. The immutable payload deadline must match deadline_at_ms. Result effect certainty distinguishes not_applied, acknowledged and unknown; finished does not mean Agent task success. Enforce valid state transitions and idempotent result updates; late failures must not erase stronger confirmed evidence.

Persist intent before dispatch. Endpoint has its own private durable deduplication/execution journal; Server SQL alone cannot prevent duplicates across the provider side-effect boundary. Unknown effects remain explicit and are not automatically retried with a new command ID.

## Relationships and indexes

- endpoints 1:0..1 endpoint_session_state; endpoints 1:many commands.
- Use ON DELETE RESTRICT for both foreign keys. Disabling/unregistering revokes access first and explicitly clears current inventory where authorized. Keep the endpoint identity/tombstone while dependent command evidence remains; no cascade deletion of commands.
- endpoint_session_state needs only its primary key initially.
- commands indexes: (endpoint_id, create_at_ms, command_id) and (state, update_at_ms, command_id). Add (issuer_id, create_at_ms, command_id) only if measured operator-history queries need it.
- Endpoint list sorting uses stable endpoint_id ties. Add (update_at_ms, endpoint_id) if required; avoid indexes without corresponding query needs.
- Session filters parse bounded current JSON documents; they are not indexed per-Session SQL queries. Restrict fleet scan scope and measure whole-JSON serialization/read costs. No database-specific JSON indexes in MVP.

## Retention and lifecycle

No Session-history retention job exists. Replacing current inventory does not append old JSON to audit, SSE replay or logs. Revoke/clear Endpoint state through explicit administrative workflows that never touch remote agent workspaces or implicitly stop agents.

Terminal commands initially have a proposed 30-day retention. Never purge executing or uncertain records solely by age. Archive/reconcile explicitly and retain deduplication evidence at least through validity/reconnect windows. Expired repeated commands remain rejected even after detailed result cleanup; globally unique IDs and immutable validity are enforced. Bound prompts/results by size, permission and retention; hash/redact where possible without breaking recoverable execution.

Keep latest standard metadata bounded (capabilities, profiles, labels, errors and inventory). All stored sensitive inputs require restricted access and deliberate protection; never log raw request bodies by default. Authentication enrollment/rotation and audit retention beyond command evidence remain separate security design items, not reasons to add an adapter registry to Server.

## References

- `docs/agent-cluster-architecture.md`: overall boundaries and reporting decisions.
- `docs/agent-cluster-protocol.md`: standard API, command and snapshot semantics.
- `docs/agent-cluster-adapters.md`: Endpoint-private adapter implementation mapping.
- `.task/plan_20261027T153140_agent-cluster-delivery.md`: future verification checklist and delivery phases.

## Independent source freshness within one field

Each Adapter summary records latest attempt status/time, last successful observation time and data_known. Session data for failed sources is retained with original observation evidence; never overwrite its age using the enclosing report receipt time. A first-ever failure has data_known=false, not a verified zero-session count. This per-source formatting/cache composition occurs only at Endpoint; Server performs generic structural validation and whole-field replacement. Explicit Adapter configuration removal is distinguished from discovery failure by Endpoint and removes its section from the next report. The cache retains only last-known values, not historical versions. No SQL columns/tables or Session history are added for failure isolation.
