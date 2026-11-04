---
maintainer: AI
author: DawsonLin
---
# Context protection termination reported as completed

Session 20261104141448 exited on ContextWindowLimitError after failed forced summaries. The chat loop catches the error and breaks before normal answer display/storage, while its outer run marks the return completed. Safety comparisons use adjusted counts but diagnostics show raw counts only. Approved fix: preserve failure outcome and reason, avoid success hooks, expose adjusted comparisons; leave summary policy unchanged. Verification tracked in .task/plan_20261104T151000_context-terminal-outcome.md.

Implementation prepared: per-run protection failure marks error; reason is displayed and stored according to need_save_answer; no success/final hooks on failure; adjusted token counts included in diagnostics. Focused checks: 342 pass including BDD; three changed files aggregate statement coverage 91%. Full suite 413/422 files pass with unresolved, unclassified failures elsewhere; acceptance remains pending. No commit performed.
