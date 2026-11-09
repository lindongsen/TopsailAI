---
maintainer: AI
author: DawsonLin
status: resolved
created: 2026-11-09
---

# Snapshot output truncation splits a UTF-8 rune

## Symptom

A snapshot read whose payload exceeded `max_bytes` returned invalid UTF-8. A probe with an adapter
returning `Lines: []string{"中中中"}` and `MaxBytes: 4` produced `data="中\xe4"`, and
`utf8.ValidString` reported false.

## Root cause

`internal/endpoint/executor.go` truncated with a raw byte slice:

```go
if len(response.Data) > limit {
    response.Data = response.Data[:limit]
    response.Truncated = true
}
```

A three-byte rune cut at byte four leaves one whole rune plus the first byte of the next, which no
longer decodes.

The follow route had already been fixed to truncate on a rune boundary through `truncateUTF8` in
`internal/adapter/topsailai/follow.go`. The snapshot route was not, so the same protocol field
behaved differently on the two output routes.

## Detection failure

`TestReadOutputTruncatesAtMaxBytes` used the ASCII-only fixture `"abcdefghij"`, which is valid UTF-8
at every byte offset. The test therefore passed both before and after any rune-boundary fix and could
not detect the defect.

## Resolution

`truncateUTF8` was extracted into the shared `adapter` package as `adapter.TruncateUTF8`
(`internal/adapter/truncate.go`). Both output routes now call it, so the two routes cannot drift
apart again. The TopsailAI-local `truncateUTF8` delegates to the shared helper.

The helper removes at most one rune's worth of bytes, so a payload that is not UTF-8 at all is
shortened rather than emptied. An earlier implementation using `utf8.RuneStart` plus an
incomplete-sequence check was reverted because it returned an empty payload for all-invalid input,
which would hide the provider's bytes from the operator.

## Verification

- `TestReadOutputTruncatesOnRuneBoundary`: `中中中` with a 4-byte budget returns exactly `中`, valid
  UTF-8, within budget, `truncated: true`.
- `TestReadOutputKeepsWholeRunesWhenBudgetFallsInsideARune`: `中文abc` with a 5-byte budget returns
  exactly `中`.
- `TestTruncateUTF8KeepsWholeRunes`: seven sub-cases covering rune-boundary backoff, exact-boundary
  cuts, ASCII, within-budget passthrough and non-positive budgets.
- `TestTruncateUTF8KeepsTheValidPrefixOfInvalidData` and `TestTruncateUTF8StopsTrimmingAfterOneRune`
  cover corrupt payloads.
- Reverse verification: restoring the raw byte slice made both snapshot tests fail with
  `data="中\xe4" is not valid UTF-8` and `data="中\xe6\x96" is not valid UTF-8`; restoring the fix
  made them pass.
- `adapter.TruncateUTF8` coverage 100%; `internal/adapter` 78.9%, `internal/adapter/topsailai` 88.0%,
  `internal/endpoint` 82.5%.
- Full suite green: `go build ./...`, `go vet ./...`, `gofmt` clean, and `go test ./... -count=1`
  including BDD and packaging.

## Disclosed limitation

The pre-existing `TestReadOutputTruncatesAtMaxBytes` was left unchanged. It still asserts the ASCII
behaviour and still cannot detect a rune-boundary regression; the new tests are the detectors.
Keeping it documents the exact-budget path, but it must not be mistaken for UTF-8 coverage.

## Out of scope

`agent-cluster-cli help logs` describes the REPL budget, the current session and the rendered row
numbers on the standalone surface, none of which exist there. The human explicitly limited this unit
to the snapshot truncation defect, so that finding is tracked separately under
`issues/standalone-help-duplicates-without-text-parameter.md`.
