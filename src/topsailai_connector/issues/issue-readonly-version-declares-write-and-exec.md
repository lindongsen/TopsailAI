---
maintainer: AI
author: DawsonLin
status: open
created: 2026-11-09
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
