---
maintainer: AI
author: DawsonLin
status: pending
created: 2026-11-13
---

# `internal/tui/table.go` is not gofmt-clean

## Symptom

`gofmt -l internal/` reports `internal/tui/table.go`, while `git status --short -- internal/tui/table.go`
is empty. The file is therefore committed in a state that `gofmt` would rewrite.

## Why it is recorded instead of fixed

The defect predates the Provider CLI migration and belongs to no unit of that work. Formatting it
inside an unrelated logical unit would mix an unreviewable whole-file rewrite into a diff that is
supposed to prove something else, and it would make the change impossible to attribute.

## Scope of the fix

Run `gofmt -w internal/tui/table.go`, confirm `gofmt -l internal/` is empty, and confirm
`make test-unit-common` and `make test-unit-endpoint` still pass. No behaviour change is expected,
because `gofmt` only rewrites layout.

## Verification

Not yet performed. This record exists so the defect is traceable; it is not a claim that the file is
correct.
