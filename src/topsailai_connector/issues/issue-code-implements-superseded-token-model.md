---
maintainer: AI
author: DawsonLin
status: open
created: 2026-11-10
---

# Code implements the superseded signed-token model

## Symptom

`internal/security/token.go` implements a signed token with `ID`, `Kind`,
`Subject`, `IssuedAt` and `ExpiresAt`, and `internal/protocol/operation.go`
`Request` carries a single `Token` field. `docs/permission-design.md` now specifies
three shared secrets instead: `tunnel_token`, `client_token` and a Node-generated
`node-id.node-token` pair.

The two disagree on every point that matters:

| Concern | Code | Design |
|---|---|---|
| Credential shape | Signed payload plus signature | Opaque shared secret |
| Expiry | `ExpiresAt` is mandatory | No secret expires |
| Identity | `Subject` inside the token | `node-id` in the pair and in the URL |
| Validation | Signature plus clock window | Constant-time string comparison |
| Revocation | Revocation list of `id` values | Rotate the secret |

## Impact

A reader who trusts the code builds the wrong system. The code is not merely
incomplete; it implements a model the design has replaced, so an implementer
following it would add a signature library, a clock window and a revocation list
that the design deliberately removed.

## Root cause

The design changed after the skeleton was written, and the skeleton was not
rewritten because implementation has not started. The skeleton is a placeholder
rather than a partial implementation, so the mismatch is expected at this stage.

## Fix

Replace `internal/security/token.go` with a secret-comparison helper: constant
time, whole value, one error for every mismatch. Replace `Request.Token` with the
`node-id` and `node-token` fields the design specifies. Do this as the first
implementation unit, before any handler is written, so no handler is built against
the old shape.

## Detection failure

No test compares the code's vocabulary against the design document's vocabulary.
The existing tests in `internal/security` and `internal/protocol` pass, because
they test the old model against itself.

## Related

- `docs/permission-design.md` — the current contract.
- `issues/undo/issue-token-leeway-not-implemented.md` — obsolete, because the
  design removed expiry.
- `issues/issue-request-has-no-node-identity.md` — superseded by the pair design.
