---
maintainer: AI
author: DawsonLin
---

# Node Identity

## What an operator sees

A Node owns its own name. On first start it generates a node id, stores it in
`<config>/identity` and prints it. The node id is an address, not a
credential: it appears in URLs, logs and audit records, and knowing it grants
nothing.

The credential that authorizes a caller to talk to this Node is a separate value
in a separate file, `<config>/credentials.yaml`. On first start the Node also
generates one credential. Every `run` prints a startup summary naming the Server
address, the node id, the key id and the secret, so the operator can read the value
off the terminal at any time rather than only on the start that created it. The
secret is printed in full only when stdout is a terminal; a redirected stdout gets
`<secret:N bytes>` instead, so a launcher that logs stdout does not accumulate a
credential that never expires.

Two files, two jobs. Regenerating the address does not revoke a caller, and
revoking a caller does not change the address.

## Behaviour

- The node id is generated locally. The Server never generates, assigns or
  overrides a node identifier, and there is no endpoint that lists Nodes.
- The node id is stable across restarts. A Node that regenerated on every start
  would invalidate the address the operator already distributed.
- `connector-node id` prints the stored node id and nothing else, so it can be
  copied into a script. It creates the identity file if it does not exist yet.
- `connector-node regenerate` replaces the node id and prints the new one. It
  changes the address only. `--keep-id` is refused, because it kept the address
  while replacing the secret, and the secret no longer lives in this file.
- Regeneration takes effect within one poll interval. The running Node reads its
  identity file once per second and adopts a changed address, dropping the channel
  that was opened under the old one.
- `connector-node credential add` generates a credential, appends it to the
  credential file and prints it once. `credential list` prints the public key
  identifiers. `credential remove` removes one by key id and refuses to remove the
  last one, because a Node with no credential accepts no caller.
- Rotation is add-then-remove. That is the only order that does not lock a caller
  out between two commands.
- A malformed identity file is a startup failure, not a regeneration.
  Regenerating would silently invalidate an address the operator already copied,
  and the operator would see a confusing routing failure instead of the real
  cause.
- The identity file is created `0600` on POSIX and with an owner-only ACL on
  Windows. It holds an address rather than a secret, but a file another user can
  rewrite is a file another user can redirect the Node's traffic with.
- The credential file is created `0600` and is refused at startup if another user
  can read it, because it holds secrets that never expire.

## Why the two values live in files

The Node rewrites both itself: the address on `regenerate`, the credential set on
`credential add` and `credential remove`. A value the Node owns belongs in a file
the Node owns, not in the environment of whatever process launched it: an
environment variable cannot be rewritten by the process that reads it, and it is
visible to every child process.

Keeping them in two files is what makes the two operations independent. One file
would mean that changing the address rewrote the credential, and an operator who
only wanted a new address would silently lock out every caller.

## What this feature does not do

- It does not expire a credential. A leaked credential works until the operator
  removes it. Rotation is the only revocation mechanism, and it is deliberate: an
  expiry would need a clock the Node trusts, and a revocation list would need the
  Node to store credential values.
- It does not authenticate the operator to the Server. That is the client
  credential's job. The node credential authenticates the operator to the Node.
- It does not make the address secret. The node id is public by design, so a
  leaked node id is not an incident. A leaked credential is.
