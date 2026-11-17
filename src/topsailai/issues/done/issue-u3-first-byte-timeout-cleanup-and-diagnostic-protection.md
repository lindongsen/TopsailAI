---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
status: resolved
---
# U3 first-byte timeout cleanup and diagnostic protection

## Trigger
Independent U3 review identified that local-owner disposal could be skipped when pause failed, and fallback logging could replace the business outcome when a logging handler failed. Creation warning elapsed was also calculated from a clipped remaining budget.

## Action
Repair the generator with one outer `try/finally` covering terminal outcome handling, pause, tail streaming, generator close, and local-owner disposal. Protect fallback logging with a nested exception boundary and calculate warning elapsed from the budget's cumulative authority clock. Add targeted regression coverage without changing tracked existing tests.

## Prevention
Structural cleanup and fully best-effort diagnostics prevent pause or logging failures from leaking owned response state or changing timeout/stream business results; cumulative elapsed preserves truthful timing after the deadline.

## Status
Open pending independent re-review and required gate execution.

## Targeted repair verification

The regression repair initialized `primary` before the monitored first-item cleanup `try` and restored pause execution to the original `ERROR`, `EOF`, and `VALUE` decisions only; `ABANDONED`, `NOT_READY`, and `REJECTED` paths do not add pause. The outer `finally` still disposes a locally owned response on every exit.

Fallback warning and phase-diagnostic logging remain nested in protected exception boundaries, and timeout warning elapsed is derived from the cumulative budget clock rather than clipped remaining time. The focused matrix passed 78 tests; the regression/containing-file matrix passed 51 tests; the U3 BDD pair passed 15 tests; the approved six-file U2 selection passed 89 tests; archive baseline comparison passed 152 tests for both baseline and current with 1366 matched files and no overlays. Independent re-review remains required.

## Status

Open pending independent re-review; targeted repair is locally verified and not committed or staged.

## Closure verification (2026-11-17)

Resolved in HEAD. The repair described above as "not committed or staged" is committed.

- `251ad9a6 fix: dispose local owner on all first byte timeout exits` (2026-10-15) is an ancestor
  of HEAD `5da6bb49f651a501b041486590a0c87e5acd85c6`.
- `7d5e67a0 fix: warn on late terminal outcomes and pause before first result` (2026-10-15) is
  also an ancestor.
- `ai_base/llm_control/first_byte_timeout.py:664-675` holds one outer `try/finally` that pauses
  for `ERROR`, `EOF` and `VALUE` decisions and disposes the locally owned response on every exit,
  so a pause failure can no longer skip disposal.
- `ai_base/llm_control/first_byte_timeout.py:318-324` keeps `_safe_log_first_byte_phase_elapsed`
  inside a nested exception boundary, so a logging handler failure cannot replace the business
  outcome.
- Warning elapsed is derived from the budget's cumulative authority clock rather than the clipped
  remaining budget.
