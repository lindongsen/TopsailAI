---
maintainer: AI
author: DawsonLin
created: 2026-11-07
---

# Server HTTP API

This document describes the Server HTTP surface implemented in `internal/server`. It is a
reference for the current implementation, not a proposal. The abstract protocol, resource model
and command lifecycle are specified in `docs/agent-cluster-protocol.md`; this document only
records the concrete routes, parameters and response shapes that exist today.

The Server is the only network boundary an operator client uses. A client never calls an Endpoint
directly and never invokes a provider CLI.

## Common response envelope

Every JSON response uses the same envelope.

| Field | Type | Meaning |
|---|---|---|
| `code` | int | `0` on success; a non-zero value is a business error code |
| `message` | string | Human-readable message |
| `data` | any | Payload, or `null` on error |
| `request_id` | string | Correlation identifier, also returned in the `X-Request-ID` header |
| `timestamp` | int64 | Server response time in UTC epoch milliseconds |

Errors carry a stable machine-readable `code` string in the `code` field and a meaningful HTTP
status. Clients must branch on the code, not on the message text.

## Authentication

Every route except `/healthz` and `/readyz` requires a bearer token.

```text
Authorization: Bearer <token>
```

A missing or wrong token returns `401 unauthorized`. The token is configured through
`AGENT_CLUSTER_AUTH_TOKEN`; see `docs/Environment_Variables.md`.

The token may be restricted to a set of operator scopes through `AGENT_CLUSTER_AUTH_SCOPES`. An
empty scope set leaves the credential unrestricted, which is the single-administrator deployment.
The recognised scopes are `view`, `read_output`, `send_message`, `control` and `endpoint_admin`.

Command admission authorizes the requested operation against the scopes and against the permission
the Endpoint advertises for that operation. A rejected admission returns `403 permission_denied`.

## Health and readiness

| Method | Path | Purpose |
|---|---|---|
| GET | `/healthz` | Liveness; unauthenticated |
| GET | `/readyz` | Readiness; unauthenticated, returns `503 not_ready` when storage is unavailable |

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/endpoints` | List Endpoint summaries |
| PUT | `/api/v1/endpoints` | Register or update one Endpoint |
| GET | `/api/v1/endpoints/{endpoint_id}/session-state` | Read the persisted latest inventory document |
| PUT | `/api/v1/endpoints/{endpoint_id}/session-state` | Submit a full inventory report |
| POST | `/api/v1/endpoints/{endpoint_id}/session-state/refresh` | Force one fresh Endpoint collection |
| GET | `/api/v1/endpoints/{endpoint_id}/capabilities` | Read standard capability descriptors |

`GET /api/v1/endpoints` accepts `offset`, `limit`, `sort_key` and `order_by`. `offset` defaults to
`0` and `limit` to `1000`.

`GET .../capabilities` accepts an optional `name` query parameter. When `name` is supplied and the
capability is not advertised, the response is `501 unsupported` rather than an empty success, so a
caller cannot mistake an absent capability for a supported one with no detail.

### Inventory submission and latest-only storage

`PUT .../session-state` accepts one complete inventory document. The Server validates it and
atomically replaces the single stored document for that Endpoint. There is no per-session row and
no snapshot history. A report that is not newer than the stored document is ignored by storage.

The document carries `schema_version`, `source_generation`, `snapshot_revision`, `observed_at_ms`,
`report_complete`, `collection_status`, `adapters` and `sessions`. `collection_status` is one of
`succeeded`, `partial`, `failed` or `unknown`.

### Forced collection

`POST .../session-state/refresh` forces one fresh collection and waits for it to be committed. The
response `data` is the document re-read from storage, so it always equals a following
`GET .../session-state`. This is the only route that makes the operator's next view fresh; `GET`
remains a read-only projection of the persisted document.

The Server request budget is 30 seconds, which exceeds the Endpoint collection budget so the inner
component reports its own failure first.

| Status | Code | Meaning |
|---|---|---|
| 200 | `success` | The committed document is at least as new as the report this request forced |
| 503 | `unavailable` | No forced-collection channel is configured |
| 503 | `endpoint_unavailable` | Transport failure, disconnect, or the request deadline expired |
| 503 | `not_committed` | The committed document could not be read back |
| 409 | `not_committed` | Storage ignored the report, so freshness is not proven |

The `409` case exists because storage silently ignores a report that is not newer than the stored
document. A submitted report alone therefore cannot prove freshness, so the handler compares the
committed observation time and snapshot revision against the submitted report and fails closed.

A refresh response confirms only that a newly attempted collection was committed. It does not claim
that every adapter source was freshly observed; degraded sections keep their own freshness metadata.

## Commands

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/commands` | Admit one target-bound intent |
| GET | `/api/v1/commands` | List recent commands |
| GET | `/api/v1/commands/{command_id}` | Read durable delivery and result evidence |
| POST | `/api/v1/commands/{command_id}/cancel` | Cancel a command that has not been dispatched |

`GET /api/v1/commands` accepts `endpoint_id`, `resource_id` and `limit`. `limit` defaults to `20`
and is clamped to `100`.

### Admission

A command request is one immutable intent. The client supplies `command_id`, `endpoint_id`,
`operation`, `operation_version`, `capability_revision`, `payload_schema_version`, `payload`,
`execute_before_at_ms` and either a `target` or a `launch_profile_id` with `profile_revision`.

The Server derives the issuer identity from authentication and rejects a client-supplied
`issuer_id` that disagrees with it (`403 issuer_mismatch`). The Server never accepts authority
claims from the request body.

`202 Accepted` means Server admission only. It is not delivery and not execution. A repeated
`command_id` with an identical canonical intent returns the prior record; a changed intent returns
`409 intent_conflict`. An intent whose `execute_before_at_ms` has already passed is recorded and
immediately expired rather than dispatched.

### Command record

A command record separates lifecycle from provider evidence. It carries `command_id`,
`request_hash`, `endpoint_id`, `operation`, `status`, `phase`, `delivery_boundary`,
`effect_certainty`, `exit_confirmed`, `error_code`, `provider_response`,
`provider_response_truncated`, `deadline_at_ms` and `create_at_ms`.

`provider_response` is the provider's own return document, bounded to 64 KiB, stored and returned
verbatim. The Server never parses it. `provider_response_truncated` marks a shortened document so a
partial provider answer is never presented as complete evidence.

Reads converge commands that are still `executing` past their immutable deadline into the terminal
`unconfirmed` state with `unknown` effect certainty. Convergence is idempotent and never rewrites a
command that already reached a terminal state.

Cancellation succeeds only before dispatch. A command that was already dispatched returns
`409 too_late_to_cancel`, because a cancellation request cannot claim that provider effects stopped.

### Operation families

Admission validates the requested operation against the permission the Endpoint advertises for it.
Two standard families are defined; both are versioned operations with fixed payload schemas, not a
passthrough for provider-specific instructions.

| Family | Operation | Payload | Required permission |
|---|---|---|---|
| Provider control | `ctl.<action>` | JSON object forwarded as the action arguments | `read_output` for actions that return conversation content, otherwise `control` |
| Command execution | `command.exec` | `{"argv": ["..."]}` | `control` |

`ctl.<action>` is advertised one capability per action, so an action the Endpoint does not serve is
absent from the inventory and is refused at admission with `403 permission_denied`. The action name is
an opaque standard identifier: the Server never interprets provider semantics or routes by adapter.

`command.exec` carries an argv array and never a command string, because the Endpoint must not parse
or split a string. `argv` is required, is limited to 64 tokens, each token is limited to 4096 bytes,
and no token may be empty or contain a control character. The Endpoint matches the array against an
Endpoint-global allowlist by prefix and executes it in the session `project_workspace`, falling back
to the session `pwd`. When neither resolves, or when no allowlist is configured, the operation fails
closed with `policy_denied` rather than falling back to an unrestricted or inherited directory.

The result document carries `argv`, `exit_code`, `stdout`, `stderr`, `truncated`, `observed_at_ms`
and an optional `error_code`. It is one bounded snapshot, not a stream: `truncated` marks output that
exceeded the capture limit, and a non-zero `exit_code` is a legitimate result rather than a transport
failure.

## Output snapshots

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/output` | Read one bounded output snapshot |

Required query parameters are `endpoint_id` and `resource_id`. Optional parameters are
`provider_generation`, `max_bytes` and `max_lines`.

`max_bytes` defaults to 64 KiB and is clamped to 1 MiB. `max_lines` is optional; an absent or
invalid value keeps the provider default, and an explicit value is clamped to the provider range of
10000 lines. The two budgets are independent because providers differ: a line-oriented provider
uses `max_lines`, a byte-oriented provider uses `max_bytes`.

A snapshot longer than `max_bytes` is truncated on a UTF-8 boundary and labelled `truncated: true`,
so a shortened payload never ends in half a character. The follow route uses the same truncation
rule, because a caller that receives invalid UTF-8 cannot tell a corrupt provider from a truncated
read.

The result is one bounded snapshot with its observation time. It is not a stream, not a follow and
not a durable subscription. A provider that cannot answer returns `503` with the provider's error
code, so an unavailable read is never reported as an empty successful read.

## Output follow

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/output/follow` | Stream output records for one resource |

Required query parameters are `endpoint_id` and `resource_id`. Optional parameters are
`provider_generation`, `max_bytes` and `max_lines`. `max_bytes` defaults to 64 KiB and is clamped to 1 MiB;
`max_lines` keeps the provider default when absent or invalid and is clamped to 10000 lines.

`max_bytes` bounds one record, because one record is one chunk. A record longer than the budget is
truncated on a UTF-8 boundary and labelled `truncated: true`, and the stream continues with the next
record. An oversized record is therefore never reported as a provider failure, and it never hides
the records that follow it.

The response is `application/x-ndjson` with `Cache-Control: no-store`: one JSON record per line,
chunk records first and exactly one terminal record last. Each record carries `lines`,
`observed_at_ms`, `truncated`, `end` and an optional `error_code`. A consumer that stops receiving
records without a terminal record must treat the stream as interrupted rather than complete; the
client reports `stream_interrupted` in that case.

A transport that cannot stream returns `503` with `unsupported` rather than degrading into a
snapshot, because a snapshot presented as a stream would look complete while silently missing
everything written after it. The Endpoint admits at most 8 concurrent follows and rejects an excess
request with `too_many_follows` instead of queueing it, so a long follow cannot starve commands,
heartbeats or inventory reports on the shared channel. Cancelling the request stops the stream; it
does not stop the agent.

## Launch options

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/launch-options` | Read the live start-capable handler catalog |

`endpoint_id` is required. An optional `adapter_id` queries that handler's managed projects.

The response `data` contains `handlers` (each with `adapter_id`, `display_name` and `revision`),
`projects` (each with `name` and `path`) and an optional `error_code`. A failed project query is
reported as an error, never as an empty successful list.

The query is forwarded through the existing Endpoint channel, bound to the exact connection
generation and request ID, and waits at most 10 seconds. At most 64 launch queries may be pending.

## Session history

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/history` | Read one bounded live provider session-history window |

`endpoint_id` is required. The route is a live provider read, not a stored projection: it never
serves persisted inventory and never caches a result. The Server forwards the query verbatim and
returns the adapter's answer unchanged, so it does not interpret provider status words, re-derive
resumability or correlate rows with the inventory.

`limit` is optional and narrows the caller's view only. It is parsed at the Server boundary and
forwarded as an explicit protocol value, so the transport layer never re-reads the request. An absent,
non-numeric or negative value keeps the provider's own window instead of silently narrowing the read
to zero rows. A positive value can never raise the provider's own cap, and the adapter judges provider
truncation before applying it, so a narrowed view is never presented as a complete history.

Reading history requires the `view` scope. A history row carries the session name, the recorded task
text and the project workspace, which is metadata rather than session output, so `view` is the
required scope and reading a session's actual output still needs the separate `read_output` scope.
The check runs before the transport is consulted, so an unauthorized caller cannot infer Endpoint
reachability from the response.

The response `data` contains `rows`, `observed_at_ms` and an optional `truncated`. Each row carries
`provider_session_id`, an optional `resource_id`, descriptive `provider_display_name`, `provider_project_workspace`,
`task`, `provider_status`, `provider_no`, `created_at_ms`, `modified_at_ms`, `resumable` and an
optional `resume_blocked_reason`.

A history row is deliberately not a routable resource. It carries an opaque cluster handle so a
resume request can address it, but it never carries a provider generation, because a past session is
not running and therefore has no generation to validate. Routing still requires `resource_id` plus
`provider_generation`, and only the inventory join can supply that pair.

`truncated` reports that the provider returned its own capped window rather than everything that
exists, so a bounded window is never presented as a complete history. Accepted rows are bounded by
1000, the provider document by 512 KiB and one task text by 8192 bytes.

Failure outcomes keep their own status, because an unsupported adapter is not an outage and an empty
history is not an error:

| Status | Code | Meaning |
|---|---|---|
| 400 | `invalid_target` | `endpoint_id` is missing |
| 403 | `permission_denied` | The credential does not hold the `view` scope |
| 404 | `endpoint_not_found` | The endpoint identifier is not registered |
| 501 | `history_unsupported` | No configured adapter can list history |
| 502 | `provider_error` | The provider call failed |
| 502 | `history_response_too_large` | The provider document exceeded the configured bound |
| 503 | `unavailable` | The Server has no history query channel configured |
| 503 | `endpoint_unavailable` | The endpoint is registered but has no live connection |

The query is forwarded through the existing Endpoint channel, bound to the exact connection
generation and request ID, and waits at most 10 seconds.

## Events and manifest

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/events` | Server-sent events of latest-state invalidations |
| GET | `/api/v1/manifest` | Current endpoint IDs and snapshot revisions |

`/api/v1/events` is a `text/event-stream` response. Each event carries `type`, `endpoint_id`,
`snapshot_revision`, `server_instance_id` and `sequence`. An event is a lightweight invalidation
emitted after a commit, not authoritative data: a client reloads the current document rather than
treating the event as the document. Events never contain historical session payloads or stdout.

`/api/v1/manifest` returns `server_instance_id` and one entry per Endpoint with its current
`snapshot_revision`. It reconciles a missed final notification while connected. A changed
`server_instance_id` means the Server restarted, so the client must resynchronize.

Both routes are registered only when an event broker is configured.

## Method and body handling

An unsupported method on a known route returns `405 method_not_allowed`. An unknown path returns
`404 not_found`.

Request bodies are limited to 4 MiB and decoded strictly: unknown fields are rejected and trailing
JSON values are rejected. A malformed body returns `400 invalid_request`.

## Related documents

- `docs/agent-cluster-protocol.md`: abstract resources, capability contract and command lifecycle.
- `docs/agent-cluster-architecture.md`: boundaries, authority and storage decisions.
- `docs/agent-cluster-database.md`: Server business tables and retention.
- `docs/Environment_Variables.md`: configuration read by the binaries.
