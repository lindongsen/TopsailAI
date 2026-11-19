---
maintainer: AI
author: DawsonLin
status: decided
created: 2026-11-10
updated: 2026-11-18
---

# CLI HTTP API

## Status

This document describes the interface the CLI uses to reach a Node through the
Server. The interface is implemented and covered by unit, integration and
end-to-end tests.

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
is small: one endpoint, three headers, one JSON body.

## Two proofs, two verifiers

A CLI request carries **two independent authentication proofs**. Each one is
verified by a different party, and neither party can verify the other's.

| Proof | Header | Signed with | Verified by | Forwarded to the Node |
|---|---|---|---|---|
| Client proof | `Authorization` | The client credential secret | Server | No |
| Node proof | `X-Connector-Node-Auth` | The node credential secret | Node | Yes, byte for byte |

The client proof answers "may this caller use the Server". The node proof answers
"may this caller operate on this Node". Passing the first proves nothing about the
second, which is why both are required.

Neither proof carries a scope or a permission. Authorization lives in the Node's
policy file alone.

### Why the Server never receives the node secret

The Server forwards the node proof and keeps no copy. It never receives the node
credential secret at all, so it cannot mint a proof, cannot verify one, and cannot
recognise one later.

This is stronger than "the Server does not store the secret". A Server that
received the secret and merely promised not to store it would still hold it for
the duration of a request, and a compromised Server would hold every Node's
credential at once. A Server that never receives it has nothing to leak.

The consequence is stated plainly: the Server cannot tell a valid node proof from
an invalid one. It relays the Node's refusal instead of claiming a check it never
performed.

## Endpoint

```
POST /v1/nodes/{node_id}/operations
```

`node_id` is the identifier the Node generated at first start and reported in
`hello`. It is an address, not a credential: knowing it grants nothing without a
node credential.

The `node_id` appears in the URL, where the Server routes by it, and again inside
the signed node proof, where the Node checks it. The two must agree, and the Node
is the party that enforces it, because the Node is the only party that knows which
credential belongs to which identifier.

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
the channel port. That is acceptable because the API verifies the client proof
before it forwards anything, and because a caller who can reach the port can
already attempt a `hello`. A deployment that wants the CLI API unreachable from
the internet puts a reverse proxy in front and blocks `/v1/` there; the Server
does not need a second port to express that.

The path prefix is part of the contract, not an implementation detail: a proxy rule
that forwards `/v1/` and `/channel` differently depends on it, so changing either
path is a breaking change to the deployment.

### Headers

| Header | Required | Content |
|---|---|---|
| `Authorization` | yes | `CONNECTOR-CLIENT-HMAC-SHA256 version=1,key_id=...,timestamp_ms=...,nonce=...,signature=...` |
| `X-Connector-Node-Auth` | yes | `CONNECTOR-NODE-HMAC-SHA256 version=1,key_id=...,timestamp_ms=...,nonce=...,signature=...` |
| `Content-Type` | yes | `application/json` |
| `X-Request-Id` | no | Caller correlation id, signed by both proofs and echoed in the response |

The two proofs travel in separate headers on purpose. A log that redacts
`Authorization` then does not accidentally print the node proof, and a proxy that
rewrites one header does not corrupt the other. Putting both in one header or in
the body would make redaction all-or-nothing.

`Authorization` is used rather than a custom name because a proxy or a log
redactor already treats it as sensitive. The value is a proof, not a bearer
secret, so a redactor that hides it hides a value that could not be reused anyway.

### Proof grammar

Both proofs use one grammar, and every deviation is a refusal:

```
<scheme> version=1,key_id=<key-id>,timestamp_ms=<decimal>,nonce=<32 hex>,signature=<64 hex>
```

| Field | Rule |
|---|---|
| `scheme` | Exactly `CONNECTOR-CLIENT-HMAC-SHA256` or `CONNECTOR-NODE-HMAC-SHA256`, matching the header it appears in |
| `version` | Exactly `1`. A future format change is detectable instead of being read as the current one |
| `key_id` | 1 to 64 characters of `a-z`, `0-9`, `-` and `_`, not starting with `-` or `_` |
| `timestamp_ms` | Canonical non-negative decimal: no sign, no prefix, no leading zero except the single value `0` |
| `nonce` | Exactly 32 lowercase hexadecimal characters, which encode 128 random bits |
| `signature` | Exactly 64 lowercase hexadecimal characters, the HMAC-SHA256 value |

Fields must appear in that order, exactly once, with no optional whitespace. The
whole header value is capped at 512 bytes, because the header is parsed before it
is verified and an unbounded header would let the peer decide how much memory the
verifier spends.

A permissive parser would accept two spellings of one proof, and two spellings is
one spelling too many for a value that is compared byte for byte. Uppercase
hexadecimal is refused rather than folded, because folding would accept two
spellings of one nonce and the nonce is the replay identity.

### What the client proof signs

The client proof signs the exact HTTP request the CLI sends:

```
CONNECTOR-CLIENT-HMAC-SHA256
1
<method>
<request target>
<body digest>
<node proof header digest>
<request id>
<timestamp_ms>
<nonce>
```

One field per line, joined by a single newline, in that order.

| Field | Value |
|---|---|
| `method` | `POST` |
| `request target` | The path and query as sent, for example `/v1/nodes/node_7f3a.../operations` |
| `body digest` | Lowercase SHA-256 hex of the raw body bytes, or the literal `-` when no body is present |
| `node proof header digest` | Lowercase SHA-256 hex of the exact `X-Connector-Node-Auth` value |
| `request id` | The `X-Request-Id` value the CLI sent |
| `timestamp_ms` | The signer's clock reading in milliseconds since the epoch |
| `nonce` | The one-time value the Server records |

Two fields deserve their own explanation.

**The body digest is over raw bytes, not over parsed JSON.** The Server reads the
body, hashes it, and only then decodes it. Signing the parsed form would let two
different byte sequences that decode to the same object share one signature.

**The node proof header digest is what stops a proof swap.** Without it, an
attacker holding a valid client proof could keep it and replace the node proof it
travels with. The Server would verify the client proof, forward the substituted
node proof, and the Node would answer a request the caller never made. Binding the
exact transmitted bytes closes that.

A missing body is represented by the literal `-` rather than by the digest of zero
bytes, so "no body" and "a present zero-byte body" are different requests.
Collapsing them would let one proof be replayed against the other.

### What the node proof signs

The node proof signs the logical operation, not the HTTP serialization:

```
CONNECTOR-NODE-HMAC-SHA256
1
<node id>
<key id>
<operation>
<scope>
<path>
<offset>
<length>
<request id>
<timestamp_ms>
<nonce>
```

One field per line, joined by a single newline, in that order.

The Node receives a request the Server reconstructed from the channel frame, not
the original HTTP bytes, so it cannot reproduce an HTTP serialization. It can
reproduce the logical operation exactly, which is what the proof signs.

Every field occupies one line even when it is empty or zero. An empty `path` and a
zero `offset` are signed as empty and `0`, never omitted, so the CLI and the Node
cannot disagree about a missing field.

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
    "content": "base64...",
    "size": 1024,
    "truncated": false
  },
  "request_id": "req_8bdc0bc0b71db9b534806132fa68408b",
  "timestamp": 1762732800000
}
```

The envelope is the project-wide response format: `code`, `message`, `data`,
`request_id`, `timestamp`. `code` is `0` on success and a non-zero business code
otherwise.

`data` is the Node's own payload, relayed unchanged, so it varies by operation and
carries no envelope fields of its own:

| Operation | `data` fields |
|---|---|
| `file.list` | `entries`: array of `{name, type, size, mode, modified_at, is_symlink, link_target}` |
| `file.stat` | `type`, `size`, `mode`, `modified_at`, `is_symlink`, `link_target` |
| `file.read` | `content` (base64), `size`, `truncated` |

`truncated` reports whether the content was cut off, not whether the response
reached the cap. A file whose size is exactly the cap is returned in full and
reports `false`, because nothing was left behind; a file one byte larger returns
the same number of bytes and reports `true`. The distinction matters to a caller
that stops on `truncated`: deriving the flag from the byte count alone told it a
complete file was partial.

The `request_id` is the caller's correlation id, echoed in the envelope. It is
generated as `req_` followed by 32 lowercase hexadecimal characters, which encode
128 random bits, and it is capped at 128 bytes so a caller-supplied value cannot
grow the log line it appears in.

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
| `1001` | `invalid_argument` | The request is malformed: bad proof grammar, bad scope name, rejected path, bad JSON | No |
| `1002` | `unauthenticated` | A proof is missing, malformed or does not verify, or its timestamp is outside the window, or its nonce was already used | No |
| `1003` | `node_offline` | No live connection for that `node_id` | Yes, later |
| `1004` | `node_timeout` | The Node did not answer within the request timeout | Yes |
| `1005` | `denied` | The Node refused: no grant, or the policy does not allow it | No |
| `1006` | `not_found` | The path does not exist inside the scope | No |
| `1007` | `unsupported_operation` | The operation is unknown or declared but not enabled in this version | No |
| `1008` | `too_large` | The response exceeds the cap, or the request body exceeds the limit | No |
| `1009` | `internal` | The Server failed. Details are logged, not returned | Yes |
| `1010` | `overloaded` | The Server is at its admission limit for this caller, this Node or the whole process, and refused the request instead of queueing it without a bound | Yes |

`denied` and `not_found` are deliberately distinct. Collapsing them would let a
caller probe for the existence of a file it may not read, which is an information
leak dressed as a simpler API.

`unauthenticated` is one code for every authentication failure: a wrong secret, a
missing header, a malformed proof, an expired timestamp and a replayed nonce all
produce it. Distinguishing them would tell an attacker whether a guess was close,
and whether a captured proof was merely stale or structurally wrong.

`internal` never carries a detail string. A detail string is where an absolute
path, a secret fragment or a stack trace reaches a caller, and none of those belong
in a response.

## What the Server validates, and what it must not

The Server validates **shape and its own proof**, because a malformed request
should fail before it costs a round trip to the Node:

- The method is `POST` and the path matches the endpoint.
- The `node_id` in the path is a well-formed identifier.
- The body fits the size limit.
- The `X-Connector-Node-Auth` header is present and non-empty.
- The client proof parses, its `key_id` selects a configured credential, its
  timestamp is inside the replay window, its signature verifies, and its nonce has
  not been seen.
- The `Content-Type` is `application/json`.
- The body decodes, and the operation, scope name and path pass the shape rules.
- The node proof parses as a node-scheme proof.
- A live connection exists for the `node_id`.

The Server must **not** validate authority:

- It does not verify the node proof. It cannot: it never receives the node
  credential secret.
- It does not decide whether the grant covers the operation. That is the Node's
  decision, and a Server that pre-empted it would become an authority for
  operations.
- It does not decode, re-encode, normalise or wrap the node proof. A re-encoded
  value is a derived value, and a derived value is a stored credential index in
  disguise.

### The order is part of the contract

The Server checks the presence of the node proof header before it verifies the
client proof. That is not an oracle: the header belongs to the caller, so learning
that it is missing tells the caller only what it already sent.

What must never happen is the reverse: the Server must not report anything about
node proof **validity** before the client proof verifies, because that would let an
unauthenticated caller use the Server as an oracle for node credentials. It does
not, because it never evaluates node proof validity at all.

## What the Server never does with either secret

- It never writes a client secret, a node secret or a proof signature to a log, a
  trace, an audit record or an error message. An audit record names the `node-id`
  and the `key_id`, never a secret.
- It never receives the node credential secret. The node proof is a signature, and
  a signature is not a secret.
- It never stores a proof beyond the request being forwarded. The value is released
  when the response is written.
- It never stores a hash, prefix or fingerprint of a secret.
- It never claims to have validated the node proof. It relays the Node's refusal,
  because a Server that reported a check it never performed would be lying about
  the one thing the caller relies on.

## Replay protection

A signature proves who built a request. It does not prove the request is fresh, and
it does not stop the same bytes being sent twice. Two mechanisms close that, and
each verifier owns its own copy of both.

| Mechanism | Rule |
|---|---|
| Timestamp window | A proof whose `timestamp_ms` differs from the verifier's clock by more than the window is refused |
| Nonce cache | A nonce is recorded after its signature verifies; a second proof with a recorded nonce is refused |

Defaults, which are the same for both verifiers but configured separately:

| Setting | Default | Maximum |
|---|---|---|
| Window | 60 seconds | 10 minutes |
| Capacity | 65536 unexpired nonces | — |

The window is bounded because an unbounded window is a replay window of unbounded
size. A zero or negative window is a configuration failure rather than a value to
clamp, because a clamped window would silently accept a proof the operator meant to
refuse.

The cache is bounded because an unbounded cache is a memory exhaustion path. When
it is full, the verifier refuses new proofs rather than evicting an unexpired
nonce: evicting one would re-open the replay window for exactly the nonce an
attacker would choose.

### The two caches are independent

The Server records `(client key id, client nonce)`. The Node records
`(node key id, node nonce)`. They are separate because they belong to separate
verifiers with separate clocks, separate windows and separate lifetimes.

A single shared cache would be wrong in both directions: the Server would be
recording state about a proof it cannot verify, and a Node restart would silently
clear the Server's replay protection.

### A retry must regenerate both proofs

A retry is a new request, not a resend. It must carry:

- a new `request id`,
- a new client `timestamp_ms`, `nonce` and `signature`,
- a new node `timestamp_ms`, `nonce` and `signature`.

Reusing either proof fails. Reusing the client proof is refused by the Server;
reusing the node proof is refused by the Node. A client that refreshed only one of
them would see a failure from the verifier it forgot.

### What replay protection does not do

It does not make a plaintext link safe. An attacker who captures a request and
sends it first wins the race: the verifier records the nonce from whichever copy
arrives first, and the legitimate copy is then refused as a replay. Timestamps and
nonces cannot order two identical requests.

TLS remains the mechanism that prevents capture, response theft and response
tampering. HMAC removes the reusable secret from the wire; it does not make the
wire private.

## Routing

The Server keeps an in-memory registry `node_id -> connection`. The registry is
memory only: persisting it would create a record of which Nodes exist and when
they were last seen, which is a privacy decision this design does not make.

- A request for an unknown `node_id` is refused with `node_offline`. It is **not**
  queued. Queueing would turn an immediate refusal into a delayed surprise, and
  the caller would not know whether the request would ever run.
- The path `node_id` selects the connection. The Server does not compare it with
  the node proof, because it cannot read the proof's meaning without the secret.
  The Node compares the signed `node_id` with its own identity and refuses a
  mismatch, which is the only check that can be authoritative.
- One connection serves one Node. A Node that reconnects replaces its registry
  entry, and the previous connection is closed.

## Concurrency

- Requests to one Node are multiplexed over its single channel by `request_id`.
  The Node may answer out of order.
- The Server bounds in-flight requests on three dimensions at once: per caller,
  per Node and for the whole process. A request must satisfy all three. The
  defaults are 2, 4 and 64, configurable through
  `CONNECTOR_SERVER_MAX_IN_FLIGHT_PER_CALLER`,
  `CONNECTOR_SERVER_MAX_IN_FLIGHT_PER_NODE` and
  `CONNECTOR_SERVER_MAX_IN_FLIGHT`.
- The per-Node bound is the one that protects the personal computer the Node runs
  on. The per-caller bound stops one caller from occupying every slot, and the
  process bound stops unbounded growth.
- Admission runs after authentication and after the Node is known to be online, so
  an unauthenticated request cannot occupy a slot and an offline Node cannot hold
  one.
- A request that cannot be admitted waits up to
  `CONNECTOR_SERVER_ADMISSION_WAIT_MS` and is then refused with `overloaded`,
  which is retryable. A wait of `0` refuses immediately.
- `overloaded` is distinct from `internal` on purpose: the condition is temporary
  and the same request will succeed later, while `internal` means the Server has a
  defect and retrying is pointless.
- The counters are per process. Several Server processes enforce the bound per
  process, not across the fleet.
- A request that exceeds `CONNECTOR_SERVER_REQUEST_TIMEOUT_SECONDS` is answered
  with `node_timeout` and its pending entry is removed. The Node's eventual answer
  is discarded, because the caller has already been told the request failed.

## File content transport

The channel carries file content in one of two transports, negotiated once per
connection during the handshake. The transport decides how bytes are framed; it
carries no authority, so authentication, authorization and the path fence are
identical either way.

| Transport | Content encoding | When it is used |
|---|---|---|
| `binary-v1` | Raw bytes in a WebSocket binary frame, with a small JSON header | Both peers offer it |
| JSON (unnamed) | Base64 inside the JSON frame payload | A peer does not offer `binary-v1` |

- The Node advertises the transports it supports in `hello`. The Server selects
  the first version in its own preference order that the Node offered, and reports
  the choice in `hello_confirm`.
- A peer that does not offer `binary-v1` falls back to the JSON transport rather
  than being refused, so an upgrade does not break a deployment whose two halves
  are replaced at different times.
- A peer that offers only a version the Server does not know is refused with
  `invalid_argument` and a message naming both sides, rather than being silently
  treated as JSON.
- The Server records the selected transport in its log as `file_transport=`, so an
  operator can tell which one a connection is using without inspecting traffic.
- The transport is not visible to the CLI. A caller sends the same request and
  receives the same response either way, so a client does not need to know which
  transport is in force.

## CLI surface

The CLI is a subcommand of the Server binary, so an operator installs one binary
and gets both the Server and the client. It has no configuration file: every input
comes from a flag or from an environment variable, and a flag wins over the
environment because a flag is the more explicit statement of intent.

```
connector-server cli --server https://cloud.example:8443 \
    --node-id node_7f3a... \
    --client-credential operator-dawson.5f7k... \
    --node-credential automation-backup.q4ka... \
    --scope project --path notes.md file.read
```

| Flag | Environment | Required | Meaning |
|---|---|---|---|
| `--server` | `CONNECTOR_CLI_SERVER_URL` | yes | Server base URL, `http` or `https` |
| `--node-id` | `CONNECTOR_CLI_NODE_ID` | yes | The identifier the request is for |
| `--client-credential` | `CONNECTOR_CLI_CLIENT_CREDENTIAL` | yes | `key_id.secret` the Server verifies |
| `--node-credential` | `CONNECTOR_CLI_NODE_CREDENTIAL` | yes | `key_id.secret` the Node verifies |
| `--scope` | none | yes | A scope name the Node's policy defines |
| `--path` | none | no | Relative path inside the scope; empty means the scope root |
| `--offset` | none | no | Byte offset for `file.read`, default `0` |
| `--length` | none | no | Byte count for `file.read`; `0` means up to the cap |
| `--request-id` | none | no | Correlation id signed by both proofs; generated when absent |
| `--json` | none | no | Print the whole response envelope instead of the payload |
| `-o`, `--output` | none | no | Write the result to `-` (stdout) or to a local file path |
| `--force` | none | no | Allow `-o` to replace an existing destination file |

The operation name is the one positional argument: `file.list`, `file.stat` or
`file.read`. A second positional argument is refused rather than ignored, because
an ignored argument is a command that did something other than what it looked like
it did. Flags must precede the operation name, because Go's flag parser stops at
the first non-flag argument.

Rules:

- Both credentials are read from the environment as well as from a flag, because a
  script that calls the CLI repeatedly should not repeat a secret on every line.
  **The environment variable is the recommended form**, because a flag value is
  visible in `argv` to every account on the host and is written to shell history by
  default. The flag exists for a script that already holds the secret and would
  otherwise have to export it, and a flag that is present takes precedence over the
  environment variable. That exposure is an accepted trade-off recorded in the
  residual risks of `docs/permission-design.md`.
- The CLI never prints a secret, and it never includes one in an error message.
  `cli.Describe` prints the `node-id` and both `key_id` halves in full because they
  are public, and replaces both secrets with `<redacted>` without revealing a
  prefix or a length.
- The CLI exits non-zero on any error code, so a shell script can branch on it. The
  error code and message go to stderr, and the payload goes to stdout, so
  `file.read` can be piped into another program without stripping a header.
- `file.read` writes the file content to stdout as raw bytes, not as JSON. A
  `--json` flag wraps the whole response envelope for scripting.
- A truncated `file.read` prints a notice on stderr, never on stdout, because a
  notice on stdout corrupts a piped payload.
- The CLI refuses a credential that does not parse as `key_id.secret`, and a
  `--node-id` that is not a well-formed identifier, before sending anything. A
  copy-paste error then surfaces locally instead of as a confusing authentication
  failure from the far side.
- The CLI's own timeout is longer than the Server's forward timeout, so the CLI
  receives the Server's `node_timeout` answer instead of giving up first and
  reporting a network error that hides the real cause.

### Reading a whole file with `-o`

`file.read` returns at most 256 KiB per request, because the Node caps a single
response. Without `-o` the CLI sends exactly one request and prints a truncation
notice on stderr when the file is larger, which is the historical behaviour and is
unchanged.

`-o` changes the question from "give me one chunk" to "give me the whole thing":

| Invocation | Requests | Result |
|---|---|---|
| `file.read` | one | At most 256 KiB, truncation notice on stderr |
| `-o -` `file.read` | until end of file | The whole file on stdout as raw bytes |
| `-o /path/out.bin` `file.read` | until end of file | The whole file written to `/path/out.bin` |
| `--offset 100 --length 5000 -o out` | until the range is read | Bytes `[100, 5100)` written to `out` |
| `-o -` `file.list` / `file.stat` | one | The listing or the metadata, written to the destination |

The loop is driven by the response, not by a hardcoded step size, so a change to the
Node's cap does not require a change in the CLI. It stops when the Node reports that
it reached end of file, when a response delivers zero bytes, or when the `--length`
budget is spent.

`truncated` is trusted only in the safe direction. A `false` value always means end
of file, so stopping on it never drops data. A `true` value is trustworthy as well,
but the loop is written so it does not depend on that: a Node older than the fix in
`a5b580e3` reported truncation for a file whose size is exactly the cap even though
the content was complete, and a loop that treated a `true` value as proof of lost
data would have refused a complete file. The defect is recorded as fixed in
`issues/done/issue-truncated-flag-misreports-an-exact-cap-file.md`; the loop keeps
its independence from that direction so an older Node still yields a correct result
at the cost of one extra request.

A destination that exists always holds a complete result. The CLI writes to a
temporary file in the same directory as the destination and renames it into place
only after every chunk has arrived, so a failure part way through leaves the
destination untouched rather than half written. An existing destination is refused
unless `--force` is given, because replacing a local file is a destructive act the
caller did not ask for by naming a path.

Two path rules appear on one command line and they are not the same rule:

- `--path` is a **remote** path. It is resolved inside the Node's scope and must
  satisfy the Node's path grammar: relative, no `..`, no `.`, no colon, no
  backslash.
- `-o` is a **local** path. It is resolved by the CLI on the caller's machine, so it
  may be absolute and may contain `..`.

`--json` and `-o` are refused together, because one asks for the response envelope
and the other asks for the payload, and a single invocation cannot honour both.
`--force` without `-o` is refused for the same reason: it names a behaviour that
would not happen.

Each chunk is a separately signed request with its own nonce and timestamp, so the
loop needs no protocol change and gains no replay weakness. The one ceiling worth
stating is the Server's replay cache: it holds 65536 nonces for a 60 second window,
so a whole-file read of more than about 16 GiB within one minute would fill it and
the Server would refuse further requests rather than evict an unexpired nonce. That
is a fail-closed limit, not a corruption risk, and it is far beyond a read a person
performs interactively.

## How the operator learns the credentials

The CLI cannot discover either credential. There is no lookup endpoint, because a
lookup endpoint would let any caller enumerate which Nodes exist.

| Credential | Created by | Command | Shown |
|---|---|---|---|
| Client credential | Server operator | `connector-node credential add` with `CONNECTOR_NODE_CONFIG_DIR` pointing at a Server-side directory | Once, at creation |
| Node credential | Node operator | `connector-node credential add` | Once, at creation |
| Node id | The Node, at first start | `connector-node id` | Every time, it is public |

The Server binary has no `credential` subcommand. Its client credential file is
written by the Node binary's `credential add`, pointed at a Server-side directory
through `CONNECTOR_NODE_CONFIG_DIR`:

```
CONNECTOR_NODE_CONFIG_DIR=/etc/connector/server-client \
  connector-node credential add --key-id operator-dawson
```

That is deliberate rather than a gap. The credential file has one format, and one
implementation writes it. A second generator inside the Server binary would be a
second definition of a valid file, and the two would eventually disagree about
what the Server accepts. The command prints the `key_id.secret` value once and
writes `credentials.yaml` into that directory, which is the file
`CONNECTOR_SERVER_CLIENT_CREDENTIALS_FILE` must name.

The ordering constraint is recorded in `docs/permission-design.md`: the Node must
start once before any CLI can reach it, because the Server cannot route to a name
it has never been told.

A credential file may hold several credentials, each with its own `key_id`. That is
what makes rotation a coordinated but non-destructive act: add the new credential,
move the callers, then remove the old one. Removing a credential invalidates it
immediately, because the verifier compares against the set it currently holds and
keeps no history.

`connector-node regenerate` changes the node id, not the credential. A caller that
keeps its credential keeps working; a caller that addressed the old identifier must
be given the new one.

## Related documents

- `docs/permission-design.md` — the three credentials, the path fence, the policy file.
- `docs/Environment_Variables.md` — configuration surface.
