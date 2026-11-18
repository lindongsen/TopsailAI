---
maintainer: AI
author: DawsonLin
status: draft
created: 2026-11-18
updated: 2026-11-18
---

# Client and Node Credential Replay Protection Product Requirements

## Document status

This PRD is a discussion draft. It defines desired product behavior for HMAC proof of possession and replay protection for `client_token` and `node-token`. It explicitly excludes `tunnel_token` and does not replace the implemented bearer contract until the open decisions are resolved and the proposal is accepted.

The supporting technical design is `docs/hmac-replay-protection-proposal.md`.

## Overview

### Background and motivation

The current CLI sends a reusable `client_token` to the Server and a reusable `node-token` through the Server to the Node. The Server does not persist or log the presented values, but it sees both credentials during each request. A passive observer on plaintext transport can capture them. Neither verifier currently enforces a caller timestamp and one-time nonce, so captured credentials and requests remain replayable until rotation.

The product needs two independent proofs:

- a client proof that lets the Server verify CLI access without receiving the client secret;
- a Node proof that lets the target Node verify caller access without exposing the Node secret to the Server.

Both boundaries need independent freshness and replay enforcement. Both verifier types should support independently revocable credentials so one caller can be rotated or removed without interrupting every caller.

### Product goals

- Keep client credential secrets out of CLI-to-Server requests.
- Keep Node credential secrets out of the Server request path.
- Reject replay independently at the Server and Node boundaries.
- Authenticate every request-defining field at the boundary that consumes it.
- Let Server and Node operators manage callers independently by public credential ID.
- Preserve the rule that Node policy is the only source of scopes and permissions.
- Provide safe, actionable diagnostics without recording secrets, signatures, or nonces.
- Keep credential lookup, replay state, reload behavior, and cleanup bounded.
- Behave consistently on Linux, macOS, and Windows.

### Success measures

The release is successful when all of the following are demonstrated:

- No client or Node credential secret appears in HTTP requests, channel frames, logs, traces, errors, or audit records.
- Replaying a complete accepted HTTP request is refused by the Server.
- Wrapping a captured Node proof in a fresh valid client proof is refused by the Node.
- Changing any field protected by either proof causes that proof to fail.
- Rotating or revoking one credential leaves unrelated credentials and the other authentication domain usable.
- Each credential lookup is direct rather than a scan through configured secrets.
- Both replay caches remain within documented memory bounds under expected traffic.
- Linux, macOS, and Windows produce identical canonical authentication bytes for identical logical inputs.

### Scope

This release includes:

- multiple client credentials on the Server;
- multiple caller credentials on each Node;
- client HMAC proof for CLI-to-Server authentication;
- Node HMAC proof for CLI-to-Node authentication through the Server;
- independent timestamps, nonces, replay windows, and replay caches;
- strict proof parsing and canonical request formats;
- credential creation, public listing, rotation, revocation, and safe reload behavior;
- explicit bearer migration without silent fallback;
- safe diagnostics and bounded replay state.

This release does not include:

- any `tunnel_token` or channel-handshake change;
- request or response encryption;
- Node response signing;
- token-specific scopes or permissions;
- `file.write` or `command.exec`;
- exactly-once execution across verifier restarts.

## Personas

| Persona | Identity | Core goal | Main pain point |
|---|---|---|---|
| Server operator | Person operating the cloud Server | Control which clients can call the Server and revoke one caller safely | One shared bearer `client_token` couples all clients and can be replayed after capture |
| Node operator | Person owning and running a Node | Control which callers can authenticate to that Node independently | One bearer `node-token` is exposed to the Server and shared rotation disrupts every caller |
| CLI user or automation owner | Person or service calling a Node | Authenticate both boundaries without transmitting reusable secrets | A single operation currently exposes two bearer credentials along its route |
| Security reviewer | Person reviewing protocol and operational risk | Verify complete signed-field coverage and fail-closed replay behavior | Two authentication boundaries can drift or be incorrectly treated as one |

## User stories

### Server operator

- **US-001:** As a Server operator, I want multiple client credentials with public identifiers so I can identify and revoke one Server caller independently.
- **US-002:** As a Server operator, I want replayed client proofs rejected so a captured HTTP request cannot be reused.
- **US-003:** As a Server operator, I want invalid client credential reloads to preserve the previous set so an editing error does not break every caller.

### Node operator

- **US-004:** As a Node operator, I want multiple Node caller credentials so I can rotate or revoke one caller without disrupting others.
- **US-005:** As a Node operator, I want replayed Node proofs rejected even when the Server wraps them in a fresh request.
- **US-006:** As a Node operator, I want credentials to remain separate from policy so authentication cannot grant itself a scope or permission.

### CLI user or automation owner

- **US-007:** As a CLI user, I want the CLI to prove possession of both credentials without transmitting either secret.
- **US-008:** As an automation owner, I want retries to generate fresh authentication material for both boundaries so legitimate retries are not replays.
- **US-009:** As a CLI user, I want the same request behavior on Linux, macOS, and Windows so scripts are portable.

### Security reviewer

- **US-010:** As a security reviewer, I want client proof to bind the HTTP method, target, body, request ID, and freshness fields so the request cannot be repurposed.
- **US-011:** As a security reviewer, I want Node proof to bind the target Node and complete operation intent so the Server cannot create or modify a valid Node request.
- **US-012:** As a security reviewer, I want independent bounded replay state and no authentication downgrade so resource pressure or migration cannot reopen bearer risk.

## User journey

1. The Server operator creates a client credential and distributes it once to one CLI caller.
2. The Node operator creates a Node caller credential and distributes it once to the same caller.
3. The CLI stores `client_key_id.client_secret`, `node_id`, and `node_key_id.node_secret`.
4. For each operation, the CLI generates one caller request ID and independent client and Node timestamps, nonces, and signatures.
5. The Server verifies client proof and replay state, removes that proof, and forwards the unchanged Node operation and proof.
6. The Node verifies Node proof and replay state, then evaluates local policy and performs an allowed operation.
7. Each operator can list public key IDs, rotate one credential, or revoke one credential without exposing secrets or affecting unrelated callers.

## Functional requirements

| ID | Feature | Stories | Description | Inputs | Outputs and interaction |
|---|---|---|---|---|---|
| F-001 | Manage multiple client credentials | US-001, US-003 | The Server maintains a bounded set of independently identifiable client credentials | Client key ID and generated secret | One-time credential output, public-only listing, independent rotation and revocation |
| F-002 | Create and verify client HMAC proof | US-002, US-007, US-010 | The CLI signs the HTTP request and complete Node proof header, and the Server verifies them without receiving the client secret | Method, path/query, raw body digest, complete Node proof header digest, request ID, client timestamp and nonce | Authenticated Server request or refusal |
| F-003 | Reject client replay | US-002, US-008, US-012 | The Server enforces a verifier-owned window and atomic client nonce cache | Client key ID, timestamp, nonce, proof result | One admission; expired or duplicate proofs refused |
| F-004 | Manage multiple Node credentials | US-004, US-006 | Each Node maintains a bounded set of independently identifiable caller credentials | Node key ID and generated secret | One-time credential output, public-only listing, independent rotation and revocation |
| F-005 | Create and verify Node HMAC proof | US-005, US-007, US-011 | The CLI signs logical operation intent and the Node verifies it without exposing the secret to the Server | Node and operation fields, request ID, Node timestamp and nonce | Authenticated Node request or refusal |
| F-006 | Reject Node replay | US-005, US-008, US-012 | The Node enforces its own window and atomic Node nonce cache | Node key ID, timestamp, nonce, proof result | One admission; expired or duplicate proofs refused |
| F-007 | Forward Node proof without secrets | US-007, US-011 | The Server removes client proof and forwards Node-signed fields and proof unchanged | Valid client request and Node proof | Target Node receives unchanged logical proof; no secret reaches Server transport |
| F-008 | Keep authentication separate from authorization | US-006, US-011 | Node credential success leads to policy evaluation and carries no grant | Authenticated request and Node policy | Existing default-deny policy decision |
| F-009 | Reload credential sets atomically | US-003, US-004 | Each verifier publishes a complete valid credential snapshot and preserves the previous one on failure | Replacement credential set | All-or-nothing active set without mixed versions |
| F-010 | Diagnose and migrate safely | US-003, US-009, US-012 | Operators receive safe failure classes and authentication modes never fall back | Configured modes, proof syntax, refusal context | Actionable non-secret diagnostics and explicit migration behavior |

## Non-functional requirements

| Dimension | Requirement |
|---|---|
| Security | Both proofs use HMAC-SHA256 and constant-time comparison. Secrets never appear in transport or diagnostics. Each domain has a unique fixed scheme and no fallback. Node credentials never carry permission. |
| Performance | Credential selection is one map lookup. HMAC verification and nonce insertion are constant per request. Cleanup does not scan unbounded history on each request. |
| Capacity | Client and Node credential counts, proof field lengths, replay windows, and live replay entries have explicit limits. A full cache fails closed without evicting live entries. |
| Reliability | Credential reload is atomic. Failed reload preserves the previous set. Losing a response never authorizes reuse of an old proof. |
| Compatibility | Canonical bytes are identical on Linux, macOS, and Windows. Unsupported schemes, versions, modes, and alternate encodings are refused. |
| Observability | Logs identify public key ID, request ID, domain, and refusal class where useful; they exclude secrets, signatures, and nonces. |
| Maintainability | Client and Node canonical formats are separately versioned. Adding a signed field requires matching implementation and cross-platform golden tests. |
| Privacy | HMAC is not encryption. The Server still observes operation metadata and response data. Documentation continues to recommend TLS. |

## Functional dependencies

```text
F-001 Client credentials
  └── F-002 Client proof
        └── F-003 Client replay protection

F-004 Node credentials
  └── F-005 Node proof
        ├── F-006 Node replay protection
        └── F-008 Policy separation

F-007 connects the verified client boundary to the Node proof boundary.
F-009 supports lifecycle changes in F-001 and F-004.
F-010 governs diagnostics and rollout for F-001 through F-009.
```

## MoSCoW priority

| ID | Feature | Priority | Reason |
|---|---|---|---|
| F-001 | Manage multiple client credentials | Must | Public IDs and independent revocation are required for safe client proof selection and rotation |
| F-002 | Create and verify client HMAC proof | Must | Otherwise `client_token` remains a reusable bearer credential on the wire |
| F-003 | Reject client replay | Must | HMAC alone does not stop captured HTTP requests from being resent |
| F-004 | Manage multiple Node credentials | Must | Independent Node callers and direct proof-key selection are core requirements |
| F-005 | Create and verify Node HMAC proof | Must | Otherwise the Server still receives a reusable Node credential |
| F-006 | Reject Node replay | Must | A compromised Server could otherwise resend captured valid Node proofs |
| F-007 | Forward Node proof without secrets | Must | This preserves the Server-as-router boundary and complete signed intent |
| F-008 | Keep authentication separate from authorization | Must | Authentication must never become a second source of scope or permission |
| F-009 | Reload credential sets atomically | Should | Safe rotation matters, but restart-based adoption can temporarily substitute |
| F-010 | Diagnose and migrate safely | Should | Controlled rollout is important, while a coordinated hard cutover is a possible alternative |

Must features are 8 of 10 total features, or 80.0%.

## Release recommendation

### Initial release

Deliver F-001 through F-008. Enforce the no-fallback portion of F-010 from the first HMAC-capable release even if full migration tooling follows later.

### Follow-up release

Deliver F-009 and F-010 in full, including safe live reload, diagnostics, and removal of transitional bearer modes.

## Acceptance criteria

### F-001 Manage multiple client credentials

**AC-F001-01: Create independent client credentials**\
Given the Server has capacity for another credential\
When the operator creates two credentials with different public key IDs\
Then both callers can authenticate independently and neither receives the other's secret.

**AC-F001-02: Reject duplicate client key ID**\
Given a client key ID already exists\
When another credential with that ID is created or loaded\
Then the operation fails and the existing credential remains unchanged.

**AC-F001-03: Enforce client credential limit**\
Given the Server holds the maximum active client credentials\
When another is added\
Then it is refused without removing or replacing an existing credential.

**AC-F001-04: Revoke one Server caller**\
Given two callers have distinct client credentials\
When one credential is revoked\
Then that caller fails Server authentication and the other remains usable.

### F-002 Create and verify client HMAC proof

**AC-F002-01: Authenticate without transmitting client secret**\
Given the CLI and Server share a valid client credential\
When the CLI sends an operation request\
Then the Server verifies a request-specific proof and no request field contains the client secret.

**AC-F002-02: Bind every client request field and Node proof**\
Given a valid client proof\
When the method, path, raw query, body bytes, complete Node proof header, request ID, client key ID, timestamp, or nonce changes\
Then the original proof fails.

**AC-F002-03: Distinguish missing and zero-byte bodies**\
Given one request has no body and another has a present zero-byte body\
When their canonical values are built\
Then they use different body markers and cannot share one proof.

**AC-F002-04: Reject unsupported client proof syntax**\
Given a proof has an unknown scheme, version, field, duplicate field, or alternate encoding\
When the Server parses it\
Then it is refused without repair or fallback.

### F-003 Reject client replay

**AC-F003-01: Refuse complete HTTP replay**\
Given a valid HTTP request has been admitted\
When the same request is sent again inside the client replay window\
Then the Server refuses it and does not forward it.

**AC-F003-02: Admit one concurrent client proof**\
Given two identical valid HTTP requests arrive concurrently\
When both attempt nonce admission\
Then exactly one is admitted and the other is refused.

**AC-F003-03: Do not reserve client nonce for bad signature**\
Given a forged proof uses a nonce later used by a legitimate request\
When the forged proof fails and the valid request arrives\
Then the failed proof has not reserved the nonce and the valid request can proceed.

**AC-F003-04: Fail closed when Server replay cache is full**\
Given the Server cache contains its maximum unexpired entries\
When another otherwise valid new proof arrives\
Then it is refused without evicting a live nonce.

### F-004 Manage multiple Node credentials

**AC-F004-01: Create independent Node credentials**\
Given a Node has capacity for another credential\
When its operator creates two credentials with different Node key IDs\
Then both callers can authenticate independently and neither receives the other's secret.

**AC-F004-02: Reject duplicate Node key ID**\
Given a Node key ID already exists\
When another credential with that ID is created or loaded\
Then the operation fails and the existing credential remains unchanged.

**AC-F004-03: Enforce Node credential limit**\
Given the Node holds the maximum active credentials\
When another is added\
Then it is refused without removing or replacing an existing credential.

**AC-F004-04: Revoke one Node caller**\
Given two callers have distinct Node credentials\
When one credential is revoked\
Then that caller fails Node authentication and the other remains usable.

### F-005 Create and verify Node HMAC proof

**AC-F005-01: Authenticate without transmitting Node secret**\
Given the CLI and Node share a valid Node credential\
When the CLI sends an operation through the Server\
Then the Node verifies a request-specific proof and the Server never receives the Node secret.

**AC-F005-02: Bind every Node operation field**\
Given a valid Node proof\
When the target Node, Node key ID, operation, scope, path, offset, length, request ID, timestamp, or nonce changes\
Then the original proof fails.

**AC-F005-03: Canonicalize empty and zero values**\
Given an operation has an empty path or zero numeric values\
When CLI and Node build canonical bytes\
Then each value occupies its defined position and produces identical bytes on all supported platforms.

**AC-F005-04: Reject unsupported Node proof syntax**\
Given a Node proof has an unknown scheme, version, field, duplicate field, or alternate encoding\
When the Node parses it\
Then it is refused without repair or fallback.

### F-006 Reject Node replay

**AC-F006-01: Refuse Node-proof replay under fresh client proof**\
Given a Node proof has already been admitted\
When the Server forwards it again inside a newly authenticated client request\
Then the Node refuses it and performs no second operation.

**AC-F006-02: Admit one concurrent Node proof**\
Given two identical valid Node proofs arrive concurrently\
When both attempt nonce admission\
Then exactly one is admitted and the other is refused.

**AC-F006-03: Do not reserve Node nonce for bad signature**\
Given a forged Node proof uses a nonce later used by a legitimate request\
When the forged proof fails and the valid proof arrives\
Then the failed proof has not reserved the nonce and the valid request can proceed.

**AC-F006-04: Fail closed when Node replay cache is full**\
Given the Node cache contains its maximum unexpired entries\
When another otherwise valid new proof arrives\
Then it is refused without evicting a live nonce.

### F-007 Forward Node proof without secrets

**AC-F007-01: Forward signed Node fields unchanged**\
Given the Server has accepted a client proof\
When it forwards the operation\
Then the caller request ID, Node-signed operation fields, and Node proof reach the Node unchanged.

**AC-F007-02: Keep internal correlation separate**\
Given the Server needs a wire correlation ID\
When it forwards a request\
Then that ID does not replace or alter the signed caller request ID.

**AC-F007-03: Remove client proof from forwarded request**\
Given the Server accepted the client proof\
When it constructs the Node request\
Then it forwards no client proof or client credential material.

**AC-F007-04: Never claim to verify Node proof**\
Given Node proof shape is valid\
When the Server forwards it\
Then the Server records only that shape validation passed and leaves authenticity to the Node.

### F-008 Keep authentication separate from authorization

**AC-F008-01: Apply policy after Node authentication**\
Given Node proof is valid and policy grants the operation on the scope\
When the Node handles the request\
Then the operation proceeds according to existing policy rules.

**AC-F008-02: Refuse authenticated but unauthorized operation**\
Given Node proof is valid but policy does not grant the operation\
When the Node handles the request\
Then it refuses the operation and the credential does not override policy.

**AC-F008-03: Reject credential-carried grants**\
Given a credential or proof adds a role, permission, scope grant, or approval claim\
When the Node parses it\
Then the claim never changes authorization.

### F-009 Reload credential sets atomically

**AC-F009-01: Publish complete snapshots**\
Given a valid replacement credential set\
When Server or Node reload succeeds\
Then later requests use the complete new immutable set rather than mixed versions.

**AC-F009-02: Preserve the old set after failure**\
Given a verifier has a working credential set\
When a replacement is malformed, duplicated, oversized, or over capacity\
Then reload fails and the previous set remains effective.

**AC-F009-03: Isolate reload effects**\
Given one domain's credentials change\
When its verifier publishes the new set\
Then the other authentication domain and Node channel remain unchanged.

### F-010 Diagnose and migrate safely

**AC-F010-01: Distinguish operator failure classes**\
Given verification fails due to malformed proof, unknown key, clock skew, bad signature, replay, full cache, or mode mismatch\
When the verifier records the failure\
Then its log identifies the class and relevant public identifiers.

**AC-F010-02: Exclude proof material from diagnostics**\
Given any authentication success or failure\
When logs, errors, traces, startup summaries, and audit records are inspected\
Then they contain no secret, signature, or nonce.

**AC-F010-03: Never fall back after HMAC failure**\
Given a boundary is configured for HMAC and receives invalid HMAC syntax or proof\
When authentication fails\
Then no bearer comparison is attempted.

**AC-F010-04: Permit explicit mixed migration across domains**\
Given client authentication is HMAC and one Node remains explicitly bearer, or the reverse\
When the CLI uses the configured mode at each boundary\
Then each verifier enforces only its own configured mode without automatic downgrade.

## Assumptions and constraints

### Assumptions

- Protected operations remain read-only: `file.list`, `file.stat`, and `file.read`.
- Callers already receive credentials through an out-of-band channel.
- Host clocks can be synchronized closely enough for bounded windows, but final tolerances are undecided.
- Short cross-restart replay windows may be acceptable for read-only requests if explicitly accepted per verifier.
- Existing Node policy behavior remains unchanged.

### Hard constraints

- Go is the implementation language.
- Linux, macOS, and Windows are supported.
- The Node is the only authority for scope and permission.
- The Server never receives or retains a Node credential secret.
- Credentials authenticate and never carry permission.
- Authentication defaults to refusal.
- HMAC failure never falls back to bearer.
- `tunnel_token` and channel authentication are unchanged and outside this PRD.

### Product constraints

- Existing bearer deployments may require explicit migration modes.
- Both verifiers must retain original HMAC secrets securely; digest-only storage is incompatible.
- HMAC does not encrypt paths, metadata, file contents, or responses.
- Timestamp and nonce checks cannot distinguish an original request from an identical captured copy that reaches the verifier first.
- TLS remains required for transport confidentiality, peer endpoint authentication, and protection against on-path first-use racing and response tampering.
- In-memory replay state does not provide exactly-once behavior across verifier restarts.

## Risks

| Risk | Impact | Probability | Mitigation |
|---|---|---|---|
| Clock skew refuses legitimate requests at either boundary | Medium | Medium | Independent bounded windows, clock-skew diagnostics, and documented time synchronization |
| Server replay cache exhaustion causes denial of service | High | Medium | Bound clients and traffic, reject malformed proofs early, fail closed, and expose capacity |
| Node replay cache exhaustion causes denial of service | High | Medium | Bound Node callers and traffic, reject malformed proofs early, fail closed, and expose capacity |
| Captured complete request wins a plaintext first-use race | High | Medium on plaintext paths | Require TLS for on-path protection; HMAC prevents modification and later replay but cannot identify which identical copy was original |
| Cross-restart replay inside either window | Medium for reads; high for future writes | Medium | Explicitly decide each residual risk and require restart-safe deduplication before mutation |
| Canonical formats diverge across components or platforms | High | Medium | Shared pure packages, golden vectors, and cross-platform tests |
| Reverse proxy rewrites the signed HTTP path or Node proof header | High | Medium | Define the exact public request bytes verified by Server and test actual proxy deployment behavior |
| Bearer compatibility becomes a permanent downgrade | High | Medium | Explicit per-boundary modes, no fallback, migration deadline, and removal criteria |
| Credential stores expose many caller secrets | High | Low to medium | Private access, strict bounded files, deny remote reads, and documented backup handling |
| Multiple Node credentials accidentally become permissions | High | Low | Keep grants only in policy and regression-test policy separation |
| Server still observes operation and response data | High when confidentiality is expected | High | State that HMAC is not encryption and require TLS where confidentiality and response integrity matter |

## Open questions

- [ ] Are multiple credentials permanent caller identities or only rotation overlap in each domain?
- [ ] What management commands or deployment interfaces create, list, rotate, revoke, and reload credentials?
- [ ] What are maximum client and Node credential counts and key ID bounds?
- [ ] Does the caller configure `node_id` and `node_key_id.node_secret` separately, or use another copyable form?
- [ ] Are the proposed `Authorization` and `X-Connector-Node-Auth` header grammars accepted?
- [ ] Are the final scheme names `CONNECTOR-CLIENT-HMAC-SHA256` and `CONNECTOR-NODE-HMAC-SHA256`?
- [ ] Is `req_` plus 128 random bits the final caller request ID format?
- [ ] What are default and maximum replay windows for Server and Node?
- [ ] What peak rates and cache memory budgets must Server and Node support?
- [ ] Are cross-restart replays inside short windows accepted for read-only operations at each verifier?
- [ ] How are Server client credentials stored and reloaded without conflicting configuration sources?
- [ ] How are Node caller credentials stored and reloaded?
- [ ] How long are explicit bearer compatibility modes supported?
- [ ] Which failure classes are externally visible and which are log-only?
- [ ] Is response signing explicitly deferred to a later release?

## References

- `docs/hmac-replay-protection-proposal.md`
- `docs/permission-design.md`
- `docs/API.md`
- `docs/Environment_Variables.md`
- `docs/cases/AdversarialCase_secrets.md`
- `docs/cases/AdversarialCase_node-authority.md`
- topsailai-data note `note--hmac-request-signing-practice`

## Terminology

| Term | Meaning |
|---|---|
| Client credential | `client_key_id.client_secret`, held by one CLI caller and the Server |
| Node credential | `node_key_id.node_secret`, held by one CLI caller and one Node |
| Client proof | HMAC proof verified by the Server over HTTP request identity and body |
| Node proof | HMAC proof verified by the Node over logical operation intent |
| Caller request ID | CLI-generated identifier signed by both domains and forwarded unchanged |
| Wire correlation ID | Server-generated identifier used only to pair channel responses with pending requests |
| Replay window | Maximum clock difference accepted by one verifier |
| Nonce | One-time random value recorded by one verifier during its replay window |
| Canonical input | Fixed byte representation of every field protected by one proof |
