---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
---

# `watch` hides the whole table when one endpoint fails to report

## Trigger

Human report (verbatim):

> 发现一个cli的watch指令的问题：
> workspace> watch
> auto-refresh: 5s projection (any key stops)
> auto-refresh: endpoints "ai-dev", "gd-dev", "local-endpoint", "topsailai-dev" failed to report
>
> 即使有错，也不应该不显示list。

## Observed behavior

`watch` printed two lines and no table. Every endpoint in the fleet had failed to report, so the
operator saw a diagnostic instead of the inventory. The same fleet rendered normally through `list`,
which reports per-endpoint failures beside the table rather than instead of it.

## Root cause

Two defects combined, and the second one would have kept the table empty even after the first was
fixed.

`watchController.load` (`internal/tui/watch.go`) collected the failing endpoint IDs, sorted them, and
then returned an empty `reportLoad{}` together with an error:

```go
if len(failed) == 0 {
    return loaded, nil
}
sort.Strings(failed)
return reportLoad{}, fmt.Errorf("endpoints %q failed to report", strings.Join(failed, `", "`))
```

The rows that had been read successfully were discarded with the struct. `collect()` then took the
error branch, called `publishFailure`, and returned before `render` was ever invoked, so no table bytes
were produced at all. `replWatch.Idle` turned the error into the single `auto-refresh: ...` line the
operator saw.

The second defect was in `render`, which passed `io.Discard` as the errors writer:

```go
renderListRows(safe, io.Discard, loaded, c.filter, false, options)
```

`RenderTable` (`internal/tui/table.go:326-330`) writes `endpoint <id> unavailable: <err>` to that
writer. Discarding it meant that fixing `load` alone would have produced a table with no indication of
which endpoints were missing, which is the same information loss in a quieter form.

The comment above `load` recorded the original intent: rejecting a partial collection prevents row
numbers from being rebound against data the operator cannot see. The concern is real, but it was
implemented as "no table at all", which is a strictly worse outcome than a table plus a named failure.

## Detection failure

`TestWatchControllerRejectsPartialCollection` asserted the defect as intended behaviour:

```go
if result.err == nil {
    t.Fatal("partial collection was accepted")
}
if len(result.rows) != 0 {
    t.Fatalf("partial collection published rows: %v", result.rows)
}
```

The test was green, so the behaviour looked deliberate and verified. `TestWatchControllerReportsRepeatedFailureOnce`
and `TestWatchControllerReportsRecoveryAfterFailure` both also asserted `result.err != nil` for a
per-endpoint failure, so three tests agreed with each other and none of them asked whether the operator
could still see the fleet. No test asserted that a diagnostic reaches the rendered output, which is why
the `io.Discard` writer was never noticed.

## Impact

An operator watching a fleet lost the entire inventory whenever any endpoint was unreachable. Because
`publishFailure` de-duplicates by message, the screen stayed on that one line for the whole session
instead of recovering on a later tick, so the failure looked permanent even after the endpoints
returned. The healthy endpoints were invisible throughout, which is the opposite of what a monitoring
surface is for.

## Resolution

Fixed on 2026-11-12 with a minimal change:

1. `internal/tui/watch.go`: `load` now returns the collected `reportLoad` unchanged and lets the shared
   renderer report per-endpoint failures. Only a failure to enumerate the endpoints themselves returns
   an error, because that is the one case with nothing to render.
2. `internal/tui/watch.go`: `render` passes `safe` as the errors writer instead of `io.Discard`, so
   `endpoint <id> unavailable: <err>` is written into the same sanitized buffer as the table. The
   renderer already sanitizes that text, and a watch payload is one block the editor prints at once, so
   a diagnostic on a separate writer would either be lost or arrive detached from its table.
3. `internal/tui/watch.go`: the now-unused `sort` import was removed.
4. `internal/tui/watch_test.go`: `TestWatchControllerRejectsPartialCollection` was replaced by
   `TestWatchControllerRendersTableWhenOneEndpointFails`, which asserts both the healthy endpoint row
   and the failing endpoint diagnostic appear in the rendered bytes. A new
   `TestWatchControllerReportsTotalEnumerationFailureAsDiagnostic` covers the enumeration failure that
   still has nothing to render. `TestWatchControllerReportsRecoveryAfterFailure` was rewritten to assert
   that a per-endpoint failure is not a load failure and that the diagnostic disappears after recovery.
   `TestWatchControllerReportsRepeatedFailureOnce` was removed because its subject, the `lastErr`
   de-duplication of a load failure, no longer describes a per-endpoint failure; the payload-level
   suppression in `replWatch.Idle` already prevents an unchanged table from reprinting.

Verification: both new tests were observed to fail against a deliberately broken build before being
accepted. Restoring `io.Discard` failed both with the table present but the diagnostic absent; restoring
the `reportLoad{}` rejection failed both with `partial collection was rejected instead of rendered`.
`go build ./internal/tui/`, `go vet ./internal/tui/`, `go test ./internal/tui/ -count=1` and
`make test-unit-cli` are green after the fix.
