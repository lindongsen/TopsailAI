---
maintainer: AI
author: DawsonLin
status: done
created: 2026-11-09
resolved: 2026-11-10
---

# Read-only version declares write and exec operations

## Symptom

`internal/protocol/operation.go` declares `OperationFileWrite` and
`OperationCommandExec`, and `Operation.Permission()` maps both to a permission.
`docs/permission-design.md` states the first version is read-only.

## Impact

A declared operation is callable unless something refuses it. The mapping makes
both operations look supported, so a dispatch path that trusts the mapping would
perform a write or an exec in a version that promises neither. The risk surface of
`command.exec` is an order of magnitude larger than a file read, so this is not a
cosmetic mismatch.

## Root cause

The vocabulary was written once for all three versions, and the version gate was
left to a later dispatch layer. Nothing in the current code refuses the two
operations, so the declaration is the only signal and it says "supported".

## Fix

Keep the constants, because removing them would make the second version a wire
format change. Refuse both at two places: the Node does not advertise them in
`hello`, and the Node refuses them at dispatch with `denied` even when a caller
sends one. The second refusal is what makes the gate independent of the Server
honouring the advertisement.

## Detection failure

No test asserts that a read-only Node refuses a write or an exec. The existing
tests assert that every declared operation maps to a permission, which is the
opposite property: they confirm the operations are wired up rather than refused.

## Resolution

Fixed. `Operation.Enabled()` in `internal/protocol/operation.go` returns false for
`file.write` and `command.exec`, so the version gate is a property of the
vocabulary rather than a promise a later dispatch layer has to remember.
`Operation.Validate()` refuses a disabled operation, and
`Authority.AuthorizeOperation` in `internal/node/authority.go` refuses it again at
dispatch with `denied`, so the gate does not depend on the Server honouring the
advertisement.

The constants are kept, as the fix required, so the second version is not a wire
format change.

Tests: `internal/protocol/operation_test.go` asserts `Enabled()` for all three
operations and that `Validate()` refuses a disabled one;
`internal/node/authority_test.go` asserts a read-only Node refuses a write and an
exec even when the policy grants the permission.

Fixed in `e0918e7f` (wire contract) and `36407d6f` (authority).
