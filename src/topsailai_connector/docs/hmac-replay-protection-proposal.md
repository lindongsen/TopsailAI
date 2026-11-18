---
maintainer: AI
author: DawsonLin
status: proposal
created: 2026-11-18
updated: 2026-11-18
---

# Client and Node HMAC Replay Protection Proposal

## Status

This document is a discussion proposal, not the active protocol contract. The implemented baseline remains the bearer `client_token` and `node-id.node-token` design in `docs/permission-design.md` and `docs/API.md` until the open decisions here are settled and the decided documents, cases, wire contract, implementation, and skills are updated together.

The proposal covers exactly two authentication boundaries:

- CLI to Server authentication currently performed by `client_token`.
- CLI to Node authentication currently performed by `node-token`, with the Server forwarding the operation.

`tunnel_token`, Node-to-Server channel authentication, and the WebSocket `hello` exchange are explicitly outside this proposal.

This proposal prevents transmission and replay of reusable credentials. It does not make request or response content confidential.

## Problem

Today the CLI sends two reusable bearer secrets on each operation request:

- `client_token` in the HTTP `Authorization` header, which the Server verifies;
- `node-token` in `X-Connector-Node-Token`, which the Server reads and forwards to the Node.

The Server does not persist or log either presented value, but it sees both reusable credentials during the request. A passive observer on a plaintext connection also sees both. Neither boundary currently has a caller timestamp, one-time nonce, or caller-generated request identity enforced by its verifier, so a captured credential or complete request remains reusable until rotation.

The current adversarial cases correctly describe replay as an accepted risk. This proposal is intended to replace that behavior for `client_token` and `node-token` only.

## Goals

- The CLI proves possession of a Server client credential without transmitting its secret.
- The CLI proves possession of a Node caller credential without transmitting its secret through the Server.
- The Server verifies the client proof and cannot use the forwarded Node proof to create a new valid Node request.
- The Server and Node independently reject replay at their own authentication boundaries.
- Changing any authenticated HTTP or Node-operation field invalidates the relevant proof.
- The Server and each Node can accept several independently revocable caller credentials.
- Credential identity is auditable without logging secrets, signatures, or nonces.
- Scope and permission remain entirely controlled by the Node policy.
- Memory, storage, and verification cost remain bounded.
- The design behaves consistently on Linux, macOS, and Windows.

## Non-goals

- Changing `tunnel_token` or the channel handshake.
- Hiding methods, URLs, operation names, scope names, paths, file contents, sizes, or responses from the Server.
- Encrypting the CLI-to-Server or Server-to-Node transport.
- Signing Node responses in the first release.
- Protecting against compromise of the CLI or Node host.
- Preventing the Server from dropping, delaying, duplicating, or misrouting traffic. Verifiers can refuse invalid or replayed requests but cannot force delivery.
- Assigning different scopes or permissions to different credentials. Credentials authenticate; policy authorizes.
- Adding `file.write` or `command.exec`.
- Providing exactly-once execution across process restarts.

TLS remains recommended because HMAC protects credential secrecy and request integrity, not message confidentiality. On plaintext transport, observers can still read request metadata and response data.

## Authentication domains

The two domains are independent even though one CLI request carries both proofs.

| Domain | Signer | Verifier | Reusable secret holders | Replay identity |
|---|---|---|---|---|
| Client authentication | CLI | Server | CLI and Server | `(client_key_id, client_nonce)` |
| Node authentication | CLI | Target Node | CLI and target Node | `(node_key_id, node_nonce)` |

The Server client credential permits the caller to use the Server. It grants no Node access.

The Node caller credential proves that the caller may ask the target Node for an operation. It grants no scope or permission. After Node authentication, the Node performs the existing policy check and refuses by default.

The domains use distinct scheme names, timestamps, nonces, signatures, credential stores, replay caches, capacity settings, and logs. A proof from one domain cannot authenticate the other.

## Credential model

Both domains use a copyable credential with the same grammar:

```text
<key_id>.<secret>
```

Examples:

```text
client credential: operator-dawson.5f7k...
node credential:   backup-service.q4ka...
```

- `key_id` is public. It selects one secret and may appear in audit logs.
- `secret` is the only secret half. It never leaves its signer and verifier.
- The CLI derives `key_id` by splitting the credential, so a second setting cannot drift out of sync.
- Client and Node key IDs live in separate namespaces. The same spelling in both domains does not identify the same credential.

The Node's public `node_id` remains separate from the Node caller credential. The active `node-id.node-token` form is the migration source, not the proposed long-term credential grammar.

### Proposed bounds

The following initial values are proposals, not settled decisions:

- Maximum active client credentials per Server: 32.
- Maximum active Node credentials per Node: 32.
- `key_id` length: 1 to 64 ASCII characters.
- `key_id` alphabet: lowercase letters, digits, `-`, and `_`.
- Secret entropy: 256 random bits, encoded with the existing lowercase unpadded base32 alphabet.
- Exactly one dot in the copyable credential.
- Duplicate key IDs in one domain: configuration load failure.
- Empty, malformed, overlong, or unknown credentials: refusal.

Each verifier performs one direct map lookup by `key_id`; it never tries every configured secret.

## HTTP request format

One CLI operation carries both proofs:

```http
POST /v1/nodes/node_7f3a.../operations HTTP/1.1
Host: connector.example.com
Content-Type: application/json
X-Request-Id: req_8c7419d379344f388bcbaf7fb981c246
Authorization: CONNECTOR-CLIENT-HMAC-SHA256 version=1,key_id=operator-dawson,timestamp_ms=1794470400000,nonce=481af01e3f5a0fbaf99d07455137e1b6,signature=<64-lowercase-hex>
X-Connector-Node-Auth: CONNECTOR-NODE-HMAC-SHA256 version=1,key_id=backup-service,timestamp_ms=1794470400000,nonce=a3f9c1d2e4b50718de913f826a5c74e1,signature=<64-lowercase-hex>

{
  "operation": "file.read",
  "scope": "project",
  "path": "docs/readme.md",
  "offset": 0,
  "length": 262144
}
```

`X-Request-Id` is generated by the CLI and signed by both domains. Proposed grammar:

```text
req_ + 32 lowercase hexadecimal characters
```

It is distinct from the Server's internal `wire_...` correlation ID. The Server forwards the caller request ID unchanged and may generate a separate wire ID for pending-response routing.

### Authentication header grammar

Both proof headers use the same strict field grammar with different fixed scheme names:

```text
<scheme> version=1,key_id=<key-id>,timestamp_ms=<decimal>,nonce=<32-lowercase-hex>,signature=<64-lowercase-hex>
```

The parser rejects:

- missing, duplicate, or unknown fields;
- unsupported or case-changed schemes;
- unsupported versions;
- leading or trailing whitespace in values;
- control characters or line breaks;
- malformed decimal values;
- malformed, uppercase, short, or overlong hexadecimal nonce or signature values;
- extra separators or permissive alternate spellings.

The header is parsed, not normalized or repaired.

## Client proof

The client proof protects the HTTP boundary from CLI to Server.

### Canonical client request

The CLI signs the exact HTTP request body bytes and the exact `X-Connector-Node-Auth` header value it sends. The Server computes both digests from bounded raw bytes before JSON decoding or Node-proof parsing. Binding the Node proof prevents an attacker from replacing it while retaining a valid client proof.

The canonical UTF-8 string is newline-separated in this exact order, with no final newline:

```text
CONNECTOR-CLIENT-HMAC-SHA256
1
<METHOD uppercase>
<request path with raw query, or path alone when no query>
<lowercase SHA-256 hex of raw body bytes, or literal - when no body exists>
<lowercase SHA-256 hex of the exact X-Connector-Node-Auth header value bytes>
<request_id>
<client_timestamp_ms decimal>
<client_nonce lowercase hex>
```

The signature is:

```text
client_signature = HMAC-SHA256(client_secret, canonical_client_request)
```

The signature is encoded as 64 lowercase hexadecimal characters and compared with `hmac.Equal`.

Rules:

- Method, path, query, body bytes, complete Node proof, request ID, timestamp, and nonce are all bound.
- The request body and Node proof header are bounded before hashing and decoding.
- A missing body uses literal `-`; a present zero-byte body uses the SHA-256 digest of zero bytes. They are different requests.
- The Node proof header is required and its exact transmitted bytes are hashed; intermediary normalization is not tolerated.
- Redirects are not followed automatically when they would change the signed method, URL, body, or proof headers.
- A proxy must not rewrite the signed path, query, or authentication headers between the CLI and Server. Deployment documentation must state the public path that the Server verifies.

## Node proof

The Node proof protects the logical operation from CLI to target Node. It cannot sign raw HTTP bytes because the Node receives a reconstructed channel request rather than the original HTTP serialization.

### Canonical Node operation

The canonical UTF-8 string is newline-separated in this exact order, with no final newline:

```text
CONNECTOR-NODE-HMAC-SHA256
1
<node_id>
<node_key_id>
<operation>
<scope>
<path>
<offset decimal>
<length decimal>
<request_id>
<node_timestamp_ms decimal>
<node_nonce lowercase hex>
```

The signature is:

```text
node_signature = HMAC-SHA256(node_secret, canonical_node_operation)
```

Rules:

- Every field occupies one line, including empty path and zero numeric values.
- Values are signed exactly as accepted by the wire grammar; they are not trimmed, cleaned, case-folded, or path-normalized first.
- Newlines are rejected in every signed textual field.
- Numeric fields use canonical non-negative base-10 spelling with no sign, prefix, or leading zeros except the single value `0`.
- `node_id` and `node_key_id` are signed, so a proof cannot be moved to another Node or credential identity.
- Every operation input is signed. Enabling an operation with new input fields requires a new reviewed canonical version.
- The format version is signed. Unsupported versions are refused without fallback.

## Server-to-Node representation

After validating the client proof, the Server removes it and forwards the Node proof unchanged with the logical operation:

```json
{
  "node_id": "node_7f3a...",
  "request_id": "req_8c7419d379344f388bcbaf7fb981c246",
  "operation": "file.read",
  "scope": "project",
  "path": "docs/readme.md",
  "offset": 0,
  "length": 262144,
  "node_auth": {
    "scheme": "CONNECTOR-NODE-HMAC-SHA256",
    "version": 1,
    "key_id": "backup-service",
    "timestamp_ms": 1794470400000,
    "nonce": "a3f9c1d2e4b50718de913f826a5c74e1",
    "signature": "<64-lowercase-hex>"
  }
}
```

The outer channel frame retains a separate Server-generated wire correlation ID. The Server must:

- validate the client proof before forwarding;
- receive no secret in the HTTP request and never receive the Node secret at all;
- retain the configured client secret only as the verifier for client proofs;
- never forward the client proof to the Node;
- forward every Node-signed field and Node proof field unchanged;
- never replace the signed caller request ID;
- reject malformed or oversized Node-proof envelopes without claiming to verify the Node HMAC;
- never fall back to bearer authentication after a proof failure.

The Node is the only Node-proof verifier. The Server may validate Node-proof shape and size only.

## Replay protection

HMAC alone does not prevent replay. Each verifier independently applies a timestamp window and nonce cache.

### Independent timestamps

The request carries `client_timestamp_ms` in the client proof and `node_timestamp_ms` in the Node proof. The CLI may generate equal values, but the protocol treats them independently.

Each verifier accepts only when:

```text
absolute(verifier_now_ms - proof_timestamp_ms) <= verifier_replay_window_ms
```

Proposed initial default for both domains: 60 seconds. The final defaults and maximums remain open.

The verifier owns its window. A request cannot choose or widen it. Zero, negative, and excessive configured values are startup or reload failures rather than values to clamp silently.

### Independent nonces

The CLI generates a cryptographically random 128-bit nonce for each domain and each attempt:

```text
client_nonce: 32 lowercase hexadecimal characters
node_nonce:   32 lowercase hexadecimal characters
```

The Server records:

```text
(client_key_id, client_nonce) -> expiry
```

The Node records:

```text
(node_key_id, node_nonce) -> expiry
```

The check-and-insert operation must be atomic so concurrent copies cannot both pass. A bad signature never reserves a nonce.

### Verification order

Server:

1. Bound and read the raw HTTP body.
2. Validate client-proof shape and bounds.
3. Look up `client_key_id`.
4. Check `client_timestamp_ms`.
5. Reconstruct and verify the client HMAC.
6. Atomically reject or record `(client_key_id, client_nonce)`.
7. Decode and validate the operation and Node-proof shape.
8. Forward the logical operation and Node proof.

Node:

1. Validate Node-proof shape and bounds.
2. Look up `node_key_id`.
3. Check `node_timestamp_ms`.
4. Reconstruct and verify the Node HMAC.
5. Atomically reject or record `(node_key_id, node_nonce)`.
6. Check Node policy for operation and scope.
7. Perform the operation.

### Cache bounds and full behavior

Each replay cache is separately bounded by its credential count, expected accepted request rate, replay window, and memory budget. Cleanup must not require scanning unbounded history on every request.

If a cache is full while unexpired entries remain, its verifier fails closed. It does not evict a live nonce to admit another request because eviction would reopen replay for the evicted proof.

The Server cache must account for all client credentials and concurrent CLI traffic. Each Node cache accounts only for that Node's caller credentials and traffic.

### Restart limitation

Both in-memory caches are empty after their verifier restarts:

- Server restart can permit replay of a client proof still inside the Server window.
- Node restart can permit replay of a Node proof still inside the Node window.

For current read-only operations and short windows, either or both may be accepted as documented residual risks. They are not acceptable by default for future mutations. Before enabling `file.write` or `command.exec`, the design must choose durable deduplication, operation idempotency, or another restart-safe mechanism.

### Retries

Every CLI retry creates a new:

- caller request ID;
- client timestamp, nonce, and signature;
- Node timestamp, nonce, and signature.

Reusing only one old proof is refused at that proof's verifier. Resending the complete old request is replay and must be refused.

This provides at-most-once admission within each running verifier and replay window, not exactly-once execution. A request may execute and its response may be lost.

## Credential storage

HMAC verification requires the original secret. A one-way digest cannot recompute an HMAC, and using a stored digest as the HMAC key merely turns the digest into an equivalent reusable credential.

### Server client credential store

The Server needs a strict mapping:

```text
client_key_id -> client_secret
```

The current single `CONNECTOR_SERVER_CLIENT_TOKEN` environment variable cannot express multiple credentials, public IDs, or atomic set replacement. The final source remains an open decision. Options include a private credential file or one explicitly defined environment representation; secrets must not be duplicated across several precedence layers.

### Node caller credential store

The Node needs a strict mapping:

```text
node_key_id -> node_secret
```

This set should be separate from `policy.yaml` so authentication material and authorization rules do not share one distribution lifecycle. A proposed local layout is:

```text
<config>/identity
<config>/credentials.yaml
<config>/policy.yaml
```

### Shared storage requirements

Both stores require:

- private access for the service account on each supported platform;
- no secret in logs, errors, startup summaries, audit records, generated policy, or configuration dumps;
- strict parsing with unknown fields and duplicate key IDs refused;
- bounded file or environment size and bounded credential count;
- atomic replacement;
- all-or-nothing reload, preserving the previous effective set after failure;
- no automatic fallback to another source or authentication mode.

On Windows, ACL behavior and failure policy must be designed explicitly; POSIX mode `0600` is not a complete Windows access-control statement.

## Credential lifecycle

Client credentials and Node credentials are independently created, distributed, listed by public ID, rotated, and revoked.

Required operator capabilities:

- add a credential and reveal `key_id.secret` once;
- list public key IDs without secrets;
- rotate one key ID, replacing its secret;
- revoke one key ID;
- add a replacement under a new key ID, migrate its caller, then revoke the old key.

A credential carries no scope or permission. Revocation means only that the key no longer authenticates requests at its domain.

The safer overlap model is one secret per key ID. Rotation overlap uses two distinct key IDs so logs and revocation remain unambiguous. Whether management occurs through commands, private files, or deployment tooling remains open.

## Runtime reload

The Server and Node each publish a complete immutable credential snapshot atomically. One request reads one snapshot once, so key lookup and HMAC verification cannot straddle reload.

- Client credential changes affect Server request authentication and do not alter Node channels.
- Node caller credential changes affect Node request authentication and do not by themselves alter the Node-to-Server channel.
- `tunnel_token` and channel behavior are outside this proposal and remain unchanged.

A failed reload preserves the previous snapshot. A removed or rotated secret is not retained as authentication history. Replay entries may remain until normal expiry because they are bounded and contain no reusable secret.

## Threat analysis

### Passive network observer

With bearer authentication, an observer can copy reusable credentials. With both HMAC proofs, a passive observer sees request-specific proof material but cannot derive either secret or sign a new request. A replay after the legitimate request has been admitted is rejected while its nonce remains recorded and after expiration by the timestamp window.

The observer still sees all plaintext operation metadata and response data when TLS is absent.

### Active network attacker and first-use race

Timestamp and nonce checks do not distinguish the original request from an identical captured copy. If an active attacker on a plaintext path delivers the copy before the legitimate request reaches the verifier, the attacker's copy may be admitted first and the legitimate request then refused as replay. HMAC prevents modification and reusable-secret theft; it does not provide channel confidentiality, peer endpoint authentication, or priority for the original sender.

TLS remains required to prevent on-path capture, first-use racing, response theft, and response modification. HMAC is defense in depth and protects reusable credentials when plaintext is unavoidable; it is not a replacement for TLS.

### Compromised Server

The Server necessarily stores client credential secrets because it verifies client proofs. A compromised Server can therefore impersonate a Server client toward itself; HMAC cannot protect a verifier from compromise.

The Server does not store or receive Node credential secrets. A compromised Server can observe, delay, drop, duplicate, reorder, or replay Node-signed operations and can falsify unsigned responses. It cannot alter a signed Node operation or generate a proof for a new operation intent without the Node secret.

### Compromised Node

The Node stores its caller secrets and policy. A compromised Node can impersonate its callers toward itself and expose files within its host authority. This proposal does not protect a compromised endpoint.

## Response integrity

This proposal authenticates requests only. The Server can still alter a response or substitute bytes from another response if transport or application protection does not catch it.

Response signing may later bind response code and data digest to the caller request ID, but it is outside the first release. It must not be presented as part of token replay protection already delivered.

## Authentication failures and logging

Each verifier should classify internally:

- malformed proof;
- unknown key ID;
- timestamp outside the window;
- bad signature;
- replayed nonce;
- replay cache unavailable or full;
- mode or version mismatch.

Server logs may include client key ID, request ID, target Node ID, and refusal class. Node logs may include Node key ID, request ID, operation, scope, and refusal class.

Neither side logs secrets, signatures, or nonces. Although signatures and nonces are not reusable long-term secrets, logging them creates a replay corpus and unnecessary credential-derived data.

The external error mapping remains open. Actionable operator logs and deliberately coarse caller responses can coexist.

## Compatibility and migration

There is no automatic fallback from HMAC to bearer. A proof that fails HMAC verification fails authentication.

Migration must be controlled independently for the two domains, but a CLI request can succeed only when its proof mode matches both verifiers.

Possible rollout:

1. Ship binaries capable of both explicit bearer and HMAC modes while existing deployments remain explicitly bearer.
2. Provision client HMAC credentials on the Server and matching CLIs.
3. Switch CLI-to-Server authentication to HMAC without changing Node authentication.
4. Provision Node HMAC credentials on one Node and matching CLIs.
5. Switch that Node and its callers to Node HMAC.
6. Repeat per Node.
7. Disable bearer modes and remove compatibility code after the migration deadline.

During migration, one boundary may be HMAC while the other remains explicitly bearer. One boundary must never accept both syntaxes as fallback on the same request.

The exact migration order, configuration surface, and compatibility duration remain product decisions.

## Scale assumptions to decide

Before implementation, decide or measure independently for Server and Node:

- active credentials;
- peak accepted requests per second;
- concurrent requests;
- allowed clock skew;
- default and maximum replay windows;
- restart frequency;
- replay-cache memory budget;
- retry behavior during disconnection and timeout.

Verification remains constant-time with respect to credential count after map lookup. Cleanup must not scan unbounded collections on every request.

## Validation plan

### Shared unit checks

- Credential parsing accepts exactly one bounded `key_id.secret` pair.
- Header parsing rejects missing, duplicate, unknown, malformed, and alternate fields.
- Correct HMAC verifies; a wrong signature does not.
- Changing each signed field individually invalidates its proof.
- Timestamp boundaries pass exactly at the configured limit and fail immediately outside it.
- Bad signatures do not reserve nonces.
- Concurrent duplicate proofs result in one admission and one replay refusal.
- A full cache fails closed without evicting a live entry.
- Expired entries are removed and memory remains bounded.
- Unsupported scheme, version, and mode are refused without fallback.
- Credential reload is atomic and failure preserves the old snapshot.
- Removing one key does not invalidate unrelated keys.

### Client-domain checks

- The raw body digest is computed before JSON decoding and matches the bytes sent by the CLI.
- The complete `X-Connector-Node-Auth` header digest is computed from the exact bounded bytes sent by the CLI.
- Changing method, path, query, body bytes, complete Node proof header, request ID, timestamp, nonce, or client key ID invalidates the client proof.
- A missing body and present zero-byte body have different canonical values.
- The client proof is not forwarded to the Node.
- A replayed client nonce is refused by the Server.

### Node-domain checks

- Changing target Node, Node key ID, operation, scope, path, offset, length, request ID, timestamp, or nonce invalidates the Node proof.
- Empty path and numeric zero have one canonical representation.
- The Server forwards the Node proof and signed fields unchanged.
- The Server never receives the Node secret.
- A replayed Node nonce is refused by the Node.
- Authentication success still proceeds through Node policy and carries no permission.

### Integration checks

- One CLI builds two proofs; the Server verifies one, forwards the other, and the Node verifies and executes an allowed read.
- Replaying the complete HTTP request is refused at the Server.
- Rewrapping a captured Node proof in a fresh valid client proof is refused at the Node.
- Reusing a captured client proof with a fresh Node proof is refused at the Server.
- A retry with fresh request ID and both fresh proofs succeeds when policy allows it.
- Rotation or revocation in one domain leaves unrelated credentials and the other domain unaffected.
- Linux, macOS, and Windows build identical canonical bytes for the same logical inputs.
- No secret, signature, or nonce appears in captured logs.

### Negative proof

Break each guard one at a time and confirm its matching test fails: client signed-field coverage, Node signed-field coverage, both timestamp checks, both HMAC comparisons, both atomic nonce insertions, both cache-full paths, mode gates, and credential reload atomicity.

## Documents and cases affected after approval

Acceptance requires coordinated updates to at least:

- `MEMORY.md` for binding human decisions;
- `docs/permission-design.md`;
- `docs/API.md`;
- `docs/Environment_Variables.md`;
- `README.md` and first-run examples;
- `docs/cases/AdversarialCase_secrets.md`;
- `docs/cases/AdversarialCase_node-authority.md`;
- `docs/cases/TestCase_node-id-pair.md`;
- `docs/cases/TestCase_secret-gates.md`;
- `docs/cases/TestCase_cli-and-routing.md`;
- client, Node setup, and Server operations skills.

The active documents currently state bearer headers, single secrets, and successful replay. They must not be partly updated before implementation because that would document an interface users cannot run.

## Open decisions

- Are multiple client and Node credentials permanent caller identities or only rotation overlap?
- What commands or deployment interfaces create, list, rotate, revoke, and reload each credential set?
- What are the final maximum credential counts and key ID bounds?
- Does the Node operator configure `node_id` and `key_id.secret` separately, or receive another single copyable form?
- Is the proposed one-header grammar accepted for both proof domains?
- Are `CONNECTOR-CLIENT-HMAC-SHA256` and `CONNECTOR-NODE-HMAC-SHA256` the final scheme names?
- Is `req_` plus 128 random bits the final caller request ID grammar?
- What are the default and maximum replay windows for Server and Node?
- What peak rates and cache memory budgets must Server and Node support?
- Are cross-restart replays inside short windows accepted for read-only operations at each verifier?
- How are Server client credentials stored and reloaded without creating conflicting configuration sources?
- How are Node caller credentials stored and reloaded?
- How long do explicit bearer compatibility modes remain?
- Which failure classes are externally visible and which are log-only?
- Is response signing explicitly deferred to a later release?

These decisions must be settled before converting this proposal into active permission and API contracts.

## Reference

This proposal adapts the reusable guidance in the topsailai-data note `note--hmac-request-signing-practice`: proof of possession instead of transmitting bearer secrets, fixed canonical inputs, verifier-owned timestamp windows, bounded nonce caches, signature verification before nonce insertion, explicit modes without fallback, and secure retention of original HMAC secrets.
