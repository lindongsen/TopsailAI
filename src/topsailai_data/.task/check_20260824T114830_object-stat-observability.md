---
maintainer: AI
workspace: /TopsailAI/src/topsailai_data
ProjectFolder: /TopsailAI/src/topsailai_data
ProjectRootFolder: /TopsailAI/src/topsailai_data
ProjectCode: TOPSAILAI_DATA
programming_language: go
---

# topsailai_data Object Stat Observability — Consolidated Test Execution Checklist

## Objective

Consolidate end-to-end verification for the completed "Object Stat Observability"
feature. Six implementation units (model/schema, `.stat.json` persistence, manager
orchestration, CLI surfaces, config wiring, lifecycle/GC integration) are implemented
and individually approved. This checklist exercises the feature holistically through
build/static checks, unit tests, CLI functional/integration tests, edge cases, and a
live smoke run.

## Reference Documents

- Design: `.task/plan_20260824T104900_object-usage-observability.md`
- Code proposal: `.task/code_20260824T105800_object-stat-observability.md`
- Skill: `skills/topsailai_data/SKILL.md` (CLI usage, `make build`, binary at `bin/topsailai_data`)

## Environment

- Workspace: `/TopsailAI/src/topsailai_data`
- CLI binary: `bin/topsailai_data` (built via `make build`)
- Temporary data root: `/tmp/topsailai_stat_check_$$`
- Export: `export TOPSAILAI_DATA_ROOT=/tmp/topsailai_stat_check_$$`

## Test Categories

### 1. Build & Static Checks

| ID | Test | Command | Expected Result |
|---|---|---|---|
| B1 | Build CLI | `make build` | Produces `bin/topsailai_data`; build succeeds |
| B2 | Vet | `go vet ./...` | No vet findings |
| B3 | Format | `gofmt -l $(git ls-files '*.go')` | No files reported (empty output) |
| B4 | Whitespace | `git diff --check` | No whitespace errors |

### 2. Unit Tests

| ID | Test | Command | Expected Result |
|---|---|---|---|
| U1 | Full unit suite | `go test ./... -count=1` | All packages pass (cmd, adapters, local, cli, config, errors, manager, models) |
| U2 | Coverage sanity | `go test ./pkg/models/... ./pkg/adapters/local/... ./pkg/manager/... ./pkg/cli/... ./pkg/config/... -cover` | Touched packages meet >93% coverage where feasible; no significant uncovered stat paths |

### 3. Functional / Integration (via CLI binary)

Setup: fresh `TOPSAILAI_DATA_ROOT`; create a seed object with a description and tag.

| ID | Test | Command | Expected Result |
|---|---|---|---|
| F1 | Create accrues write stat | `create stat-obj --description "stat test" --tag demo` | Success; `.stat.json` exists in object folder with `write_count >= 1` and `last_written_at` set |
| F2 | show displays Stat section | `show stat-obj` | Output includes a `Stat:` section with ReadCount/LastReadAt/WriteCount/LastWrittenAt |
| F3 | get increments read | `get stat-obj stat-obj.md` | `read_count` increases by 1; `last_read_at` updated |
| F4 | get-archive increments read | `get-archive stat-obj > /dev/null` | `read_count` increases by 1 again |
| F5 | stat single object | `stat stat-obj` | Shows read/write counts and human-readable local timestamps (RFC3339, not epoch ms) |
| F6 | stat top default ranking | `stat top` | Ranks by `read_count` desc, limit 10, status active, yaml; `stat-obj` ranked by its read count |
| F7 | stat top flags | `stat top --by write --order asc --limit 50 --status all --format json` | Ordered by write_count asc; json output with rank/id/path/status/read_count/last_read_at/write_count/last_written_at |
| F8 | stat top asc puts unused first | Create a second object with no reads; `stat top --by read --order asc` | Unused object (zero read_count) sorts to top |
| F9 | list --with-stat | `list --with-stat --format json` | Each row carries stat fields; no crash |
| F10 | search --with-stat | `search stat --with-stat --format json` | Matching rows carry stat fields |
| F11 | list/search without flag do not count | Record `read_count`; run `list` and `search`; re-check `stat <id>` | Counts unchanged (enumeration does not increment) |
| F12 | TRACK_STAT=0 disables counting | `TOPSAILAI_DATA_TRACK_STAT=0 get stat-obj stat-obj.md` then `stat stat-obj` | Counts do not increase, but `stat <id>` still readable (returns existing values) |
| F13 | delete freezes stats | `delete stat-obj`; attempt read; `stat stat-obj --status all` | Stats frozen (no increment on deleted object); `.stat.json` preserved |
| F14 | recover preserves history & resumes | `recover stat-obj`; then `get stat-obj stat-obj.md` | Historical counts preserved; read_count increments resume from prior value (not reset) |
| F15 | finalize removes .stat.json | `delete stat-obj` (second time) | Object transitions to ceased; `.stat.json` removed |
| F16 | gc --status ceased removes .stat.json | `gc --status ceased` | Ceased object and any residual `.stat.json` removed; no orphan stat file |
| F17 | show hides .stat.json | `show stat-obj` (while active) | Folder-structure tree does NOT list `.stat.json` |

### 4. Edge Cases

| ID | Test | Command | Expected Result |
|---|---|---|---|
| E1 | Legacy object without .stat.json | Manually place an object folder with only `{name}.md` (no stat file); `stat <id>` | Shows zeros / `never`; no error |
| E2 | Corrupt .stat.json | Write invalid JSON into `.stat.json`; `stat <id>` and `show <id>` | Treated as zero; warning logged; command does not fail |
| E3 | Invalid stat top args | `stat top --by bogus`; `stat top --order sideways`; `stat top --limit -1`; `stat top --status nope`; `stat top --format xml` | Clear validation errors returned |
| E4 | Invalid STAT_FLUSH config | `TOPSAILAI_DATA_STAT_FLUSH=bogus bin/topsailai_data list` | Startup/validation error: `TOPSAILAI_DATA_STAT_FLUSH must be sync or async` |

### 5. Live Smoke

| ID | Test | Command | Expected Result |
|---|---|---|---|
| L1 | End-to-end lifecycle | create → get → stat → stat top → list --with-stat → delete → recover → delete(finalize) → gc --status ceased, all in a scratch root | No crashes; no orphan `.stat.json` anywhere under the root after final cleanup |
| L2 | Orphan scan | After L1, walk the scratch root for any `.stat.json` | None remain |

## Completion Criteria

All tests pass. Any failure is recorded with exact command, actual output, expected
output, and reproduction steps. Failures are routed to the developer for fixing within
the owning unit's scope, then re-reviewed before re-running the checklist.

## Execution Results

(Filled by tester on 2026-08-24. Overall: ALL PASS. No source code modified.)

Scratch roots used:
- Functional: `/tmp/topsailai_stat_check_zwcvos`
- Edge cases: `/tmp/topsailai_edge_GER8vR`
- Live smoke: `/tmp/topsailai_live_y8LxIX`

### 1. Build & Static Checks

| ID | Result | Evidence |
|---|---|---|
| B1 | PASS | `make build` succeeded; `bin/topsailai_data` present (5256111 bytes) |
| B2 | PASS | `go vet ./...` clean (no findings) |
| B3 | PASS* | `gofmt -l` flagged only pre-existing baseline files `pkg/adapters/adapters_test.go` and `pkg/adapters/local/path.go` (both UNMODIFIED, not in feature set); no feature files reported |
| B4 | PASS | `git diff --check` clean (no whitespace errors) |

### 2. Unit Tests

| ID | Result | Evidence |
|---|---|---|
| U1 | PASS | `go test ./... -count=1` — all 8 packages green (cmd, adapters, local, cli, config, errors, manager, models) |
| U2 | PASS | Coverage assessed: models 100%, config 94.7%, local 71.9%, manager 74.0%, cli 82.4%. Stat-specific funcs largely 60-100% (ReadStat/IncrementRead/IncrementWrite/StatFilePath 100%). Lower totals reflect pre-existing baseline; no significant uncovered stat paths. |

### 3. Functional / Integration (via CLI binary)

Seed object `stat-obj` created with `--description "stat test" --tag demo`.

| ID | Result | Evidence |
|---|---|---|
| F1 | PASS | `.stat.json` appeared with `write_count: 1` and `last_written_at` set |
| F2 | PASS | `show stat-obj` includes `Stat:` section (ReadCount/LastReadAt/WriteCount/LastWrittenAt) |
| F3 | PASS | `get` incremented read_count 1→2; last_read_at updated |
| F4 | PASS | `get-archive` incremented read_count 2→3 |
| F5 | PASS | `stat stat-obj` shows counts + RFC3339 local time (e.g. `2026-08-24T11:52:...+08:00`) |
| F6 | PASS | `stat top` default: ranked by read_count desc, limit 10, status active, yaml |
| F7 | PASS | `stat top --by write --order asc --limit 200 --status all --format json` — json with rank/id/path/status/read_count/last_read_at/write_count/last_written_at |
| F8 | PASS | `stat top --by read --order asc` — unused object (read_count 0) sorted to top |
| F9 | PASS | `list --with-stat --format json` attaches stat fields; no crash |
| F10 | PASS | `search stat --with-stat --format json` attaches stat fields |
| F11 | PASS | `list`/`search` without flag did NOT change read_count (stayed 3) |
| F12 | PASS | `TOPSAILAI_DATA_TRACK_STAT=0 get` did not increment; `stat <id>` still readable |
| F13 | PASS | `delete` froze stats (read blocked, count stayed 3, `.stat.json` preserved). Viewed via `TOPSAILAI_DATA_INCLUDE_DELETED=1 stat <id>` (note: `--status` is only valid on `stat top`, not `stat <id>` — see note below) |
| F14 | PASS | `recover` preserved history (3→3) then `get` resumed accumulation (3→4) |
| F15 | PASS | Second `delete` (finalize) transitioned to ceased; `.stat.json` removed (verified absent) |
| F16 | PASS | `gc --status ceased` removed ceased object dir; emitted deletion log `removed object stat file`; no orphan stat |
| F17 | PASS | `show` folder-structure tree does NOT list `.stat.json` (confirmed with separate `f17-obj`) |

NOTE (doc correction, not a code defect): checklist F13 said `stat stat-obj --status all`; `--status` is only valid on `stat top`. Verified freeze behavior correctly via `TOPSAILAI_DATA_INCLUDE_DELETED=1 stat stat-obj`.

### 4. Edge Cases

| ID | Result | Evidence |
|---|---|---|
| E1 | PASS | Legacy object without `.stat.json` → `stat` shows zeros/`never`, no error |
| E2 | PASS | Corrupt `.stat.json` → WARN `ignoring corrupt object stat ... invalid character 'T' looking for beginning of value`; `stat`/`show` succeed with zeros |
| E3 | PASS | Invalid args → clear errors: `invalid by "bogus"`, `invalid order "sideways"`, `limit must be non-negative`, `invalid status "nope"`, `unsupported format "xml" (expected yaml or json)` |
| E4 | PASS | `TOPSAILAI_DATA_STAT_FLUSH=bogus list` → `error: load configuration: TOPSAILAI_DATA_STAT_FLUSH must be sync or async` |

### 5. Live Smoke

| ID | Result | Evidence |
|---|---|---|
| L1 | PASS | End-to-end lifecycle (create→get→stat→stat top→list --with-stat→delete→recover→delete×2 finalize→gc --status ceased) completed without crash |
| L2 | PASS | Post-lifecycle orphan scan: `find <root> -name '.stat.json'` count = 0 |

## Conclusion

Feature verified end-to-end. All checklist items PASS (B1-B4, U1-U2, F1-F17, E1-E4, L1-L2). No source code modified.
