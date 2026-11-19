---
maintainer: AI
author: DawsonLin
status: open
severity: medium
created: 2026-11-19
platform: linux
---

# `tunnel_token` travels in plaintext inside the `hello` frame

## Symptom

A packet capture on the Server host shows the `tunnel_token` on the wire in
recoverable form. The HMAC migration replaced the client and node credentials
with signed proofs, but the channel handshake was explicitly out of scope, so
`tunnel_token` still travels as a value rather than as a proof.

Measured on `gd-dev` (`192.168.2.3`) with `tcpdump -i eth0 -s 0 tcp port 18444`,
capturing a Node reconnect:

```
Node -> Server  GET /channel  (WebSocket upgrade)
Node -> Server  text frame, masked:
  {"type":"hello","payload":"<base64>"}

payload decoded:
  {"version":"1.0",
   "node_id":"node_ysj64hfylk2ke3aui65fygln2e",
   "tunnel_token":"cFZLMlVPd0dvMFBqTVJhQXdJSk53RWtUU1pSSmxqUjhUcnNjYVRnT1U=",
   "operations":["file.read","file.list","file.stat"],
   "scopes":["project","scratch"]}

base64 decoded:
  pVK2UOwGo0PjMRaAwIJNwEkTSZRJljR8TrscaTgOU
```

That value is byte-identical to `CONNECTOR_SERVER_TUNNEL_TOKEN` in the Server's
`server.env`. Base64 is an encoding, not encryption, so the token is readable by
anyone who can observe the segment.

## What this does and does not mean

The HMAC mechanism works as designed for the two credentials it covers. Measured
in the same capture:

| Secret | On the wire | Verdict |
|---|---|---|
| `client_token` replacement (client credential secret) | 0 occurrences | protected by HMAC |
| `node-token` replacement (node credential secret) | 0 occurrences | protected by HMAC |
| `tunnel_token` | present, base64, recoverable | **not protected** |

The Server receiving `tunnel_token` is by design: the Server is the party that
validates it, so it must see the value. The defect is not that the Server sees
it. The defect is that the value crosses the network in a form a third party can
read, because the transport is plaintext `ws://`.

## Why the earlier "zero hits" measurement was wrong

A first pass grepped the capture for the plaintext secret and reported zero hits
for all three. That measurement was invalid for two independent reasons, and both
would have produced a false clean result:

- **The frame is masked.** A WebSocket client frame XORs its payload with a
  4-byte mask, so the base64 text does not exist in the raw bytes. A grep over
  the capture cannot find a string that is not there.
- **The token is base64 inside a base64 payload.** The frame body is JSON whose
  `payload` field is base64, and the `tunnel_token` inside that JSON is base64
  again. Searching the outer text for the inner encoding finds nothing even after
  the mask is removed.

The correct procedure is to unmask the frame, decode the `payload` field, and
search the decoded JSON. Doing that turned 0 hits into 35.

## Detection gap

The design document states the residual risk "Transport is plaintext `ws://`" and
the deployment note repeats it, but neither states that `tunnel_token` is the
value that crosses in the clear. A reader of the HMAC migration would reasonably
conclude that all three secrets are now proof-based, because the migration
description says the two CLI-facing gates were converted and does not say which
value remains a bearer value.

The enforcement checklist has no item that asks whether a secret crosses the wire
as a value rather than as a proof, so a reviewer checking the HMAC work had
nothing to check.

## Impact

An attacker who can observe the network segment obtains a Server-wide credential
that opens a channel and impersonates a Node. The blast radius is every Node on
that Server, because `tunnel_token` is shared by all of them. There is no expiry,
so the value works until it is rotated.

The exposure requires network observation. It does not require any credential, any
account on either host, or any interaction with the Server.

## Fix direction

Three options, in increasing cost:

1. **State the exposure where the value is defined.** The design document and the
   deployment note must say that `tunnel_token` is the one secret that still
   crosses the wire as a value, and that the HMAC migration did not cover it.
   This changes no behaviour and removes the false impression.
2. **Move the channel to TLS.** This is the real fix, and it is blocked by the
   Node being unable to trust a private CA. A self-signed certificate fails
   verification, so the deployment uses `ws://` deliberately.
3. **Convert the handshake to a proof.** The Node would sign the hello with a
   credential the Server can verify without holding the secret. This is the same
   shape as the CLI gates, and it is the only option that removes the exposure
   without requiring a PKI.

Option 1 is documentation and should happen regardless. Options 2 and 3 are
design decisions that change the deployment contract and need a human decision.

## Scope

No data loss, no authorization bypass. The exposure is credential disclosure to a
network observer, bounded by the requirement to observe the segment. The
`tunnel_token` gate itself still works: a wrong value is refused.
