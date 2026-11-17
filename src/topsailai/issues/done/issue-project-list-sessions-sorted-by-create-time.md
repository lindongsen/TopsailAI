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

# Project session list is paged by create_time and ordered by stdout mtime, never by update_time

## Symptom

`topsailai project list_sessions` does not reflect a session's real modification
time. A session edited minutes ago can be missing from the list entirely, while a
session untouched for two days can appear near the bottom of the "Modified"
column showing a time from today.

## Evidence

The listing path uses three different timestamps, none of which is the stored
`update_time`.

1. Page selection is `create_time DESC` in the database.
   `cli/cli_topsailai/project_scope.py:335-346` runs
   `topsailai_list_sessions --json --has-project --sort desc --limit 30`, and
   `cli/ai_list_sessions.py:308-312` maps `desc` to `-create_time`.
2. Display order is stdout file mtime ascending.
   `cli/cli_topsailai/project_scope.py:413-421` sorts the returned rows by
   `_mtime`, oldest first.
3. The "Modified" column is stdout mtime with a `create_time` fallback.
   `cli/cli_topsailai/project_scope.py:394-399` sets `modified_time_raw` from the
   newest stdout file mtime, or from `create_time` when no stdout file exists.

Measured against the live database (`/root/.topsailai/memory.db`, 396 project
sessions, 145 excluding `agent_driver`):

- Three sessions belong in the 30 most recently modified rows but are absent
  from the page the CLI fetches:
  - `20261113084305` create `2026-11-13 08:43:43`, update `2026-11-16 14:29:29`
  - `wa-1fb57b5948b4` create `2026-11-10 23:40:18`, update `2026-11-16 11:05:23`
  - `wa-ecd67a6e691e` create `2026-11-13 22:38:55`, update `2026-11-15 00:05:02`
- The oldest `update_time` inside the fetched page is `2026-11-14 12:30:54`,
  so the page is not a "most recently modified" window at all.
- `topsailai_list_sessions --json` output contains no `update_time` key
  (verified against the real command; the emitted key set has 33 fields and
  `update_time` is not among them).
- `topsailai_list_sessions --order-by=-update_time` fails with
  `Error: Unsupported order_by field: -update_time`.

## Root cause

The `session` table already stores and maintains `update_time`:

- Column definition: `context/session_manager/sql.py:101`.
- Refreshed on rename: `context/session_manager/sql.py:849`.
- Refreshed on token accumulation: `context/session_manager/sql.py:889`.
- Refreshed on metric accumulation: `context/session_manager/sql.py:1007`.
- Loaded into `SessionData`: `context/session_manager/sql.py:572` and `:690`.

The listing path never uses it, for two independent reasons:

1. `cli/ai_list_sessions.py:276-292` `_session_to_dict()` does not emit
   `update_time`, even though `SessionData.update_time` is populated. The CLI
   therefore cannot sort or display it.
2. `context/session_manager/sql.py:618-623` `allowed_fields` contains only
   `session_id`, `session_name`, `task`, and `create_time`, so the backend
   rejects any attempt to order by `update_time`.

Because the limit is applied together with `create_time DESC`, the sort
direction decides *which* rows are returned, not only how they are displayed. A
recently modified but older session is filtered out before the local re-sort can
ever see it. This is the same fetch-order versus display-order trap already
recorded in `cli/LEARN.md` ("Sort direction and limit interact when fetching
paginated data").

## Detection failure

No test asserts that the page contains the most recently modified sessions.
`cli/tests/unit/topsailai/test_project_scope.py:99-134`
(`test_build_project_list_keeps_oldest_first_order`) pins the stdout-mtime
ordering, and `:136-141` pins the `--limit` argument, so the suite validates the
current behaviour rather than the intended one. `update_time` has no consumer in
the CLI at all, so its absence from the JSON contract was never exercised by any
test.

## Proposed fix

Preferred, database-side ordering:

- Add `update_time` to `allowed_fields` in
  `context/session_manager/sql.py:618-623`.
- Emit `update_time` from `_session_to_dict()` in `cli/ai_list_sessions.py`.
- Have `build_project_list()` request `--order-by=-update_time --limit 30` so
  both selection and ordering happen in the database, and keep the local
  oldest-first display sort.

Alternative, CLI-only:

- Emit `update_time` from `_session_to_dict()`.
- Drop or raise the database limit, sort locally by `update_time`, then truncate
  to the requested count.

The CLI-only variant leaves the core untouched but fetches more rows per refresh
(145 project sessions today) and keeps the page-selection defect in the backend
contract.

## Scope note

The preferred fix touches `context/session_manager/sql.py`, which is outside the
`cli/` workspace and requires explicit authorization. CLI-side changes alone
cannot fix page selection, because the limit is applied before the CLI sees the
rows.

## Status

Resolved. Implemented by `e3f605b0` (2026-11-16 16:44, "fix: sort project
list_sessions by update_time") and `0b82180a` (2026-11-16 17:52, "fix: preserve
every list_sessions field in project list_sessions json"). Both commits postdate
this issue file, which was written at 15:24 the same day.

## Closure verification (2026-11-17)

All three defects named above were re-checked against the current tree.

1. Page selection now orders by `update_time`.
   `cli/cli_topsailai/project_scope.py:350` passes `--order-by=-update_time`
   instead of the previous `--sort desc`, which resolved to `-create_time`.
2. The storage layer accepts the field.
   `context/session_manager/sql.py` lists `"update_time": Session.update_time` in
   `allowed_fields`, so the ordering request no longer raises
   `Unsupported order_by field`.
3. The JSON payload carries the field.
   `cli/ai_list_sessions.py:281` emits `update_time` in `_session_to_dict()`.

Live probes on the current tree:

- `ai_list_sessions.py --json --has-project --order-by=-update_time --limit 3`
  exits 0 with 3 rows, 34 fields per row, and `update_time` present. The rows are
  ordered by `update_time` descending while their `create_time` values are not
  monotonic, which proves the ordering field is `update_time` and not
  `create_time`.
- `--limit 30` returns a page of 30 sorted descending, newest
  `2026-11-17T16:50:17`, oldest in page `2026-11-16T22:22:58`.
- Of the three sessions named in this issue, `20261113084305` and
  `wa-1fb57b5948b4` now appear in that page. `wa-ecd67a6e691e` is still absent,
  and that is correct rather than a remaining defect: its stored `update_time` is
  `2026-11-15 00:05:02`, and 104 sessions have a newer `update_time`, so it
  genuinely falls outside the 30 most recently modified rows.
- The same three sessions are all absent when the page is requested with
  `--order-by=-create_time`, which reproduces the original symptom and confirms
  the reported behaviour was real before the fix.

`cli/tests/unit/topsailai/test_project_scope.py` passes 139 tests. The fix added
five tests that cover exactly the blind spots this issue identified:
`test_update_time_decides_modified_time_and_order`,
`test_update_time_does_not_consult_the_stdout_index`,
`test_missing_update_time_falls_back_to_stdout_mtime`,
`test_missing_update_time_and_stdout_falls_back_to_create_time`, and
`test_page_is_requested_by_update_time_not_create_time`.

Display order is intentionally unchanged: `project_scope.py` still sorts entries
oldest-first for presentation, with a comment explaining that the page is fetched
newest-first so the most recently modified sessions are inside the page while the
oldest of them still appears on top. That is a display convention, not the
ordering defect this issue described.

The scope note above is therefore obsolete: the preferred fix location in
`context/session_manager/sql.py` was authorized and implemented, and the CLI-side
change alone would not have been sufficient.
