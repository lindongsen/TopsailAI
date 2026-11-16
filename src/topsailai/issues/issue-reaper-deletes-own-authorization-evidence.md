---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---

# Reaper Deletes Its Own Authorization Evidence And Reports False Success

Status: fixed and committed in `e2d595a6`.

## Symptom

`topsailai workspace list` kept showing session agent driver sessions whose
`meta` record was already gone, while `stats.jsonl` and `stdout` stayed on disk
for weeks. The reaper log reported `reaped=N of N` for those same runs.

## Root Cause

Two defects combined, and each one hid the other.

1. `driver_reaper.py::_delete_owner_records()` iterated
   `sorted(directory.iterdir())`, which places `meta` second:
   `events -> meta -> pipe -> sock -> stats.jsonl -> stdout`. It re-checked
   `probe.can_clean()` before every single deletion, and
   `session_activity.py` authorizes cleanup only from exactly one complete
   `meta` record. Deleting `meta` therefore made every later check return
   `UNKNOWN`, the loop `break`ed, and the remaining records survived forever.
2. `reap_sessions()` counted a session as reaped as soon as its database row was
   deleted, regardless of whether its files were removed. `main()` printed
   `reaped=%d of %d` from that count, so a run that deleted the metadata and
   preserved the statistics still reported full success.

## Evidence

Reaper log, `/root/.topsailai/log/session_agent_driver_reaper.log`:

```
deleted owner record ...session.events
deleted owner record ...session.meta
Preserve session sad-5eef89092343: unknown (incomplete owner evidence)
preserved owner record ...session.stats.jsonl: cleanup not authorized
```

Across all runs: 12 `session reaper finished` lines, 10 of them `reaped=0`;
`deleted owner record` fired 7 times (`events` 2, `meta` 5) and
`preserved owner record` 5 times, all `stats.jsonl`. The two counts match
exactly, which is the fingerprint of this defect.

Negative control against a real `SessionActivityProbe`:

```
ORIGINAL (identity order): deleted=2 preserved=3 residue=['sock', 'stats.jsonl', 'stdout']
FIXED    (meta last)    : deleted=5 preserved=0 residue=none
```

## Fix

- Added `_deletion_order()`, a stable sort that moves every `.session.meta`
  record to the end while preserving alphabetical order inside each group.
- `_delete_owner_records()` now returns `(deleted, preserved)` and records every
  surviving record after an unauthorized check, not only the current one.
- `reap_sessions()` accepts an optional `report` mapping, logs a session with
  preserved files as `partially reaped`, and keeps it out of the reaped list.
  The return value stays `list[str]` because seven existing tests assert it.
- `main()` reports `reaped`, `partial`, `deleted_files` and `preserved_files`,
  and warns when any file was preserved.

## Verification

- `scripts/session_agent_driver/tests/test_driver_reaper.py`: 61 passed
  (54 pre-existing + 7 new).
- Cross-module regression over the session activity, cleanup guard, cleanup
  edges, session meta and driver test suites: 413 passed.
- Real owner records: `20261027152208` (360 records, `meta` at position 360),
  `20261104171249` (58 records, all 24 `meta` after 34 `stats.jsonl`),
  `20261105123026` (3 records, `meta` last).

## Not Covered

- Orphan PIDs without `meta` still poison their whole session, so
  `20261027152208` remains uncleanable.
- Existing residue is not reclaimed; this fix only stops new residue.
- `StatsRetention` still has no production caller, `sock` still has no retention
  path, and `ARTIFACT_SUFFIXES` still omits `stats.jsonl` and `sock`.

## Related

- `issues/issue-reaper-cannot-clean-sigkilled-owner-record.md` — a SIGKILLed
  owner leaves `status: running`, which is a different blocking cause.
- `cli/issues/issue-agent-driver-self-cleanup-never-authorized.md` — the driver
  cannot authorize deletion of its own analysis session, also different.
