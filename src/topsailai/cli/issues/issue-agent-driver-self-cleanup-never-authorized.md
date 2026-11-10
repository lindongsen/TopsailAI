---
maintainer: AI
author: DawsonLin
---
# The session agent driver can never delete its own analysis sessions

## Status
Open. Reported, not fixed. The defect lives outside this workspace
(`/TopsailAI/src/topsailai/cli`), in `scripts/session_agent_driver/` and
`context/`, so it is recorded here instead of being changed.

## Requested by the human
While reviewing the `agent_driver` exclusion for `topsailai project list_sessions`,
the human asked what the cleanup-policy interaction actually was. Investigating
that question surfaced this independent defect. The human then instructed:
file one issue for it.

## Summary
`cleanup_analysis_session()` is called in the driver's own `finally` block, but the
analysis session's owner record carries the driver's own PID. Cleanup authorization
requires a `STOPPED` observation, and the driver is by definition still running at
that moment, so the deletion is refused every single time. The analysis session is
never removed.

## Behaviour observed
The driver logs only refusals, never a success:

```
WARNING analysis session sad-446a903a9b28 retained: deletion not authorized
WARNING analysis session sad-bc8de3f05f1d retained: deletion not authorized
WARNING analysis session sad-11716e82f419 retained: deletion not authorized
WARNING analysis session sad-075adf7cee87 retained: deletion not authorized
WARNING analysis session sad-0b7dfbea7d84 retained: deletion not authorized
```

Across `/root/.topsailai/log/`, `retained: deletion not authorized` appears 5
times and `cleaned analysis session` appears 0 times.

## Root cause chain

1. `scripts/session_agent_driver/session_agent_driver.py:516` states the design
   directly: `# The analysis agent runs in this process, so the target session's
   workspace must be exported before the agent is constructed.` The analysis agent
   is constructed in the driver's own process, not in a child process.

2. Because the agent runs in-process, the session owner record is written by the
   driver itself. `workspace/session_meta.py:106` builds the filename as
   `f"{session_id}.{os.getpid()}.session.{META_EXTENSION}"` and `:240` stores
   `"pid": os.getpid()`. Both resolve to the driver's PID.

3. `scripts/session_agent_driver/session_agent_driver.py:568` calls
   `cleanup_analysis_session(analysis_session_id)` from the `finally` block, so the
   driver process is necessarily alive during cleanup.

4. `context/session_activity.py:116` `can_clean()` authorizes deletion only after a
   fresh `STOPPED` observation. The owner PID is the live driver, so the observation
   is `RUNNING` and `can_clean()` returns `False`.

5. `scripts/session_agent_driver/session_agent_driver.py:443` therefore logs
   `retained: deletion not authorized` and returns without deleting.

The precondition for deletion is "the owner process has stopped", while the only
caller is that very owner process. The two conditions cannot both hold, so this is
a structural deadlock rather than a transient failure.

## Verified evidence

Owner PID equals the driver PID for a real analysis session:

```
$ cat /root/.topsailai/workspace/task/sad-446a903a9b28.992638.session.meta
{ "session_id": "sad-446a903a9b28", "category": "agent_driver", "pid": 992638, ... }

$ ps -p 992638 -o pid,cmd
992638 /TopsailAI/.venv/bin/python3 .../session_agent_driver.py --session wa-edabfc86a813
```

Activity probe result for the same session:

```
sad-446a903a9b28 -> running | live associated PID | can_clean: False
```

## Accumulation measured on this host

| Measurement | Value |
|---|---|
| `agent_driver` rows in the database | 55 |
| Distinct `agent_driver` session IDs with files on disk | 101 |
| Present on disk but absent from the database | 46 |
| `sad-` files in `workspace/task/` | 214 |
| Rows by creation date | 2026-11-07: 3, 2026-11-08: 24, 2026-11-10: 28 |

The trend is monotonically increasing, and nothing reclaims the rows.

## Why no existing mechanism reclaims them

- **Retention eviction does not apply.** `context/session_cleanup.py:13` defines
  `RETENTION_EXCLUDED_CATEGORIES = frozenset({SESSION_CATEGORY_AGENT_DRIVER})`, and
  `:88` filters those rows out of `counted` before the threshold is computed. That
  exclusion is correct and intentional: without it a driver backlog would evict
  ordinary user sessions. The consequence, however, is that eviction can never
  select a driver row either.
- **Age-based cleanup is never scheduled.** `clean_sessions()` is reachable only
  through the manual `cli/ai_clean_sessions.py`. No crontab entry, no
  `/etc/cron.d` entry, and no systemd timer invokes it on this host.
- **Database deletion does not remove files.** `context/session_manager/sql.py:677`
  `delete_session()` deletes the row and the chat history, then commits. It never
  touches `.session.meta`, `.session.stdout`, or `.session.stats.jsonl`. This
  explains the 46 IDs that exist on disk but not in the database.

## Impact

- Unbounded growth of both database rows and task-directory files, one analysis
  session per driver poll.
- The task directory is scanned by session discovery and status resolution, so a
  growing file inventory raises the cost of unrelated operations.
- The `retained: deletion not authorized` warning is emitted on every poll, so a
  genuine authorization failure would be indistinguishable from this expected one.

## Proposed fix options

1. **Run the analysis agent in a child process.** The owner record would then carry
   the child PID, which stops before the parent's `finally` runs, so the existing
   `can_clean()` contract authorizes deletion without weakening any guard. This is
   the semantically clean option and the preferred one, but it is the larger change
   because the in-process design is relied on for workspace export, argv isolation,
   and the input monitor.
2. **Add an explicit self-cleanup exception.** Allow deletion when the caller is the
   process that owns the record. This is smaller, but it weakens the fail-closed
   guard that currently prevents deleting a live session, so it needs a very narrow
   predicate and dedicated tests.

Option 1 is recommended. Option 2 should only be taken with explicit human approval,
because the guard it relaxes is the one protecting live sessions from deletion.

## Related but separate

The `agent_driver` rows also appeared in `topsailai project list_sessions`, because
`apply_project_workspace()` exports the target session's project workspace into the
driver process and those rows therefore carry a non-empty `project_workspace`. That
display-layer defect is already fixed and committed as
`d123ef4e fix: exclude agent_driver sessions from project list`. It is recorded here
only to explain why these rows were visible; it is not part of this issue.

## Verification performed while reporting

- Confirmed the owner PID in a real `.session.meta` equals the live driver PID.
- Confirmed `can_clean()` returns `False` for that session and `True` for a stale
  one whose owners are all absent.
- Counted refusals versus successes across the log directory.
- Counted database rows, on-disk session IDs, and the disk-only difference.
- Checked crontab, `/etc/cron.d`, and systemd timers for any scheduled cleanup.
- Read `delete_session()` to confirm it performs no filesystem cleanup.
