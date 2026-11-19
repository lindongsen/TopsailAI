---
maintainer: AI
author: DawsonLin
status: open
severity: critical
created: 2026-11-20
---

# A tunnel token holder can impersonate any Node and fabricate its answers

## Symptom

A process holding only the `tunnel_token` — no node credential, no client
credential — can connect to the Server, claim an **existing** node id, and answer
requests for that Node with invented content. The CLI reports `rc=0` and prints
the fabricated bytes as if they were the file.

Measured on 2026-11-20 against the live Server at `192.168.2.3:8743`.

## Reproduction

1. Start a real Node so its id is registered.

```
CONNECTOR_NODE_CONFIG_DIR=.tmp/imp/config \
CONNECTOR_NODE_POLICY_FILE=.tmp/imp/policy.yaml \
CONNECTOR_NODE_SERVER_URL=ws://192.168.2.3:8743/channel \
CONNECTOR_NODE_TUNNEL_TOKEN=<tunnel_token> \
  ./bin/connector-node run
-> node_id=node_xm6lqoluutyi2ezczl4y2zkfrm
```

The scope holds one file whose content is `REAL SECRET FILE CONTENT`.

2. An honest read returns the real bytes.

```
./bin/connector-cli --scope project --path real.txt file.read
-> REAL SECRET FILE CONTENT
   rc=0
```

3. Stop the real Node. Connect a rogue process that sends `hello` with the same
node id and the same `tunnel_token`, and answers every `request` frame with a
`response` frame carrying invented content.

```
CONFIRM type=hello_confirm payload={"version":"1.0","generation":42}
REQUEST op=file.read scope=project path="real.txt"
WROTE RESPONSE
```

The Server accepted the connection and logged it as an ordinary Node:

```
level=INFO msg="channel established" node_id=node_xm6lqoluutyi2ezczl4y2zkfrm
  generation=42 operations="[file.read file.list file.stat]" scopes=[project]
  file_transport=json
```

4. The same CLI command, with the same valid node credential, now returns the
fabricated bytes.

```
./bin/connector-cli --scope project --path real.txt file.read
-> FABRICATED BY THE ROGUE NODE
   rc=0
```

The real file still contains `REAL SECRET FILE CONTENT`. The caller cannot tell
the difference: same exit status, same shape, no warning.

## Why it works

Three properties combine, and each is individually reasonable.

| Property | Where | Effect here |
|---|---|---|
| `tunnel_token` is a Server-wide shared secret | `internal/server/channel.go:467` | Any holder passes the channel gate |
| The node id is chosen by the Node, not assigned by the Server | `internal/protocol/frame.go:61` | A rogue process names any id it likes |
| A duplicate node id **replaces** the live connection | `internal/server/registry.go:80`, `channel.go:497` | The rogue takes over the address, and the real Node is evicted |
| The response direction carries no proof | `internal/protocol/operation.go:115` | The Server cannot tell a real answer from an invented one |

The registry comment states the intent:

> A Node that reconnects replaces its entry: one connection serves one Node, so
> two live connections for one identity would be two answers to one request.

That reasoning is correct for a Node that reconnects. It does not distinguish a
Node that reconnects from a different process that claims its name, because the
Server has nothing to compare: it never receives a node secret, so it cannot
verify who is on the other end.

The response struct has no signature field at all:

```go
type Response struct {
	Code    Code   `json:"code"`
	Data    []byte `json:"data,omitempty"`
	Content []byte `json:"-"`
}
```

So the Server relays whatever the channel sends. The node proof is verified by the
Node, and the Node is the party that has been replaced.

## What the rogue also receives

The forwarded request carries the caller's node proof, which the rogue reads in
full:

```
NODE PROOF RECEIVED: {"scheme":"CONNECTOR-NODE-HMAC-SHA256","version":1,
  "key_id":"victim","timestamp_ms":1795130845346,
  "nonce":"d110f65c92d9d0c70db1b5314d501562",
  "signature":"40b968d125f2699e79e7d42f2a1745ef4325270340f8f2652135808324c74247"}
```

The signature cannot be turned back into the secret, so this is not a credential
leak. It is a **replay** opportunity: the rogue holds a valid proof for a request
it did not make, and the Node's nonce cache is the only thing that stops it being
used twice. The rogue can also simply not forward it, which is what happened here.

## Impact

| Consequence | Detail |
|---|---|
| Fabricated content | A caller reads invented bytes with `rc=0` and no warning |
| Denial of service | The real Node is evicted every time the rogue connects; measured generation 36→43 in one session |
| Silent substitution | The Server log shows an ordinary `channel established`; nothing distinguishes the impostor |
| Blast radius | Every Node on the Server, because the `tunnel_token` is Server-wide |
| Requires | Only the `tunnel_token` — no node credential, no client credential |

The last row is what makes this different from the copy-of-the-binary issue. That
one needs a valid node credential to read the binary. This one needs nothing but
the token, and the token is the value the design already accepts as weak.

## The user's argument, and where it holds

The user stated that the `tunnel_token` is not important, because a host that uses
it to connect to the Server has thereby made itself a managed Node, so from the
result there is no security problem.

That argument holds for the case it describes: a host that connects with the token
becomes a Node, and a Node is exactly what the operator wanted to manage. Nothing
is gained by an attacker who only wants to be managed.

It does not hold for the case measured here, because the rogue does not become
**itself**. It becomes an **existing** Node, and the Server's replace-on-duplicate
rule makes that possible. The result is not "one more managed Node"; it is "the
Node you were talking to is now someone else, and its answers are invented".

The distinction is the whole finding:

| Rogue behaviour | Result | Security problem |
|---|---|---|
| Connects with its own new node id | One more managed Node | None, as the user argued |
| Connects claiming an existing node id | Substitutes that Node's answers | **Yes** |

## Options

None chosen. Each trades a real property against another.

| Option | Effect | Cost |
|---|---|---|
| Refuse a duplicate node id instead of replacing it | The impostor cannot take over a live Node | A Node that reconnects after a network drop is refused until the Server notices the old connection is dead; needs a liveness check or a timeout |
| Sign the response direction with the node credential | The Server can tell a real answer from an invented one | The Server would have to verify a node signature, which requires the node secret — forbidden by the hard constraint |
| Give each Node a Server-issued channel identity at first connect | The Server can distinguish Nodes | Makes the Server the identity authority, which `docs/permission-design.md` explicitly rejects |
| Make the `tunnel_token` per-Node instead of Server-wide | A leaked token exposes one Node | Changes the provisioning model; the token is currently one value for the whole Server |
| Accept and document | No code change | A token holder silently substitutes any Node's answers |

The second option is worth stating precisely because it looks attractive and is
forbidden: verifying a response signature on the Server means the Server holds the
node secret, which is the one rule the whole design rests on.

The first option is the smallest change and the only one that does not touch the
credential model. It converts a silent substitution into a visible refusal, which
is the property that matters most: a caller who receives `node_offline` knows
something is wrong, while a caller who receives invented bytes does not.

## Related

- `issues/issue-a-copy-of-the-binary-leaks-the-tunnel-token.md` — the same token,
  reached by reading a copy of the binary. That route needs a node credential;
  this one does not.
- `issues/issue-two-node-processes-share-one-identity.md` — the same
  replace-on-duplicate rule, seen as an operational annoyance when one artifact is
  installed twice. This issue is the same mechanism used deliberately.
- `docs/permission-design.md` — the residual-risk table states that a leaked
  `tunnel_token` lets anyone "open a channel and impersonate a Node". That row is
  accurate and understates the consequence: impersonating a Node means answering
  its requests, not only connecting as one.
