---
maintainer: AI
author: DawsonLin
status: fixed
created: 2026-11-10
---

# Node id validation does not enforce the documented length

## Symptom

`docs/permission-design.md` states that a node id is a `node_` prefix followed by
128 bits of randomness, which is 26 characters of unpadded base32. The generator
in `internal/security/identity.go` produces exactly that.

`ValidateNodeID` does not check the length. It checks the prefix, that the body is
non-empty and that every character belongs to the alphabet. So `node_short` and
`node_a` are both accepted as valid identifiers.

## Impact

A truncated identifier is accepted everywhere an identifier is validated: the CLI
before it builds a URL, the Server before it routes, and the Node before it
compares. The result is a Node that can never be addressed, because no live
connection is registered under the truncated id, and the operator sees
`node_offline` rather than "your node id is truncated".

The design comment on `ValidateNodeID` already claims the opposite:

> A length check is not a security control, but it turns a truncated identifier
> into a startup failure instead of a Node that can never be addressed.

The comment describes an intention the code does not implement.

## Root cause

The length was treated as "the generator's business, not the parser's", which is
the reasoning `ValidateNodeToken` legitimately uses. That reasoning does not
transfer to the identifier: a token of an unexpected length is still comparable,
but an identifier of an unexpected length addresses nothing.

## Fix

`ValidateNodeID` now refuses a body whose length is not `nodeIDBodyLength`, which
is derived from `nodeIDRandomBytes` as `(nodeIDRandomBytes*8 + 4) / 5` rather
than hardcoded, so a change to the generator cannot silently disagree with the
validator. The check runs after the empty-body check and before the alphabet
check, so a truncated identifier is reported as a length problem rather than as a
character problem.

`TestValidateNodeID` gained three cases: a body one character short, a body one
character long, and `node_short`. Every fixture identifier in the test suite was
corrected to the real 26-character body, which is what surfaced the defect in the
first place: the fixtures had been using 6- and 32-character bodies that the old
validator accepted.

## Detection failure

`identity_test.go` covers the prefix, the alphabet and the empty body, but no test
asserted a length. The gap was found by reading the validator against the design
document, not by a failing test.
