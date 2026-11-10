---
maintainer: AI
author: DawsonLin
---

# Secret Gates

## What an operator sees

Three secrets gate three different things, and each one is validated by exactly
one party. An operator provisions them once and rotates them when a value may
have leaked.

| Secret | Set by | Presented by | Validated by | Gates |
|---|---|---|---|---|
| `tunnel_token` | Server operator | Node, in `hello` | Server | May this Node connect |
| `client_token` | Server operator | CLI, every request | Server | May this caller use the Server |
| `node-id.node-token` | Node | CLI, forwarded | Node | One operation on one scope |

## Behaviour

- No secret carries a permission. A secret answers "may you talk to me", and the
  policy file answers "may you do this". A secret that carried a permission would
  be a second place where authority lives.
- A secret is compared as a whole value in constant time. A prefix comparison
  would leak the length of the correct value through timing.
- A secret is never logged, never written to an audit record and never included
  in an error message. A log line names the secret's role, never its value.
- A secret shorter than 16 characters is refused at startup, because a short
  secret is a guessable one.
- A missing secret is a startup failure. A Node or Server that started without
  one would be a process whose operator believes it is protected.
- Rotation is the only revocation mechanism. There is no grace period, because a
  grace period is a second valid credential and defeats the point of rotating.
- Rotation requires a restart. Hot reload is not supported, because a restart is
  the cheapest audit trail: it is visible in the process table and in the log.

## Why the Server never stores a Node token

The Server forwards the `node-token` on the request it arrives with and keeps no
copy. This covers persistence, logging, retention after forwarding and any
derived value such as a hash, a prefix or a fingerprint.

If the Server stored an operation token, compromising the Server would yield
every stored credential at once, and the separation between the channel authority
and the operation authority would collapse into one authority.

## What this feature does not do

- It does not expire a secret. A leaked `client_token` works until it is rotated.
  Expiry would need a clock both sides trust and a revocation list, and a
  revocation list is a stored credential index.
- It does not identify individual callers. Every holder of the `client_token` is
  indistinguishable from every other holder. Per-caller identity is the upgrade
  path, and it costs a token format with a subject claim.
