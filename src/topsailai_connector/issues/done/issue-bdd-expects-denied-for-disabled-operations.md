---
maintainer: AI
author: DawsonLin
status: done
severity: medium
created: 2026-11-13
platform: all
---

# The BDD feature expects `denied` where the API and the code specify `unsupported_operation`

## Symptom

Two scenarios in `tests/bdd/features/node-authority.feature` fail:

```
runner.go:177: Then the caller receives the code "denied": code is "unsupported_operation", want "denied"
```

The failing scenarios are "A write is refused even when the policy grants it"
(line 46) and "A command is refused even when the policy grants it" (line 53).

## Impact

The scenarios assert the right *property* — a read-only Node must refuse a write
and an exec even when the policy grants the permission — but the wrong *code*.
Because the suite fails, the property is not actually being verified: a reader who
sees a red suite learns nothing about whether the refusal works, and a reader who
trusts `make check` (see `issue-make-check-masks-suite-failures.md`) learns
nothing at all.

The mismatch also means the executable specification contradicts the published
API. A client author reading the feature file would implement handling for
`denied` and never handle `unsupported_operation`.

## Root cause

Commit `24119e24` ("fix: refuse an unknown operation with the unsupported code")
changed `Authority.AuthorizeOperation` to return `CodeUnsupportedOperation` for a
disabled operation, and updated `docs/API.md` and `internal/node/authority_test.go`
to match. It did not touch the BDD feature file.

The change was correct and deliberate: `docs/API.md` states that an unknown
operation name and a declared-but-disabled name must return the same code, so a
caller cannot enumerate the vocabulary by comparing the two answers. Returning
`denied` for `file.write` would have made the two answers distinguishable.

So the feature file is stale, not the code.

## Detection failure

`make check` masked the failure, so the stale expectation survived a commit that
changed the behaviour it asserts. The unit test in `authority_test.go` was updated
in the same commit, which made the change look complete: the code had a test, the
document was updated, and the only remaining assertion was in a suite whose
failure was invisible.

## Fix

Change the two expectations to `unsupported_operation`, and state in the scenario
why the code is not `denied`, so the next reader does not "correct" it back.

## Verified on

Linux build host. After the fix, `go test -tags bdd ./tests/bdd/...` passes and
`make bdd` returns 0.
