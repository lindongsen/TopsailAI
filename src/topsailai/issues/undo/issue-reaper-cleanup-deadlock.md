---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
status: wontfix
---

# Session Cleanup Deadlock: Four Independent Blockers

## Disposition: wontfix, the gates are correct

The Human reviewed this report on 2026-11-17 and decided: "这个issue不解决，逻辑都是对的".
All four gates are intended fail-closed safety behavior, not defects. A wrong
deletion destroys a live session's evidence and is unrecoverable, while a skipped
deletion only wastes disk, so the asymmetry is deliberate. Every deletion path
already funnels through `can_clean` with no bypass, and 44 unit tests in
`tests/unit/test_topsailai_context_session_activity.py` pin the behavior.

The measurements below remain valid as a capacity and observability record. The
"Required decisions" section is closed: none of the four changes will be made
without explicit Human authorization. Reclaiming disk is a retention-policy,
cross-host-ownership, or manual-operator problem, never a reason to weaken the
authorization predicate. See `MEMORY.md` for the binding rule.

## Symptom

Session metadata and artifacts accumulate without bound. The reaper log reports
`reaped=0 of 51` and `reaped=0 of 2`. At the original measurement (2026-11-16),
of 67 metadata files older than the 7-day retention only 2 were deletable, and
the task directory held 958M, of which `.session.events` accounted for 471.6M.

Re-measured 2026-11-17 on host `topsail`: 39 metadata files are older than the
7-day retention, the task directory holds 832M, `.session.events` accounts for
530M, and none of the 39 expired files is reclaimable. The exact figures are in
the baseline table below.

## Retracted hypotheses

Two earlier explanations were wrong and are retracted here.

1. `_CLEANABLE_OWNER_STATUSES` excluding `running` was blamed as the deadlock.
   Measurement shows it blocked only 3 of the then-522 metadata files. It is a
   minor contributor. Adding `running` to that set would delete live sessions and
   would leave the dominant blockers untouched.
2. The reaper log reason `unknown (unverified recorded home)` was cited as
   current evidence. That defect was fixed by `493bb9f5` on 2026-11-14 20:55:45.
   All 107 log lines carrying that reason predate the fix. Re-running the probe
   now yields `incomplete owner evidence`, never `unverified recorded home`.

## Measured baseline

Original measurement (2026-11-16) and re-measurement (2026-11-17, host `topsail`):

| Metric | Original | Re-measured |
|---|---|---|
| Metadata files | 522 | 499 |
| Hostname `ai-dev` / `topsail` | 355 / 167 | 358 / 141 |
| Status `completed` / `interrupted` / `running` / `error` | 262 / 233 / 25 / 2 | 310 / 154 / 33 / 2 |
| Database `session` rows | 351 | 394 |
| Metadata older than 7 days | 67 | 39 |
| Task directory size | 958M | 832M |

Current host is `topsail`; all 394 database rows record
`topsailai_home = '/root/.topsailai'`.

Batch observation over the 465 distinct `session_id` values behind the 499
metadata files returns 148 `stopped`, 305 `unknown` and 12 `running`. So 148
session groups are individually cleanable, but every one of them is younger than
the 7-day retention: the 100 metadata files in those groups range from 0.13 to
6.99 days old, and none exceeds 7 days. All 39 expired files belong to `unknown`
groups, so the retention pass reclaims nothing while the directory keeps growing.

Breakdown of the 305 `unknown` verdicts, classified by the first gate that
rejects the group (re-measured 2026-11-17):

| Cause | Groups | Expired files (>7d) |
|---|---|---|
| hostname mismatch (`ai-dev`) | 302 | 39 |
| status `running` with dead PID | 3 | 0 |

The earlier breakdown (229 hostname / 40 no owner records / 8 metadata count /
1 running) is superseded: the `no owner records` and `metadata count != 1`
classes no longer appear, because `_exclude_expired_orphan` now releases a dead
owner whose artifacts have all expired.

The `running`-with-dead-PID count has grown sharply: 26 of the 33 `running`
metadata files now belong to dead PIDs, up from 1.

## Blocker 1: hostname mismatch (358 sessions)

`_observe_owner` requires an exact hostname match at
`context/session_activity.py:342`. Host and the `ai-dev` container share one
filesystem and one database:

- `/root/.topsailai` resolves to `/opt/git/ai/lindongsen/work/hosts/.topsailai`
- task directory inode is identical from both sides: `66307:7037422`
  (re-verified 2026-11-17)
- both sides see the same 499 metadata files
- all 394 database rows record the same `topsailai_home`

Hostname is therefore the only ownership discriminator. Neither side can clean
the other's records, and no component is responsible for cross-host cleanup.
This is the dominant blocker: 358 of the 499 metadata files carry hostname
`ai-dev`, and 28 of the 39 files older than 7 days are `ai-dev`-owned. The
previously cited group `20261104171249` no longer exists on disk.

The two hosts also write into the same `session_id`, which is what makes this
blocker bite. Of the 39 expired files, 25 sit in a group that contains both
`ai-dev` and `topsail` records, 14 sit in a pure `ai-dev` group, and none sits in
a pure `topsail` group. A resumed session keeps its `session_id` but gets a new
PID and a new hostname, so the `topsail` record is individually cleanable while
its `ai-dev` sibling is rejected here and drags the whole group to `unknown`
through Blocker 2. Verified on `wa-292a34fdcf01`: PID `1355243` is `topsail`,
dead and `interrupted`, but PID `2618116` is `ai-dev`, so the group is `unknown`.

## Blocker 2: session_id aggregation blocks cleanable owners behind unknown siblings

`_observe_session_owners` returns RUNNING if any owner PID is RUNNING
(`context/session_activity.py:268`). `_cleanable_sessions` returns one boolean
per `session_id` (`workspace/session_meta.py:388`), and `_remove_cleanable_meta`
gates every file with `decisions.get(session_id)` (`workspace/session_meta.py:444`).
One non-cleanable owner therefore protects every cleanable owner sharing the same
`session_id`. The original report described this as one live PID protecting dead
ones; the current instance is 1234 `unknown` owners protecting 24 `stopped` ones.

Worst case is the `topsailai` fallback group, produced when a metadata record has
an empty `session_id` and `_parse_meta_session_id` falls back to the filename
prefix. Re-measured 2026-11-17:

- 1333 owner files, 1258 distinct PIDs, 53 metadata records
- **zero** alive PIDs; 24 owners observe `stopped`, 1234 observe `unknown`
  (the `unknown` owners are `ai-dev`-hostname records rejected by Blocker 1)
- verdict for the whole group: `unknown / strict owner inventory`
- 18 metadata files older than 7 days are blocked

The blocking mechanism has shifted since the original measurement. It is no
longer one live PID protecting dead ones: every PID is dead, and the 24 owners
that are individually cleanable are blocked by the 1234 `unknown` siblings that
share the same `session_id`. Verified directly: owner `topsailai.1163405`
observes `stopped`, yet `can_clean` on its metadata returns `False` because the
group verdict is `unknown`. Blocker 1 therefore amplifies into Blocker 2, and
fixing either one alone does not release these files.

## Blocker 3: owner records without metadata block their whole group

`_observe_owner` returns UNKNOWN when `len(metadata) != 1`
(`context/session_activity.py:325`). Two shapes trigger it: a PID that left only
`session.stats.jsonl` or `session.events` and no metadata, and a PID that owns
more than one metadata record. Because the gate is per `session_id`, either shape
blocks every sibling metadata file in the group.

Verified case (re-measured 2026-11-17): PID `1032291` is dead and owns 66
metadata records, all status `completed`, each in its own `session_id` group
(`sad-04dc509079bb`, `sad-11bce726598f`, `sad-18a017998026`, ...). Every group
has exactly one metadata file, but the owner has 66, so `len(metadata) != 1`
returns UNKNOWN for all 66 and none can be reclaimed. Twelve dead PIDs currently
own more than one metadata record.

The previously cited case `wa-c518390fa981` no longer exists on disk; the
mechanism it demonstrated is unchanged and is now evidenced by the case above.

## Blocker 4: empty session_id is excluded from the candidate set

`_capture_cleanup_candidates` skips any path whose parsed `session_id` is falsy
(`workspace/session_meta.py:404`), and `_cleanable_sessions` filters the same way
(`workspace/session_meta.py:393`). A metadata file whose filename cannot yield a
session identifier is therefore never a deletion candidate and never even
receives a verdict.

In practice `_parse_meta_session_id` falls back to the filename prefix, so
`topsailai.1604.session.meta` parses as `topsailai` and lands in Blocker 2's
group rather than being dropped. The exclusion path remains reachable for any
filename that does not match `{session_id}.{pid}.session.meta`, and such a file
would be preserved silently with no log line.

## Amplification

- `SessionCleanupManager.delete_session` calls `_can_clean` twice
  (`context/session_cleanup.py:76,78`), and `_can_clean` re-reads the database
  row before each observation (`context/session_cleanup.py:69-72`).
- `_delete_owner_records` re-runs `can_clean` for every file
  (`scripts/session_agent_driver/driver_reaper.py:246`).
- `HistoryCleanupManager._can_clean_message` requires every owning session to be
  cleanable (`context/session_cleanup.py:40`), so one blocked session also
  protects its chat history.
- `.session.meta.tmp` files are preserved by design
  (`workspace/session_meta.py:532-539`) and never expire.

## Disk composition

Task directory total 832M (re-measured 2026-11-17 on host `topsail`):

| Artifact | Files | Size |
|---|---|---|
| `.session.meta` | 499 | 0.5 MB |
| `.session.stdout` | 61 | 127 MB |
| `.session.events` | 1260 | 530 MB |

Orphan events without a matching metadata file are 1039 files but only 10.2 MB.
The large events files do have matching metadata and are blocked by
authorization, not orphaned. Deleting orphan artifacts alone would reclaim
almost nothing.

## Closed decisions

All four questions below were answered "no change" by the Human on 2026-11-17.
They are retained only as a record of what was considered and rejected.

1. Cross-host cleanup policy: rejected. A host does not delete records written by
   another host, even when both share one inventory.
2. Gating granularity: rejected. Authorization stays per `session_id`; it is not
   moved to per owner PID.
3. Owner records without metadata: rejected. They keep blocking their group.
4. Empty or unparsable `session_id`: rejected. Such metadata stays unreclaimable
   by retention.
