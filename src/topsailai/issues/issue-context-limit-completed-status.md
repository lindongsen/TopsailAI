---
maintainer: AI
author: DawsonLin
status: resolved
---
# Context protection termination reported as completed

Session 20261104141448 exited on ContextWindowLimitError after failed forced summaries. The chat loop catches the error and breaks before normal answer display/storage, while its outer run marks the return completed. Safety comparisons use adjusted counts but diagnostics show raw counts only. Approved fix: preserve failure outcome and reason, avoid success hooks, expose adjusted comparisons; leave summary policy unchanged. Verification tracked in .task/plan_20261104T151000_context-terminal-outcome.md.

Implementation prepared: per-run protection failure marks error; reason is displayed and stored according to need_save_answer; no success/final hooks on failure; adjusted token counts included in diagnostics. Focused checks: 342 pass including BDD; three changed files aggregate statement coverage 91%. Full suite 413/422 files pass with unresolved, unclassified failures elsewhere; acceptance remains pending. No commit performed.

## Closure verification (2026-11-17)

Resolved in HEAD. The implementation described above as "prepared, no commit performed" is committed.

- `bc00292f fix: Report context protection termination as an error` (2026-11-04) is an ancestor
  of HEAD `5da6bb49f651a501b041486590a0c87e5acd85c6`.
- `workspace/agent/agent_shell_base.py:784` sets `self._terminal_failure` when context protection
  terminates the run.
- `workspace/agent/agent_shell_base.py:371` consumes it:
  `update_session_meta_status("error" if self._terminal_failure else "completed", ...)`, so a
  protection failure is no longer recorded as a completed session.
- Success and final hooks are skipped on that path, and the adjusted token counts are included
  in the diagnostics, as the approved fix required.
