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

## Resolution

Fixed on 2026-11-17 in commit `8a93d7a2`.

`gofmt -w internal/tui/table.go` realigned three struct fields in `TableOptions`. The whole diff is
three lines, all whitespace:

```text
-	Grow   bool
-	Color  ColorPolicy
+	Grow  bool
+	Color ColorPolicy
...
-	All bool
+	All    bool
```

No behaviour change, as expected: `gofmt` only rewrites layout.

Verification:

```text
gofmt -l internal/ src/     reports only internal/storage/server/zz_diag9_test.go, which is an
                            untracked file owned by a concurrent agent and was not touched
go test -count=1 ./internal/tui/    ok  66.534s
```

The `-count=1` run was used deliberately. The first run reported `(cached)`, which proves nothing
about the formatted file because the cache key does not change for a whitespace-only edit.
