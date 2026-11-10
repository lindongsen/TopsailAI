---
maintainer: AI
author: DawsonLin
status: open
created: 2026-11-09
updated: 2026-11-10
---

# Wire contract cannot express the Node a request is for

## Symptom

`internal/protocol/operation.go` `Request` has no node identifier. The Server
accepts connections from many Nodes and keeps a routing registry, but the request
struct cannot say which Node a request targets.

## Impact

The CLI access path in `docs/API.md` requires
`POST /v1/nodes/{node_id}/operations`, and the Server must check that the `node-id`
in the URL agrees with the `node-id` half of the pair. Neither check can be
expressed in the current wire contract, so the routing decision has nowhere to
live.

## Root cause

The protocol was written when the Server was assumed to serve one Node, so the
Node identity was implicit in the connection. The CLI access path makes the
identity explicit, and the struct was not updated with it.

## Fix

Add the `node-id` to the request envelope. The `node-token` is a separate field,
because the two halves have different jobs: the `node-id` is an address that may be
logged, and the `node-token` is a secret that never may be.

The Server compares the `node-id` in the URL with the `node-id` in the pair before
forwarding. A disagreement is `invalid_argument`, not an authentication failure,
because the Server can see both halves and the request is malformed rather than
untrusted.

## Note on the superseded design

An earlier version of this issue proposed adding `node_id` and a signed `role`
claim to the token. That is obsolete: the human replaced signed tokens with shared
secrets, so there is no claim to carry a role. The `node-id` lives in the pair and
in the URL, and the two must agree.

## Detection failure

No test exercises a request for a specific Node, because no routing exists yet.
The gap is a missing field rather than a wrong value, so no assertion could have
caught it.
