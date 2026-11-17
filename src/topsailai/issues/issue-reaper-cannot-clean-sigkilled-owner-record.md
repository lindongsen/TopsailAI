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
