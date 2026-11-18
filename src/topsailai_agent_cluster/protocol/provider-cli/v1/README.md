# Provider CLI Protocol Version 1

This directory is the language-neutral contract between the Endpoint Generic CLI Adapter and an
independently built Provider CLI. The JSON Schemas define request, response and JSON Lines stream
frames. The Go DTOs and semantic validation live in `internal/providercli`.

## Process framing

A non-streaming invocation reads exactly one JSON request from standard input and writes exactly one
JSON response to standard output. A streaming invocation reads one request and writes one JSON object
per line: one `started` frame, zero or more ordered `record` frames, and one `end` frame. Provider
diagnostics belong on standard error and must never be mixed into standard output.

The Generic CLI Adapter records process exit status separately from the protocol response. It applies
these rules in order:

- Missing, malformed, oversized, uncorrelated or extra standard output is a protocol failure and can
  never prove success.
- Exit status zero plus one valid `ok: true` response is a successful invocation.
- A valid `ok: false` response is a Provider business failure even when the process exits zero. Its
  bounded error code, message and effect certainty remain evidence.
- A non-zero exit is an invocation failure. A valid `ok: false` response is still retained as Provider
  evidence; malformed output does not hide the bounded standard-error diagnostic.
- A non-zero exit paired with `ok: true` is a process/result conflict. It is never accepted as success,
  and its effect certainty is `unknown` because the two result channels disagree.
- Timeout, cancellation or process loss without a complete correlated response never upgrades an
  effect to success. After mutation begins, the effect remains `unknown` unless non-application is
  independently proven.

These precedence rules preserve a Provider's structured rejection without allowing an exit/result
conflict to become a false success.

## Deadline and cancellation

`deadline_at_ms` is an absolute UTC Unix timestamp in milliseconds and must be positive. The Generic
CLI Adapter rejects an already expired request before starting a process, then converts the remaining
budget to a local monotonic deadline. The Provider must not extend or reinterpret that deadline.

Cancellation is process-scoped. The Generic CLI Adapter terminates only the exact invocation process
group and waits for its cleanup; it never terminates processes by a broad name match. A Provider may
hand a durable Agent to an independent lifecycle owner before returning, but it must not report an
acknowledged effect before that custody handoff completes. Cleaning an invocation process group must
not terminate an Agent whose independent handoff already completed.

For a stream, cancellation asks the Provider process to stop. When the terminal channel remains
writable, the Provider emits one correlated `end` frame carrying a cancellation error. EOF without a
terminal frame is `stream_interrupted`, never a clean end.

## Authority boundary

Provider documents contain Provider observations and evidence only. Cluster resource IDs, command
IDs, request hashes, journal phases, command revisions and complete Cluster execution receipts are
Endpoint authority and are rejected at this seam.

## Typed query contracts

The `query` envelope carries one registered query name and the fixed query version `v1`. The
query-specific request schemas validate only `payload`, and the matching result schemas validate
only `query_result`; neither document repeats the query name or version. The Generic CLI Adapter
selects exactly one request and result schema from the correlated envelope. An unknown query or
version is rejected before invocation, and an unadvertised query is not invoked.

All query payloads and results are closed objects. Unknown fields, extra JSON documents and JSON
`null` are rejected rather than ignored or normalized. Optional fields may be omitted only where the
matching schema allows omission; omission is not interchangeable with `null`.

Provider-owned resource references carry both the required `resource_kind` and a non-empty stable
`provider_resource_key`. `launch.options` uses `launch_profile`, `history.messages` uses `session`,
and `model.catalog` uses `model_profile`; any other kind fails closed. The same provider business
resource must retain the same key across repeated reads, provider restarts and every upgrade that
claims identity compatibility. Duplicate keys in one result are invalid.

A Provider query result must never contain a Cluster-owned identity such as `launch_profile_id`,
`resource_id`, `model_profile_id`, `cluster_session_id` or `command_id`. The Endpoint maps the tuple
`(adapter_id, resource_kind, provider_resource_key)` through `ResourceMapper` and publishes only the
resulting opaque Cluster ID. A Provider cannot mint, copy or infer that ID.

### The closed query registry

Seven queries are registered, all at version `v1`. The registry is closed: a Provider may advertise
support for a registered query or return `unsupported`, but it cannot add a provider-namespaced
query. `internal/providercli/queries.go` is the single source of truth, and the conformance suite
reads the same registry so a newly registered query cannot be exercised with a request that breaks
its own rule.

| Query | Addresses | Target required | Session set in payload |
|---|---|---|---|
| `launch.options` | a launch profile | no | no |
| `history.messages` | a session | no | no |
| `model.catalog` | a model profile | yes | no |
| `session.messages` | a session | yes | no |
| `session.metrics` | a session | yes | no |
| `session.metrics.batch` | a set of sessions | no | yes |
| `session.detail` | a session | yes | no |

Two rules are stated once in code and enforced in two places, because the decoder rejects a request
that breaks them and the conformance suite builds a request that satisfies them:

- `QueryRequiresSessionTarget` — the query addresses one session, so the envelope must carry a
  session target. `session.metrics.batch` is named explicitly as the exception rather than left to
  the default, so a reader cannot mistake its absence for an omission.
- `QueryRequiresSessionSet` — the query addresses a set, so the payload must carry that set. Only
  `session.metrics.batch` does. Without this shared rule the suite swept every registered query while
  supplying a payload only for the ones it happened to name, so a set-addressed query reached the
  Provider with an empty payload and the Provider's correct rejection read as a Provider defect.

A session-addressed query targets the Provider's own session identifier rather than a Cluster
resource ID, because a session with no live process has no Cluster resource ID and these reads exist
precisely for such a session.

The machine-readable contracts are:

- `launch-options-request.schema.json` and `launch-options-result.schema.json`
- `history-messages-request.schema.json` and `history-messages-result.schema.json`
- `model-catalog-request.schema.json` and `model-catalog-result.schema.json`
- `session-messages-request.schema.json` and `session-messages-result.schema.json`
- `session-metrics-request.schema.json` and `session-metrics-result.schema.json`
- `session-metrics-batch-request.schema.json` and `session-metrics-batch-result.schema.json`
- `session-detail-request.schema.json` and `session-detail-result.schema.json`

### Provider document seams

`session.detail` is the one query whose result carries documents the contract deliberately does not
model. Its two document fields are seams, not typed structures:

| Field | Producer | Forwarding rule |
|---|---|---|
| `provider_metadata` | the Provider's session record | forwarded verbatim, whole record |
| `provider_runtime` | the Provider's runtime observation | forwarded verbatim, raw bytes |

Both are optional strings. The contract fixes only their position and their bound, so a second
Provider may report entirely different documents with no protocol, Server, schema or CLI change. A
Provider that reports neither is honest about it, and the surface renders the absence as
`not reported` rather than inventing an observation. Requiring either field would force a Provider to
emit a placeholder, and a placeholder is a claim nobody made.

Both are bounded by `maxLength` in the schema and by the Endpoint's configured bound in code. The
bound is enforced as a hard rejection, never a truncation: a shortened Provider document presented as
the whole record is worse than a refused read, because the operator cannot tell which fields are
missing. There is no truncation flag, because a flag would make a partial document look like a
supported outcome.

## Size bounds

Request budgets are byte and record limits. JSON Schema `maxLength` counts Unicode characters rather
than encoded bytes, so it is only a portable shape bound for strings. Every implementation must also
enforce the constants in `internal/providercli` against UTF-8 encoded byte length. The Generic CLI
Adapter additionally enforces the request's standard-output, standard-error and record budgets while
reading the process; a structurally valid document cannot expand those transport budgets.
