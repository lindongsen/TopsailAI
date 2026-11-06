---
maintainer: AI
author: DawsonLin
---

# Session-scope `refresh`/`r` rendered no table

## Trigger

Human report (verbatim):

> cli 进入session scope后，按 r 指令没有输出表格内容，期望是要输出的

The operator entered a session scope in the interactive REPL and pressed `r`; the command reported
success but printed no table, so the reloaded inventory was invisible.

## Observed behavior

`refresh` (alias `r`) in session scope printed only `session refreshed: <sessionID>` and returned to the
prompt. Workspace and endpoint scopes rendered the table, so the same command behaved differently
depending on scope, and the operator had no way to see the reloaded rows without leaving the session
scope.

## Root cause

`interactiveRefresh` in `internal/tui/interactive.go` branched on scope and treated session scope as a
revalidation-only operation:

```go
if state.Scope.Kind != ScopeSession {
    return interactiveList(parent, api, state, "", false, out, errors, color)
}
_, _, session, err := findSelected(ctx, api, state)
...
_, err = fmt.Fprintln(out, "session refreshed:", session.SessionID)
```

The branch was introduced by commit `8f0b42ce` (`feat: restrict commands by scope`), which narrowed
`refresh` to "revalidate the current session" in session scope. The scope restriction was intentional,
but dropping the table was not: `scopedListFilter` already narrows the inventory to the current
endpoint, so the same table can be rendered in session scope without widening the query.

## Resolution

`interactiveRefresh` now performs one inventory load for both purposes:

1. `scopedListFilter` narrows the load to the current endpoint (unchanged).
2. `loadReports` fetches the inventory once.
3. In session scope `findSelectedIn` revalidates the pinned selection against that same load, so a
   changed generation still invalidates the selection and renders no table.
4. `renderListRows` renders the endpoint table through the trusted writer, so colours and provider
   ANSI sanitization match `list`.

`ListWithOptions` was split so the rendering half (`renderListRows`) is reusable; no extra API round
trip is added and the workspace/endpoint paths are unchanged.

## Prevention

- `TestRefreshRendersTableInSessionScope` asserts the session-scope table contains `SESSION_ID` and the
  pinned provider session ID, excludes another endpoint, and keeps the session prompt.
- `TestRefreshInSessionScopeStillRevalidatesTheSelection` asserts a changed generation still reports
  `selected session generation changed; use the session again`, renders no second table, and leaves the
  invalidated prompt.
- `TestRefreshKeepsTableColors` gained a session-scope case so the styling path is pinned in both colour
  and plain modes.
- `internal/tui/help.go` and `tests/manual/live-tmux/navigation.md` (OBS-06) now state that session-scope
  refresh renders the endpoint table, so the documented behaviour cannot drift back.
