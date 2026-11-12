---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_data
ProjectFolder: /TopsailAI/src/topsailai_data
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI_DATA
programming_language: go
---

# Manual and live execution report

## Result summary

113 cases were executed against the real compiled CLI: **111 PASS, 2 BLOCKED,
0 FAIL**.

Every number in this report is counted from the `results.jsonl` file of the
named run directory. A BLOCKED case is never counted as PASS.

## Module results

| Module | Cases | Run directory | PASS | BLOCKED | FAIL | Source file |
|---|---|---|---|---|---|---|
| A startup and configuration | CFG-01..13, CFG-15 | `run-a4` | 14 | 0 | 0 | `.tmp/manual-live/run-a4/reports/results.jsonl` |
| B objects and discovery | OBJ-01..09 | `run-b1b` | 9 | 0 | 0 | `.tmp/manual-live/run-b1b/reports/results.jsonl` |
| B objects and discovery | OBJ-10..16 | `run-b2b` | 7 | 0 | 0 | `.tmp/manual-live/run-b2b/reports/results.jsonl` |
| B objects and discovery | OBJ-17..24 | `run-b3b` | 8 | 0 | 0 | `.tmp/manual-live/run-b3b/reports/results.jsonl` |
| C files and archives | FILE-01..23 | `run-cfull` | 23 | 0 | 0 | `.tmp/manual-live/run-cfull/reports/results.jsonl` |
| D lifecycle and recovery | LIFE-01..17 | `run-dfull` | 17 | 0 | 0 | `.tmp/manual-live/run-dfull/reports/results.jsonl` |
| E statistics and concurrency | STAT-01..17 | `run-e2full` | 17 | 0 | 0 | `.tmp/manual-live/run-e2full/reports/results.jsonl` |
| F1 safety | SAFE-01..08 | `run-f1full` | 8 | 0 | 0 | `.tmp/manual-live/run-f1full/reports/results.jsonl` |
| F2 scale | SAFE-09..12 | `run-f2full` | 3 | 1 | 0 | `.tmp/manual-live/run-f2full/reports/results.jsonl` |
| F3 live acceptance | SAFE-13..18 | `run-f3approved` | 5 | 1 | 0 | `.tmp/manual-live/run-f3approved/reports/results.jsonl` |
| **Total** | **113** | — | **111** | **2** | **0** | — |

Per-module totals: CFG 14, OBJ 24, FILE 23, LIFE 17, STAT 17, SAFE 18.

## BLOCKED cases

| Case | Priority | Environment | Reason recorded in `results.jsonl` |
|---|---|---|---|
| SAFE-12 | P2 | I | `cross-OS platform evidence is unavailable on this host` |
| SAFE-18 | P0 | P | `human acceptance review is required; the same agent cannot certify its own work` |

SAFE-12 additionally depends on a scale budget. That budget is now approved as
the standard budget for a future run on an environment with multiple operating
systems: 2000 objects, 1 MiB payload per object, under 3 GiB disk, list and
search each under 60 s, and peak RSS under 512 MiB. The case still stays BLOCKED
because cross-OS platform evidence cannot be obtained on this single host, and
approving a budget does not change that. No new scale test is run for SAFE-12.

SAFE-17 was blocked because the actual removal step is irreversible and the
case only previewed the inventory. A human approved the reviewed inventory on
2026-11-11, so the case now runs its approved removal path through
`ML_SAFE17_APPROVED=1`. The approved path previews the owned targets, performs
the removal, and then verifies that every removal is logged, that the owned
targets are gone, that the protected backup file count and manifest are
unchanged, and that no sentinel was created inside the protected backup. All
thirteen assertions passed in `run-f3approved`. Without the approval switch the
case still previews only and stays BLOCKED, so the default behaviour is
unchanged.

SAFE-18 is blocked because the agent that implemented and executed these cases
cannot also certify the acceptance result. A human reviewer must confirm it.

## CFG-14 is not covered by automation

`cases-a-startup.sh` declares only `CFG-01` through `CFG-13` and `CFG-15`. The
`CASES=(...)` array contains no `CFG-14`, and `grep -c 'CFG-14'` on that script
returns 0.

CFG-14 covers real PTY startup and the separation of startup from interaction.
It has no automated case. It is covered only by the manual verification
performed with `terminal-start.sh` and `terminal-interact.sh`, which reported
readiness, captured the expected output and stopped only its own tmux session.

CFG-14 is therefore **not included in the automated inventory and not counted as
PASS**. The 113-case inventory and the 111 PASS total exclude it.

## Known limitations

These are design limits, not defects found by this run.

- No index. Listing and searching walk the store. At 10000 objects, list takes
  about 1 s, search about 1 s, peak RSS about 27 MiB and disk about 273 MiB. At
  100000 objects, historical observation was about 17 s for list, 22 s for
  search and about 1.2 GB cumulative allocation.
- Tag and metadata publication is not a cross-file transaction, and archive
  replacement is not a whole-package transaction. A failure between steps can
  leave the payload newer than the metadata.
- Statistics are best effort. `last_read_at` has a 1 minute debounce, so
  consecutive reads increase `read_count` without refreshing the timestamp.
- Locks only coordinate cooperating processes. They do not defend against a
  malicious concurrent path replacement or a power loss.
- Archive reads hold memory proportional to the archive size.
- The CLI has no interactive REPL. Invoked without a command it prints usage and
  exits 0.

## Product asymmetries

These are inconsistent behaviours between related commands. They are recorded
for disclosure, not classified as test defects.

1. `put` rejects a source that is the same file as the destination, but
   `file write`, `file append`, `file insert` and `file overwrite-lines` have no
   such guard.
2. `file write ../escape` and `file write /tmp/x` are normalized into the object
   and succeed, while `put` rejects the same paths.
3. `put-archive` is not transactional. It clears the payload before parsing, so
   a malformed, truncated or symlink-bearing archive is rejected after the
   original payload is already lost or partially replaced.
4. Empty directory tar entries are accepted but never materialized.
5. `file exists` validates `name=path` before `--object`.
6. Default `gc` writes cleanup detail only to stderr; stdout carries just
   `gc completed for ceased objects`.
7. `tag add` of an already present tag still counts one write operation.
8. `STAT_FLUSH=async` still writes synchronously.
9. The namespace lock is a non-blocking exclusive flock, so a competing CLI
   process fails fast instead of queueing.
10. After an interrupted operation, a resident `lock` file remains under `meta`.
    This is by design, not a leak.
11. When metadata publication fails during `put`, the payload has already been
    replaced and is not rolled back.
12. When metadata publication fails during `move`, the target copy already
    exists while the source is retained, so the target needs manual cleanup.
13. `get-archive` packages a symlink inside the payload as a symlink entry,
    while `get`, `file read`, `file write` and `move` all reject it as
    `payload alias ... invalid path`.
14. An interrupted write leaves a `.topsailai-data-write-*` temporary file in the
    payload directory. It is excluded from archive reads, folder trees, existence
    checks and move copies, and is removed at the GC boundary after 24 hours.
15. Object names have no product-level length limit. The boundary is the
    filesystem `NAME_MAX`: 252 characters succeed, 253 characters are rejected
    by the filesystem.
16. A legacy `object/.stat.json` is no longer updated by the current binary. It
    is treated as ordinary user data and becomes an orphan record.

## Live store statistics pollution

Two legacy `object/.stat.json` records in the live store changed during this
session:

| Record | Change |
|---|---|
| `note--ai-reflection-archive/.stat.json` | `read_count` 299 to 300, `last_read_at` 08:17:35 to 16:53:23 |
| `note--topsailai-deb-update-runbook/.stat.json` | `read_count` 15 to 16, `last_read_at` 12:50:20 to 14:54:02 |

Root cause: these reads happened before commit `f61ba22f` activated the separate
payload and Hash metadata layout at 12:47:30. The pre-cutover binary wrote
statistics into `object/<path>/.stat.json`, and those reads did not set
`TOPSAILAI_DATA_TRACK_STAT=0`.

The current binary only writes `meta/<hash>/stat.json`. A legacy
`object/.stat.json` is now treated as ordinary user data and is never updated,
which was confirmed by placing a legacy record in an isolated store and observing
that its digest was unchanged after a read.

Impact is limited to read counters and read timestamps. Payload content,
metadata records, lifecycle status and the object inventory are unchanged, and
`write_count` and `last_written_at` are untouched in both records.

Prevention: every read against the live store must set
`TOPSAILAI_DATA_TRACK_STAT=0`. SAFE-13, `observe-layout.sh` and
`terminal-start.sh` all enforce this, and SAFE-13 proves zero writes with a
before and after manifest of 1106 files.

Decision: the two counters are **not** restored. A one increment in `read_count`
and the updated `last_read_at` are harmless, while restoring them would require
writing to the live store, so the risk outweighs the benefit. The current state
is kept as is. See the decision record at the end of this report.

## SAFE-18 pending human acceptance

The agent that implemented and executed these cases cannot claim an independent
acceptance review. Acceptance requires every applicable P0 and P1 case to pass,
no unresolved data-loss defect, and an explicit disposition for each BLOCKED
case. A human reviewer must perform that review and record the outcome.

## Documentation and implementation mismatches

| Document | Claim | Observed behaviour |
|---|---|---|
| `docs/DESIGN.md` 7.13 | `creating` objects are not visible in `show` | `show` displays them with `Status: creating` |
| `docs/DESIGN.md` 7.13 | `deleted` objects allow reading actual data | `get`, `get-archive` and `file read` all reject them |
| `docs/DESIGN.md` 12.7 | default `gc` scans only `creating` and `ceased` | default `gc` also finalizes `deleted` objects |
| `skills/topsailai-data/SKILL.md` | `deleted` objects allow reading actual data | same rejection as above |
| `skills/topsailai-data/SKILL.md` statistics section | does not state the `stat.json` schema version | the record uses `schema_version: 1`, independent of the object record version |
| `skills/topsailai-data/SKILL.md` statistics section | does not state the read timestamp debounce | `last_read_at` has a 1 minute debounce |
| `docs/DESIGN.md` 19 and `SKILL.md` write-source safety | `put-archive` rejection preserves the original object data | preserved for an overlapping source, but a symlink-bearing archive is rejected after resolved entries are already written |
| `docs/DESIGN.md` | does not declare an object name length limit | 252 characters succeed, 253 characters are rejected by the filesystem |
| `docs/DESIGN.md` and `SKILL.md` | do not declare the legacy `object/.stat.json` disposition | treated as ordinary user data and never updated |
| `docs/DESIGN.md` and `SKILL.md` | do not declare the `metadata.json` key style | `metadata.json` uses PascalCase (`ID`, `Name`, `Path`, `Status`, `SchemaVersion`, `DataRef`) while `list --format json` uses snake_case |
| `docs/DESIGN.md` and `SKILL.md` | do not declare the absence of an interactive REPL | no command prints usage and exits 0 |

## Helper scripts and their commits

Each hash below was read with `git log --oneline -1 -- <path>` at report time.

| Script | Commit | Message |
|---|---|---|
| `run-live.sh` | `bc18daf1` | `test: add manual live case runner` |
| `observe-layout.sh` | `3b29704c` | `test: add manual live layout observer` |
| `fault-fixtures.sh` | `c0997943` | `test: add manual live fault fixtures` |
| `lock-holder.sh` | `00be686b` | `test: add manual live lock holder` |
| `terminal-start.sh` | `cd1a3e4a` | `test: add manual live terminal harness` |
| `terminal-interact.sh` | `cd1a3e4a` | `test: add manual live terminal harness` |
| `cleanup.sh` | `41b3f953` | `test: add manual live cleanup script` |

Supporting scripts and case scripts:

| Script | Commit | Message |
|---|---|---|
| `lib.sh` | `e5cd88b9` | `feat: wire include-deleted config and reject negative pagination` |
| `prepare.sh` | `e5cd88b9` | `feat: wire include-deleted config and reject negative pagination` |
| `cases-a-startup.sh` | `c0997943` | `test: add manual live fault fixtures` |
| `cases-b-objects.sh` | `20a0bbf6` | `test: add manual live object discovery cases obj17 to obj24` |
| `cases-c-files.sh` | `5d674517` | `test: add manual live file cases file09 to file23` |
| `cases-d-lifecycle.sh` | `ec52e1ce` | `test: add manual live lifecycle cases life09 to life17` |
| `cases-e-stat.sh` | `cbdf3df6` | `test: add manual live statistics cases stat09 to stat17` |
| `cases-f-safety.sh` | `023701e2` | `test: add manual live safety cases safe01 to safe08` |
| `cases-f-scale.sh` | `c0997943` | `test: add manual live fault fixtures` |
| `cases-f-live.sh` | `1e0cf202` | `test: add manual live acceptance cases safe13 to safe18` |

## Safety contract observed during execution

- Every mutating case used an isolated root. The live store was read only, with
  `TOPSAILAI_DATA_TRACK_STAT=0`.
- `.tmp/data-recovery/20261111125501/original/` was never deleted, modified or
  committed. Its file count is 782 before and after the cleanup run.
- No `killall` or `pkill -f` was used. Processes and tmux sessions were stopped
  only by the exact PID or session name owned by the test.
- All stores, logs, reports and fixtures were written under `.tmp/`.
- Saved failure output was inspected before any rerun.
- Sibling project changes under `src/topsailai_agent_cluster/` were left
  untouched and never staged.

## Decision record

The open items were decided by the human on 2026-11-11. The decisions are
recorded here so the BLOCKED status is not mistaken for an unresolved question.

### SAFE-12 scale budget: approved, case stays BLOCKED

The proposed budget is approved as the standard budget for a future run on an
environment with multiple operating systems:

- 2000 objects
- 1 MiB payload per object
- under 3 GiB disk
- `list` and `search` under 60 s each
- peak RSS under 512 MiB

SAFE-12 remains **BLOCKED** and is not counted as PASS. The reason is unchanged:
cross-OS platform evidence cannot be obtained on this single host, and approving
a budget does not change that. No new scale test is to be run for SAFE-12.

### Live store legacy statistics: not restored

The two legacy `object/.stat.json` read counters are **not** restored. A one
increment in `read_count` and the updated `last_read_at` are harmless, while
restoring them would require writing to the live store, so the risk outweighs
the benefit. The current state is kept as is.

### SAFE-18 human acceptance: stays BLOCKED

SAFE-18 remains **BLOCKED** pending a human acceptance review. The reviewer and
the review time are arranged separately by the human. This agent implemented and
executed the cases, so it does not self-certify and does not sign on the human's
behalf.

### SAFE-17 approved cleanup: executed, case now PASS

The human approved the reviewed cleanup inventory on 2026-11-11, so SAFE-17 no
longer stays BLOCKED. The case now has an approved removal path behind
`ML_SAFE17_APPROVED=1`. The approved path previews the owned targets, performs
the removal, and verifies the removal log, the disappearance of the owned
targets, the unchanged protected backup file count and manifest, and the absence
of a sentinel inside the protected backup. All thirteen assertions passed in
`run-f3approved`, so SAFE-17 is counted as PASS.

The default path is unchanged: without the approval switch the case still
previews only and stays BLOCKED, which was verified in `run-safe17b`. The
irreversible removal therefore still requires an explicit approval every time.

Two symlinks that pointed at the protected backup were removed with `rm -f`,
which deletes the link and never follows it. The protected backup still holds
782 files and its manifest is unchanged.
