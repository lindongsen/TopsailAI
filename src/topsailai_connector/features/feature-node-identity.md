---
maintainer: AI
author: DawsonLin
---

# Node Identity

## What an operator sees

A Node owns its own name. On first start it generates a `node-id.node-token`
pair, stores it in `<config>/identity` and prints it once. The operator copies
that pair into a CLI, and from then on the CLI addresses this Node by the
identifier half and proves itself with the token half.

The identifier is public: it appears in URLs, logs and audit records. The token
is a secret: it is never logged, never printed after the first start and never
stored by the Server.

## Behaviour

- The pair is generated locally. The Server never generates, assigns or
  overrides a node identifier, and there is no endpoint that lists Nodes.
- The pair is stable across restarts. A Node that regenerated on every start
  would invalidate the copy the operator already distributed.
- `connector-node id` prints the stored pair and nothing else, so it can be
  copied into a script.
- `connector-node regenerate` replaces both halves. `--keep-id` keeps the
  identifier and replaces only the token, which is what an operator needs when
  the CLI's routing target must stay valid.
- Regeneration invalidates the previous token immediately. The Node compares
  against the value it currently holds and keeps no history.
- A malformed identity file is a startup failure, not a regeneration.
  Regenerating would silently invalidate a pair the operator already copied, and
  the operator would see a confusing authentication failure instead of the real
  cause.
- The identity file is created `0600` on POSIX and with an owner-only ACL on
  Windows, because it holds a credential that never expires. A file another user
  can read is refused at startup.

## Why the pair lives in a file

The Node rewrites the pair itself when the operator regenerates it. A value the
Node owns belongs in a file the Node owns, not in the environment of whatever
process launched it: an environment variable cannot be rewritten by the process
that reads it, and it is visible to every child process.

## What this feature does not do

- It does not expire. A leaked token works until the operator regenerates it.
  Rotation is the only revocation mechanism, and it is deliberate: an expiry
  would need a clock the Node trusts, and a revocation list would need the Node
  to store token values.
- It does not authenticate the operator to the Server. That is the
  `client_token`'s job. The pair authenticates the operator to the Node.
