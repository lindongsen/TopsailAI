---
maintainer: AI
author: DawsonLin
status: planned-not-executed
---

# Safety, scale and live acceptance

Apply [execution rules](README.md). All variants NOT RUN. Every fault must be proven in a disposable fixture, not assumed because chmod was requested while running as root.

| ID | Priority / environment | Given | When | Then |
|---|---|---|---|---|
| SAFE-01 | P0 F | Interrupted single-file write before rename | Put/file write | Old digest unchanged, error surfaced; temporary lifecycle observable |
| SAFE-02 | P0 F | Metadata publication fault after actual write | Update data | Error returned; existing payload not deleted; already-written content may remain, no rollback promise |
| SAFE-03 | P0 F | Move copy/publication/source-cleanup faults | Exercise each boundary | Prepublication source/ref retained; postpublication new ref authoritative and cleanup error reported; preserve copies until reconciliation |
| SAFE-04 | P0 F | Tags published but later metadata fails | Tag mutation | Report exact resulting state/error; no fabricated cross-file atomicity |
| SAFE-05 | P0 F | Interior payload/Hash alias or special node | Read/write/archive/move/GC applicable variants | Unsafe paths refused; external sentinels unchanged; no hostile-race certification |
| SAFE-06 | P1 F | Corrupt/unknown-field/wrong-ID/schema/ref metadata | Get/list/show/move | Clear corruption result, no payload scan fallback or inferred deletion/repair; never silently accept missing inventory |
| SAFE-07 | P1 F | Bounded quota/permission/no-space sandbox | Initialize/write/finalize | Proven fault, actionable error, no false success; do not fill host disk/change global mounts |
| SAFE-08 | P1 I/F | Success and failure captures | Inspect stdout/stderr/logs | No secret/personal payload leaks; sufficient safe context; machine/binary stdout uncontaminated; best-effort stat WARN distinguished from business failure |
| SAFE-09 | P2 I | 100/1000/10000 objects; optional 100000 after budget approval | Measure startup/help/list/search/direct get/stat top/pagination | Cold/warm wall time and peak RSS; cumulative allocation separate; correctness checked at each size; budgets agreed before execution |
| SAFE-10 | P2 I | Vary batch M and store N independently | Measure end-to-end and operation counts | Expose global scans/N+1; direct-ID vs enumeration costs separated; no unapproved indexing redesign |
| SAFE-11 | P2 I | Declared attachment/archive sizes and concurrency | Roundtrip with memory/disk monitoring | Exact hashes, resource budget respected; create archive memory proportional to size acknowledged |
| SAFE-12 | P2 I | Additional supported OS/filesystem | Init/file/lock/move/lifecycle subset | Actual platform evidence; case/alias/lock limits reported, not simulated platform proof |
| SAFE-13 | P0 P | Authorized existing root, backup, baseline, tracking off | Installed skill list/search/show/get/stat/bounded archive | Correct actual binary/root; IDs/counts/states/tags/descriptions and declared payload hashes match; no business mutations |
| SAFE-14 | P0 P | Recovered store and protected backup | Verify baseline against current data | Exact extent stated: originals, active readable files, stats/status; do not claim inaccessible deleted/ceased payload was read |
| SAFE-15 | P0 I | Agent calling registered skill, isolated root | User-style create/attach/find/read/edit/recover workflow | Correct skill and --from usage; routine object operations never direct backend edits; binary proof uses raw files |
| SAFE-16 | P1 I | Successful create in one process | Restart and use root from new cwd | Persistence usable without transient state; explicit absolute root stable |
| SAFE-17 | P0 I/C/F | Owned-resource inventory and preserved evidence | Preview then approved cleanup | Per-deletion logs, exact child cleanup, sentinels intact; no shared GC or recovery-backup deletion |
| SAFE-18 | P0 P | All module results/issues/backups | Human acceptance review | All required gates satisfied or expressly dispositioned; no same-agent independent-review claim; limits and unresolved issues visible |

## Scale and existing-data acceptance notes

Declare expected object counts, payload sizes, concurrency, time/disk/RSS budgets and available resources before generation. Synthetic scale fixtures stay in I; production is not a benchmark target. Prior 100k-object observations (approximately 17 s list, 22 s search and 1.2 GB cumulative allocation) are historical context, not results of this plan, peak RSS, or automatic thresholds. No-index limits require explicit acceptance rather than hidden scope expansion.

Existing-store read-only acceptance is separately authorized and separately reported from isolated tests. Current inventory must be captured at execution time, not hard-coded from an earlier recovery. Read-only assertions disable stat tracking and account for any permitted initialization/lock effects. Do not copy sensitive contents into shared reports. Retain a verified backup until the owner explicitly approves its retirement.

Traceability: cross-module safety plus new installed-skill, recovery integrity, fault-boundary, scale and platform coverage. Failure injections that cannot be triggered deterministically through the live CLI remain BLOCKED with a lower-level-test alternative; they are not claimed live coverage.
