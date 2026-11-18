---
maintainer: AI
author: DawsonLin
---

# Secret Gates

## What an operator sees

Two credentials and one shared secret gate three different things, and each one is
validated by exactly one party. An operator provisions them once and rotates them
when a value may have leaked.

| Gate | Set by | Presented by | Validated by | Gates |
|---|---|---|---|---|
| `tunnel_token` | Server operator | Node, in `hello` | Server | May this Node connect |
| client credential | Server operator | CLI, every request | Server | May this caller use the Server |
| node credential | Node | CLI, every request | Node | One operation on one scope |

The two credentials are not shared secrets. A credential is a `key_id.secret`
pair: the key id is public and selects one secret from the verifier's set, and the
secret is an HMAC key that never leaves the signer and the verifier. The caller
signs a proof, and the verifier checks the signature. The secret itself is never
transmitted.

The `tunnel_token` is still a shared secret compared as a whole value, because the
Node presents it once at handshake time and there is no request to sign.

## Behaviour

- No credential carries a permission. A credential answers "may you talk to me",
  and the policy file answers "may you do this". A credential that carried a
  permission would be a second place where authority lives.
- A proof is bound to the request it signs. The client proof covers the method,
  the request target, the body digest, the node proof header, the request id, the
  timestamp and a nonce. The node proof covers the node id, the key id, the
  operation, the scope, the path, the offset, the length, the request id, the
  timestamp and a nonce.
- A proof is refused when it is replayed. Each verifier keeps its own nonce cache
  and its own timestamp window, so a proof accepted by the Server is not thereby
  accepted by the Node.
- A proof is refused when its timestamp is outside the window. The default window
  is 60 seconds and the maximum is 600 seconds.
- A signature is compared as a whole value in constant time. A prefix comparison
  would leak the length of the correct signature through timing.
- A secret is never logged, never written to an audit record and never included
  in an error message. A log line names the key id, never the secret.
- A credential secret shorter than 32 characters is refused. A credential secret
  is an HMAC key, so its length is the only thing between a guess and a forgery.
- A `tunnel_token` shorter than 16 characters is refused at startup, because a
  short shared secret is a guessable one.
- A missing gate is a startup failure. A Node or Server that started without one
  would be a process whose operator believes it is protected.
- Rotation is the only revocation mechanism. There is no grace period, because a
  grace period is a second valid credential and defeats the point of rotating.
- A credential is rotated by adding the new one and removing the old one. Both
  operations are local to the party that owns the credential, and neither needs
  the other party to restart.
- The `tunnel_token` is rotated by changing the Server's environment and
  restarting it. Hot reload is not supported, because a restart is the cheapest
  audit trail: it is visible in the process table and in the log.

## Why the Server never receives a node secret

The caller proves possession of the node credential to the Node, and the Server
forwards that proof without being able to verify it. The Server never learns the
secret, so it cannot mint a proof and cannot recognise one later.

This covers persistence, logging, retention after forwarding and any derived value
such as a hash, a prefix or a fingerprint. If the Server held a node secret,
compromising the Server would yield every stored credential at once, and the
separation between the channel authority and the operation authority would
collapse into one authority.

The Server does hold its own client credentials, because it is the party that
validates them. That is not a violation: those are the Server's own credentials,
and holding them is what lets the Server be the authority for the channel.

## What this feature does not do

- It does not expire a credential. A leaked client credential works until it is
  removed. Expiry would need a clock both sides trust and a revocation list, and a
  revocation list is a stored credential index.
- It does not identify individual people. A key id identifies which credential was
  used, so an operator can attribute a request to a key and can revoke that one
  key without disturbing the others. Every holder of one key is still
  indistinguishable from every other holder of it.
- It does not replace TLS. A proof proves possession of a key, not the identity of
  the machine that sent it, and an attacker who observes a proof on a plaintext
  link can replay it inside the window before the legitimate caller does. The
  window bounds that race; it does not remove it.
- It does not survive a restart of the replay cache. A proof replayed after the
  verifier restarts is accepted again if it is still inside the timestamp window.
  This is accepted for read-only operations and must be revisited before
  `file.write` or `command.exec`.
