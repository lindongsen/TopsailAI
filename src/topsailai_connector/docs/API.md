---
maintainer: AI
author: DawsonLin
status: decided
created: 2026-11-10
updated: 2026-11-10
---

# CLI HTTP API

## Status

This document describes the interface the CLI uses to reach a Node through the
Server. The interface is decided; the Server does not implement it yet. It is
written down now because the wire contract, the three secrets and the routing rule
all depend on it, and a decision that lives only in a conversation is a decision
that gets reversed by accident.

The channel protocol between the Server and the Node is **not** part of this
document. It is private to those two components and is described in
`docs/permission-design.md`.

## Why the CLI talks HTTP and not the channel protocol

The CLI is a subcommand of the Server binary. It could speak the channel protocol
directly, and that would be one protocol instead of two. It does not, for three
reasons:

- The channel protocol carries a Node's `hello` and a Server's `hello_confirm`. A
  CLI is neither, so it would need a third participant in a protocol designed for
  two.
- The channel protocol is a long-lived bidirectional link. A CLI request is one
  short round trip, and modelling it as a link means the CLI has to manage
  reconnect, heartbeat and teardown for a single call.
- An HTTP endpoint is inspectable with `curl`, testable without a Node, and
  reachable through an ordinary reverse proxy. A private binary protocol is none
  of those.

The cost is a second surface to secure. It is accepted because the second surface
is small: one endpoint, two headers, one JSON body.

## Endpoint

```
POST /v1/nodes/{node_id}/operations
```

`node_id` is the identifier the Node generated at first start and reported in
`hello`. It is an address, not a credential: knowing it grants nothing without the
`node-token`.

The `node_id` appears in the URL, where the Server routes by it. The CLI splits
the `node-id.node-token` pair locally and sends only the token half in
`X-Connector-Node-Token`, so the Server never holds both halves and cannot compare
them. A caller that routes to one Node while presenting another Node's secret is
refused by the Node it reached, because only the Node knows its own token.

### One listener, two surfaces

The Server serves the channel and the CLI API from **one** listener, on one port,
behind one TLS certificate:

| Path | Surface | Client |
|---|---|---|
| `/channel` | WebSocket, the channel protocol | Node |
| `/v1/nodes/{node_id}/operations` | HTTP JSON | CLI |

One listener is chosen because two would mean two TLS certificates, two firewall
rules and two reverse-proxy entries for one service, and because the two surfaces
share the same registry: a CLI request is routed to a Node connection that the
channel surface owns. Splitting the listeners would not split the state, so it
would buy isolation that does not exist.

The consequence to state plainly: the CLI API is reachable by anyone who can reach
the channel port. That is acceptable because the API authenticates every request
with `client_token` before it reads the `node-token`, and because a caller who
can reach the port can already attempt a `hello`. A deployment that wants the CLI
API unreachable from the internet puts a reverse proxy in front and blocks
`/v1/` there; the Server does not need a second port to express that.

The path prefix is part of the contract, not an implementation detail: a proxy rule
that forwards `/v1/` and `/channel` differently depends on it, so changing either
path is a breaking change to the deployment.

### Headers

| Header | Required | Content |
|---|---|---|
| `Authorization` | yes | `Bearer <client_token>` |
| `X-Connector-Node-Token` | yes | The `node-token` half of the pair, verbatim |
| `Content-Type` | yes | `application/json` |
| `X-Request-Id` | no | Caller-supplied correlation id, echoed in the response |

The two secrets travel in separate headers on purpose. A log that redacts
`Authorization` then does not accidentally print the Node's secret, and a proxy
that rewrites one header does not corrupt the other. Putting both in one header or
in the body would make redaction all-or-nothing.

The CLI holds the pair as one string, `node-id.node-token`, and splits it before
sending: the `node-id` goes into the URL, the `node-token` into
`X-Connector-Node-Token`. The Server never receives the pair as a single value, so
it never has a value that is half public and half secret.

### Body

```json
{
  "operation": "file.read",
  "scope": "project",
  "path": "notes.md",
  "offset": 0,
  "length": 0
}
```

| Field | Type | Required | Meaning |
|---|---|---|---|
| `operation` | string | yes | One of `file.list`, `file.stat`, `file.read` |
| `scope` | string | yes | A scope name the Node's policy defines |
| `path` | string | depends | Relative path inside the scope. Required for `file.stat` and `file.read`, optional for `file.list` |
| `offset` | int64 | no | Byte offset for `file.read`. Default `0` |
| `length` | int64 | no | Byte count for `file.read`. `0` means up to the response cap |
| `data` | base64 | no | Reserved for `file.write`. Refused in the first version |
| `argv` | string array | no | Reserved for `command.exec`. Refused in the first version |

`file.write` and `command.exec` are refused with `unsupported_operation` even
though the wire contract declares them. The refusal is at dispatch, not at
advertisement, so it does not depend on the Server honouring what the Node
advertised. An operation name outside the vocabulary gets the same
`unsupported_operation` code, so a caller cannot enumerate the vocabulary by
comparing the two answers.

### Response

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "node_id": "node_7f3a...",
    "operation": "file.read",
    "request_id": "req_01H...",
    "content": "base64...",
    "size": 1024,
    "truncated": false
  },
  "request_id": "req_01H...",
  "timestamp": 1762732800000
}
```

The envelope is the project-wide response format: `code`, `message`, `data`,
`request_id`, `timestamp`. `code` is `0` on success and a non-zero business code
otherwise.

`data` varies by operation:

| Operation | `data` fields |
|---|---|
| `file.list` | `entries`: array of `{name, type, size, mode, modified_at}` |
| `file.stat` | `type`, `size`, `mode`, `modified_at`, `is_symlink`, `link_target` |
| `file.read` | `content` (base64), `size`, `truncated` |

`file.stat` reports a symlink without following it, so `is_symlink` and
`link_target` describe the link itself. Following it is exactly the operation the
path fence refuses.

## Error codes

A caller must be able to tell "you may not" from "it is not there" from "the Node
is not connected". A single `error` string cannot express that distinction, which
is why the codes are enumerated.

| Code | Name | Meaning | Retry |
|---|---|---|---|
| `0` | `success` | The operation happened | — |
| `1001` | `invalid_argument` | The request is malformed: bad scope name, rejected path, bad JSON | No |
| `1002` | `unauthenticated` | `client_token` is missing, empty or does not match; or the `node-token` was refused by the Node | No |
| `1003` | `node_offline` | No live connection for that `node_id` | Yes, later |
| `1004` | `node_timeout` | The Node did not answer within the request timeout | Yes |
| `1005` | `denied` | The Node refused: no grant, or the policy does not allow it | No |
| `1006` | `not_found` | The path does not exist inside the scope | No |
| `1007` | `unsupported_operation` | The operation is unknown or declared but not enabled in this version | No |
| `1008` | `too_large` | The response exceeds the cap, or the request body exceeds the limit | No |
| `1009` | `internal` | The Server failed. Details are logged, not returned | Yes |

`denied` and `not_found` are deliberately distinct. Collapsing them would let a
caller probe for the existence of a file it may not read, which is an information
leak dressed as a simpler API.

`internal` never carries a detail string. A detail string is where an absolute
path, a token fragment or a stack trace reaches a caller, and none of those belong
in a response.

## What the Server validates, and what it must not

The Server validates **shape**, because a malformed request should fail before it
costs a round trip to the Node:

- `client_token`: compared in constant time against the configured value.
- The `node_id` in the path equals the `node-id` half of the pair the caller
  presents.
- The operation is a known name.
- The scope name is a valid identifier.
- The path is not absolute and contains no `..`, `.`, backslash, colon or NUL.
- The body fits the size limit.

The Server must **not** validate authority:

- It does not decide whether the `node-token` is valid. It cannot: the Node
  generated it and the Server has never seen the value.
- It does not decide whether the grant covers the operation. That is the Node's
  decision, and a Server that pre-empted it would become an authority for
  operations.
- It does not decode, re-encode, normalise or wrap the `node-token`. A re-encoded
  value is a derived value, and a derived value is a stored credential index in
  disguise.

The order matters: `client_token` is compared **before** the `node-token` is read
at all. Otherwise an unauthenticated caller could use the Server as an oracle for
Node token validity.

## What the Server never does with either secret

- It never writes `client_token` or a `node-token` to a log, a trace, an audit
  record or an error message. An audit record names the `node-id`, never a secret.
- It never stores the `node-token`. It is forwarded on the request it arrived with
  and released when the response is written.
- It never keeps `client_token` beyond the request. It is compared per request and
  released when the response is written.
- It never stores a hash, prefix or fingerprint of either secret.
- It never claims to have validated the `node-token`. It relays the Node's
  refusal, because a Server that reported a check it never performed would be
  lying about the one thing the caller relies on.

## Routing

The Server keeps an in-memory registry `node_id -> connection`. The registry is
memory only: persisting it would create a record of which Nodes exist and when
they were last seen, which is a privacy decision this design does not make.

- A request for an unknown `node_id` is refused with `node_offline`. It is **not**
  queued. Queueing would turn an immediate refusal into a delayed surprise, and
  the caller would not know whether the request would ever run.
- The path `node_id` selects the connection. The Server does not compare it with
  anything, because the `node-token` arrives in a header on its own and the Server
  never receives the pair. A pair whose halves disagree is refused by the Node,
  which is the only party that knows the correct `node-token`. The Server relays
  that refusal unchanged.
- One connection serves one Node. A Node that reconnects replaces its registry
  entry, and the previous connection is closed.

## Concurrency

- Requests to one Node are multiplexed over its single channel by `request_id`.
  The Node may answer out of order.
- The Server bounds in-flight requests per Node. A Node that stops answering must
  not accumulate unbounded pending state on the Server.
- A request that exceeds `CONNECTOR_SERVER_REQUEST_TIMEOUT_SECONDS` is answered
  with `node_timeout` and its pending entry is removed. The Node's eventual answer
  is discarded, because the caller has already been told the request failed.

## CLI surface

The CLI is a subcommand of the Server binary, so an operator installs one binary
and gets both the Server and the client. It has no configuration file: every input
comes from a flag or from an environment variable, and a flag wins over the
environment because a flag is the more explicit statement of intent.

```
connector-server cli --server https://cloud.example:8443 \
    --client-token <client_token> --node node_7f3a.kq2v... --scope project \
    --path notes.md file.read
```

`--node` takes the whole pair, not just the identifier, because the pair is what
the operator copies from `connector-node id`. The CLI splits it and sends the two
halves to the two places the Server expects them.

| Flag | Environment | Required | Meaning |
|---|---|---|---|
| `--server` | `CONNECTOR_CLI_SERVER_URL` | yes | Server base URL, `http` or `https` |
| `--client-token` | `CONNECTOR_CLI_CLIENT_TOKEN` | yes | The `client_token` the Server operator issued |
| `--node` | `CONNECTOR_CLI_NODE` | yes | The whole `node-id.node-token` pair |
| `--scope` | none | yes | A scope name the Node's policy defines |
| `--path` | none | no | Relative path inside the scope; empty means the scope root |
| `--offset` | none | no | Byte offset for `file.read`, default `0` |
| `--length` | none | no | Byte count for `file.read`; `0` means up to the cap |
| `--request-id` | none | no | Correlation id echoed by the Server; generated when absent |
| `--json` | none | no | Print the whole response envelope instead of the payload |

The operation name is the one positional argument: `file.list`, `file.stat` or
`file.read`. A second positional argument is refused rather than ignored, because
an ignored argument is a command that did something other than what it looked like
it did. Flags must precede the operation name, because Go's flag parser stops at
the first non-flag argument.

Rules:

- `client_token` and the `node-id.node-token` pair are read from the environment as
  well as from a flag, because a script that calls the CLI repeatedly should not
  repeat the credential on every line. **The environment variable is the
  recommended form**, because a flag value is visible in `argv` to every account on
  the host and is written to shell history by default. The flag exists for a script
  that already holds the secret and would otherwise have to export it, and a flag
  that is present takes precedence over the environment variable. That exposure is
  an accepted trade-off recorded in the residual risks of
  `docs/permission-design.md`.
- The CLI never prints a secret, and it never includes one in an error message.
  `cli.Describe` prints the `node-id` in full because it is the public half, and
  replaces both secrets with `<redacted>` without revealing a prefix or a length.
- The CLI exits non-zero on any error code, so a shell script can branch on it. The
  error code and message go to stderr, and the payload goes to stdout, so
  `file.read` can be piped into another program without stripping a header.
- `file.read` writes the file content to stdout as raw bytes, not as JSON. A
  `--json` flag wraps the whole response envelope for scripting.
- A truncated `file.read` prints a notice on stderr, never on stdout, because a
  notice on stdout corrupts a piped payload.
- The CLI refuses a `--node` value that does not parse as `node-id.node-token`
  before sending anything, so a copy-paste error surfaces locally instead of as a
  confusing authentication failure from the Node.
- The CLI's own timeout is longer than the Server's forward timeout, so the CLI
  receives the Server's `node_timeout` answer instead of giving up first and
  reporting a network error that hides the real cause.

## How the CLI learns the pair

The CLI cannot discover the pair. It is generated by the Node at first start and
printed by `connector-node id`, and the operator passes it to the CLI with `--node`
or `CONNECTOR_CLI_NODE`.
There is no lookup endpoint, because a lookup endpoint would let any caller
enumerate which Nodes exist.

The ordering constraint is recorded in `docs/permission-design.md` "How the
operator learns the pair": the Node must start once before any CLI can reach it,
because the Server cannot route to a name it has never been told.

If the Node regenerates its pair, the CLI's copy stops working. That is the
intended behaviour: a regeneration that left the old secret valid would not be a
regeneration. The operator copies the new pair, and the old one is dead.

## Related documents

- `docs/permission-design.md` — the three secrets, the path fence, the policy file.
- `docs/Environment_Variables.md` — configuration surface.
