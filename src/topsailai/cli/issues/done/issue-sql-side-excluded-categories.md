---
maintainer: AI
author: DawsonLin
---
# Session category exclusion is applied in memory instead of in SQL

## Status
Resolved. The human authorized the cross-workspace change with "yes, 连索引一起补",
so the SQL-side exclusion and the missing `create_time` index are both implemented.

## Requested by the human
The human asked for `topsailai_list_sessions` to be queryable by
`excluded_categories`, and explicitly instructed: record an issue for the real
SQL-side exclusion. This record is explicitly requested despite the CLI
README's default no-issues convention.

## Behaviour before the fix
`cli/ai_list_sessions.py` accepted `--excluded-categories` and removed matching
rows after `manager.list_sessions()` had already returned them. To keep the page
correct, the CLI forced `offset=0` and `limit=None` whenever an exclusion was
requested, then filtered and paginated in memory.

## Why that was not sufficient
The exclusion predicate never reached the database, so the cost was paid on every
call:

- The full matching row set was materialized in Python before any row was dropped,
  so memory and read volume grew with the table, not with the requested page.
- `offset`/`limit` could not be pushed down, so a request for 10 rows still read
  every row that survived the inclusion filter.
- `count_sessions()` could not express exclusion, so the CLI reported the surviving
  count from the already-materialized list instead of a `COUNT(*)`.
- On the local database at the time (168 sessions) this was invisible. It becomes a
  real defect as the session table grows, because every list call is O(N) in
  rows read regardless of the requested page size.

## Verified facts about the SQL layer at the time
All paths below were outside this workspace (`/TopsailAI/src/topsailai/cli`):

- `context/session_manager/sql.py:436` `_apply_session_filters(query, sessions=None, category=None)`
  applies only `Session.session_id.in_(sessions)` and
  `Session.category == resolve_session_category(category)`. There is no
  exclusion predicate.
- `context/session_manager/sql.py:444` `list_sessions(...)` applies the filters,
  then `_apply_order_by`, then `offset`/`limit`.
- `context/session_manager/sql.py:495` `count_sessions(sessions=None, category=None)`
  reuses the same filter helper.
- The same two signatures are declared in
  `context/session_manager/manager.py:38` and `:46`,
  `context/session_manager/base.py:35` and `:41`, and
  `context/session_manager/__base.py:160` and `:194`.

## Proposed fix
1. Extend `_apply_session_filters` with an `excluded_categories` parameter and
   add a `NOT IN` predicate, treating the empty string as the uncategorized
   category so `""` can be excluded like any other name.
2. Thread `excluded_categories` through `list_sessions` and `count_sessions` in
   `sql.py`, `__base.py`, `base.py`, and `manager.py`, keeping the default
   `None` so existing callers are unaffected.
3. Once the SQL path supports exclusion, drop the CLI's forced
   `offset=0`/`limit=None` workaround and the in-memory filter, and let the
   database paginate. Keep the CLI's argument parsing and validation, because
   rejecting an invalid category name before the query is still the CLI's job.
4. Add unit tests at the SQL layer for exclusion combined with `offset`/`limit`
   and for `count_sessions` with exclusion, plus a CLI test proving pagination is
   pushed down again.

## Resolution

The human authorized the cross-workspace change, so all four proposed steps are
implemented.

- `_apply_session_filters` accepts `excluded_categories` and applies
  `~coalesce(category, "") NOT IN (...)`. The `coalesce` keeps a NULL category
  counted as uncategorized instead of being silently dropped by the negated
  predicate, which matches the previous in-memory `str(value or "")` semantics.
- `list_sessions` and `count_sessions` thread the parameter through `sql.py`,
  `__base.py`, `base.py`, and `manager.py`. The default stays `None`, and
  `manager.py` only adds the keyword when the set is non-empty, so the existing
  exact-kwargs contract test keeps passing.
- The CLI no longer forces `offset=0`/`limit=None` and no longer filters in
  memory; `Matched Total` now comes from `count_sessions` with the same
  predicates. Argument parsing and validation stay in the CLI, and the SQL layer
  treats the names as already validated exact strings: resolving them again would
  turn an invalid name into the empty category and hide uncategorized rows.
- The missing `create_time` index is added as `idx_session_create_time`, created
  idempotently after the column migration because the SQLite table rebuild
  asserts the index inventory is unchanged.

## Why the index was also required

Pushing only the `NOT IN` predicate down still left the default
`ORDER BY create_time DESC` unindexed, so SQLite scanned the whole table before
returning the first page. Measured on a synthetic 200,000-row table: full read
plus in-memory filtering took 331 ms, the predicate alone took 29.75 ms, and the
predicate plus the index took 0.46 ms.

## Verification

- 189 tests pass across the SQL category, manager contract, manager SQL, and CLI
  list suites.
- Live runs against `/root/.topsailai/memory.db` (172 rows) return 140 rows when
  `agent_driver` is excluded, and `EXPLAIN QUERY PLAN` reports
  `SCAN session USING INDEX idx_session_create_time`.
- An invalid name such as `Agent` is still rejected with exit code 1.
- The full unit suite shows no failure unique to this change: comparing the
  `test_topsailai_hooks` and `test_session_stats_service` scope against a pristine
  worktree at the same HEAD yields 0 failures present only in the modified tree
  and 0 session-related failures in either tree.

## Known limitation left unfixed

`--has-project` and `--since`/`--until` are still applied after pagination, so a
page can be shorter than `--limit` and `Matched Total` ignores them. That is a
pre-existing defect unrelated to category exclusion and is reported rather than
changed here.
