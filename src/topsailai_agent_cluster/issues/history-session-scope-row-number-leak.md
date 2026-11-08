---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: topsailai_agent_cluster
programming_language: go
---

# A bare number in session scope resolved against the history table

## Trigger

Found while reviewing the committed `history` feature. A throwaway probe test rendered history,
entered a live row, then typed a bare number and observed a history-row error instead of the
session-scope error.

## Symptom

In session scope, typing a bare number produced a history-row message such as
`history row 1 is unjoined: ...` instead of
`row-number navigation is unavailable in session scope`.

## Cause

Two row-number paths exist and only one rejected session scope:

- `cdRowNumber` in `internal/tui/navigation.go` starts with a session-scope guard.
- `cdHistoryRowNumber` in `internal/tui/interactive_history.go` had no such guard.
- `interactiveCD` prefers `state.history` whenever it is non-nil, so the unguarded path won.
- `cdHistoryRowNumber` also never cleared `state.history` after entering a session, so the
  history namespace survived the transition and kept claiming bare numbers.

## Why the tests missed it

No test typed a bare number in session scope after a history render. The existing history tests
covered `cd <n>` from endpoint scope and `list` restoring the live namespace, but not the
session-scope rejection.

## Fix

Added the same session-scope guard to `cdHistoryRowNumber`, and cleared `state.history` once the
transition into a session succeeds. A number can no longer reach a table the operator cannot see.

Added two tests:

- `TestInteractiveHistoryRowNumberRejectedInSessionScope` calls the helper directly, because a
  dispatch layer that rejects the number first would hide a missing guard. Verified red with the
  guard removed (`err=<nil>`) and green with it restored.
- `TestInteractiveHistoryNamespaceClearedAfterEnteringSession` proves the namespace does not
  survive the transition.

## Lesson

When two code paths implement the same user-facing syntax, every guard must exist in both. A guard
added to one path is not a property of the syntax, and a dispatcher that prefers one path silently
removes the other path's protection. Test the guard by calling the guarded function directly, not
only through the dispatcher, or the dispatcher's own rejection will mask the missing guard.
