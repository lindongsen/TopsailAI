---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
status: open
---

# Reaper cannot clean an owner record left by a SIGKILLed driver

**Status:** open, registered only, not fixed in this change
**Severity:** low
**Discovered:** 2026-11-13 while attributing the `test_driver_reaper.py::TestEndToEnd` failure

## Symptom

When the driver process is terminated with `SIGKILL`, its `atexit` finalizer never
runs, so the session metadata file keeps `status: "running"`. The exit reaper then
observes `UNKNOWN` and refuses to delete the record, leaving a permanent orphan.

## Reproduction

A child process writes a realistic owner record with `status: "running"`, then is
killed with `SIGKILL` before its finalizer can run:

```text
child killed, pid: 609990
observation: ActivityObservation(state=unknown, reason='incomplete owner evidence')
can_clean: False
```

## Root cause

`SessionActivityProbe._observe_owner()` authorizes deletion only when
`data.get("status")` is one of `completed`, `error`, or `interrupted`. A record
still marked `running` is treated as incomplete evidence and fails closed.

That fail-closed rule is correct for its original purpose: a live owner must never
be deleted. The gap is that nothing converts a `running` record into a terminal
status once the owning process can no longer do it itself. The reaper knows the
owner PID is gone, but it does not own the metadata file and does not rewrite it.

## Impact

- The orphan record is never deleted, so the task directory grows without bound
  across repeated hard kills.
- The session row in the database is also preserved, because
  `reap_sessions()` skips the row deletion when `can_clean()` refuses.
- No data is lost and no live session is harmed, so the severity is low.

## Why this is not fixed here

Fixing it requires a production decision that is not mine to make: either the
reaper rewrites the metadata status after confirming the owner PID is gone, or the
probe accepts a `running` record whose PID is provably absent. Both change the
cleanup authorization contract, which is security-sensitive and was deliberately
tightened in `41529104 fix: enforce strict session deletion checks`.

## Suggested direction

Let the reaper, after `wait_for_parent_exit()` returns true, finalize the metadata
of the sessions it owns by setting `status: "interrupted"` and `end_ts`, then run
the existing probe. This keeps the probe's fail-closed rule untouched and puts the
status transition in the component that already holds the authoritative
"the owner is gone" observation.

## Related

- `scripts/session_agent_driver/driver_reaper.py` — `reap_sessions()`
- `context/session_activity.py` — `_CLEANABLE_OWNER_STATUSES`, `_observe_owner()`
- `workspace/session_meta.py` — `_finalize_on_exit()`, `update_session_meta_status()`

## Analysis on 2026-11-18: reproduced, and blocked by two recorded Human decisions

### Reproduction confirmed

A real child process wrote a realistic owner record, was killed with `SIGKILL`, and
the probe refused cleanup exactly as the issue describes:

```text
observation: ActivityObservation(state=<ActivityState.UNKNOWN: 'unknown'>, reason='incomplete owner evidence')
can_clean   : False
meta still present: True
meta status: running
```

### Both options proposed above are pre-rejected by recorded Human decisions

- **Rewriting the metadata to `interrupted`** contradicts `MEMORY.md` section
  "Abnormal exits must preserve the on-disk scene instead of rewriting state". The
  Human rejected exactly this class of write with "兜底逻辑为什么还要去设置meta里面的状态？"
  and required that `status: running` with `end_ts: null` remain the evidence that
  the process died without finalizing.
- **Accepting a `running` record whose PID is absent** contradicts the reaper
  authorization constraints in `MEMORY.md`, which state explicitly: do not add
  `running` to `_CLEANABLE_OWNER_STATUSES`, do not relax the hostname comparison.

So this is not an open design question. It is a conflict between two Human rules,
and it needs an explicit Human disposition rather than an autonomous choice.

### Why the existing orphan path cannot cover this case

`_exclude_expired_orphan()` returns `UNKNOWN` immediately when any artifact name
ends with `.session.meta`. A `SIGKILL`ed owner always leaves its `.session.meta`,
so that path is unreachable here by construction.

### Option C, measured in a probe without touching production code

Option C reclaims the record as expired residue instead of rewriting it: the
metadata bytes are never modified, and deletion is authorized only when the PID is
provably absent and every remaining artifact has expired.

```text
--- stdout FRESH (within retention) ---
  current : unknown | can_clean: False
  option C: unknown | can_clean: False
  meta status after decision: running | meta exists: True
--- stdout EXPIRED (past retention) ---
  current : unknown | can_clean: False
  option C: stopped | can_clean: True
  meta status after decision: running | meta exists: True
```

Option C satisfies both recorded rules: it never rewrites state, and it never adds
`running` to `_CLEANABLE_OWNER_STATUSES`. It still fails closed while any artifact
is inside the retention window, so a recently killed owner is protected.

### Decision required

Option C is a new design, not an approved one. It needs Human approval before any
production change, because it relaxes a cleanup authorization gate that was
deliberately tightened in `41529104 fix: enforce strict session deletion checks`.
The three candidates are:

1. Option C — reclaim as expired residue, never rewrite the metadata.
2. Option A — the reaper rewrites the metadata; requires relaxing the abnormal-exit rule.
3. Option B — the probe accepts an absent-PID `running` record; requires relaxing the
   `_CLEANABLE_OWNER_STATUSES` rule.

No production code has been changed for this issue.
