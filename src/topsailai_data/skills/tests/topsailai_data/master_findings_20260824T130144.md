---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_data
ProjectFolder: /TopsailAI/src/topsailai_data
ProjectRootFolder: /TopsailAI/src/topsailai_data
ProjectCode: topsailai_data
programming_language: go
---

# topsailai_data Skill — Master Findings (End-to-End Test)

- Date: 2026-08-24
- Tester: AIMember.ds1-tester
- Skill under test: `topsailai_data` (installed at `/root/.topsailai/skill/topsailai_data`)
- Source project: `/TopsailAI/src/topsailai_data`
- Underlying code: HEAD `9513ea8` ("feat: add object stat observability")
- Scratch roots (real data untouched): `/tmp/topsailai_skilltest_h8tCjO`, `/tmp/topsailai_live_p7vHbH`
- Result: **ALL PASS**

## Pre-Test Setup

| Item | Expected | Actual | Status |
|------|----------|--------|--------|
| `make build` produces fresh binary | Fresh `bin/topsailai_data` | Built (5256111 bytes, 13:00) | PASS |
| Installed skill binary refresh | Latest committed code | Symlink to project `bin/topsailai_data`; rebuild suffices | PASS |
| Invoke binary with no args | Show usage/help incl. `stat` | Help printed, `stat` command present | PASS |

## Smoke Test

| Category | Exact command | Expected | Actual | Status |
|----------|---------------|----------|--------|--------|
| Smoke | `create smoke --description ... --from smoke.md` | Object created active | Created | PASS |
| Smoke | `list` | Shows smoke | Shown | PASS |
| Smoke | `show smoke` | Metadata + Markdown + folder tree; `.stat.json` hidden | All shown; `.stat.json` absent from tree | PASS |

## create

| Category | Exact command | Expected | Actual | Status |
|----------|---------------|----------|--------|--------|
| classify/tag/desc | `create proj-alpha --classify projects --tag alpha,beta --description ... --from proj.md` | Active under projects/, tags alpha,beta | PASS | PASS |
| stdin | `create inline-note --description ...` (heredoc) | Created from stdin | PASS | PASS |
| frontmatter fallback | `create front-obj --from front.md` (no --description) | Description from YAML frontmatter | PASS | PASS |
| missing description | `create nodesc --from nodesc.md` (no frontmatter desc) | Clear error | Error returned | PASS |
| duplicate active | `create proj-alpha ...` again | `ErrObjectExists` | Error returned | PASS |
| create over ceased | `create tmpobj` → delete ×2 → recreate | Ceased purged, recreated | PASS | PASS |
| create over deleted | `create delobj` → delete → recreate | `ErrObjectExists` | Error returned | PASS |

## show / update

| Category | Exact command | Expected | Actual | Status |
|----------|---------------|----------|--------|--------|
| show metadata | `show proj-alpha` | ID/Name/Path/Desc/Status/Schema/Created/Updated/Tags/DataRef | All present | PASS |
| update desc | `update proj-alpha --description "New desc"` | Desc updated | PASS | PASS |
| clear desc | `update proj-alpha --description ""` | Desc cleared | PASS | PASS |

## list

| Category | Exact command | Expected | Actual | Status |
|----------|---------------|----------|--------|--------|
| default yaml | `list` | YAML array | PASS | PASS |
| json | `list --format json` | JSON array | PASS | PASS |
| sort asc/desc | `list --sort time:asc` / `time:desc` | Ordering respected | Verified | PASS |
| pagination | `list --offset 0 --limit 2` | Limited results | PASS | PASS |
| include-deleted | `list --include-deleted` | Includes deleted/ceased | PASS | PASS |

## search

| Category | Exact command | Expected | Actual | Status |
|----------|---------------|----------|--------|--------|
| by name | `search smoke` | Matches smoke | PASS | PASS |
| by tag | `search work` | Matches classified objects | PASS | PASS |
| by classify path | `search projects` | Matches proj-alpha | PASS | PASS |
| OR | `search smoke\|inline` | Either matches | PASS | PASS |
| json | `search smoke --format json` | JSON array | PASS | PASS |
| space query | `search "has space"` | Clear error | Error returned | PASS |

## tag

| Category | Exact command | Expected | Actual | Status |
|----------|---------------|----------|--------|--------|
| add | `tag add smoke urgent` | Tag added | PASS | PASS |
| add | `tag add smoke demo` | Tag added | PASS | PASS |
| remove | `tag remove smoke demo` | Tag removed | PASS | PASS |

## move

| Category | Exact command | Expected | Actual | Status |
|----------|---------------|----------|--------|--------|
| move | `move proj-alpha archive/2026` | Path updated, ID/Name unchanged | Verified | PASS |

## get / get-archive

| Category | Exact command | Expected | Actual | Status |
|----------|---------------|----------|--------|--------|
| get text | `get smoke smoke.md` | File content | PASS | PASS |
| get binary | `put smoke blob.bin --from rand.bin`; `get smoke blob.bin > out.bin` | Byte-for-byte round trip | `cmp` OK | PASS |
| get-archive | `get-archive smoke > a.tar`; `tar tf` | Contains smoke.md, blob.bin | PASS | PASS |

## put / put-archive

| Category | Exact command | Expected | Actual | Status |
|----------|---------------|----------|--------|--------|
| put --from | `put smoke note.txt --from note.txt` | File written | PASS | PASS |
| put stdin | `put smoke s.txt --from -` | Written from stdin | PASS | PASS |
| put-archive | `put-archive smoke a.tar` | Actual data replaced; smoke.md preserved | PASS | PASS |

## delete / recover

| Category | Exact command | Expected | Actual | Status |
|----------|---------------|----------|--------|--------|
| soft delete | `delete smoke` | Status deleted, actual data preserved, stats frozen | PASS | PASS |
| show deleted | `show smoke` | Metadata only, actual-data section suppressed | PASS | PASS |
| recover | `recover smoke` | Back to active, stats resume | PASS | PASS |
| recover --from (tar) | `recover rec --from rec.tar` | Restored active with resupplied data | PASS | PASS |

## gc

| Category | Exact command | Expected | Actual | Status |
|----------|---------------|----------|--------|--------|
| dry-run | `gc --dry-run` | Lists planned removals, no change | PASS | PASS |
| creating | `gc --status creating` | Removes creating objects | PASS | PASS |
| deleted | `gc --status deleted` | Finalizes deleted→ceased; emits `removed object stat file` log | PASS | PASS |
| ceased | `gc --status ceased` | Forces removal ignoring retention | PASS | PASS |

## stat family (NEW)

| Category | Exact command | Expected | Actual | Status |
|----------|---------------|----------|--------|--------|
| stat yaml | `stat smoke` | read/write counts + timestamps | PASS | PASS |
| stat json | `stat smoke --format json` | JSON | PASS | PASS |
| stat top default | `stat top` | Ranked by read desc, active only | PASS | PASS |
| stat top by write | `stat top --by write` | Ranked by write | PASS | PASS |
| stat top order asc | `stat top --order asc` | Unused (count 0) first | PASS | PASS |
| stat top status | `stat top --status deleted` / `all` | Filters by status | PASS | PASS |
| stat top format | `stat top --format json` | JSON | PASS | PASS |
| list --with-stat | `list --with-stat` | Attaches read_count/write_count/timestamps | PASS | PASS |
| search --with-stat | `search smoke --with-stat` | Attaches stat fields | PASS | PASS |
| TRACK_STAT=0 | `TOPSAILAI_DATA_TRACK_STAT=0 get smoke smoke.md` | Counting disabled (read_count unchanged) | PASS | PASS |
| stat readable when disabled | `TOPSAILAI_DATA_TRACK_STAT=0 stat smoke` | Still readable | PASS | PASS |

## Edge Cases

| Category | Exact command | Expected | Actual | Status |
|----------|---------------|----------|--------|--------|
| missing .stat.json | `stat legacy` (fresh object) | Zeros, no timestamps | PASS | PASS |
| corrupt .stat.json | Corrupt file then `stat legacy` | WARN `ignoring corrupt object stat` + zeros, no crash | PASS | PASS |
| invalid stat top arg | `stat top --by bogus` | Clear error | PASS | PASS |
| invalid flush value | `TOPSAILAI_DATA_STAT_FLUSH=bogus` | Config load error | PASS | PASS |

## Classify Tag Inheritance

| Category | Exact command | Expected | Actual | Status |
|----------|---------------|----------|--------|--------|
| classify tag file | `team/team.tags` inside classify dir | Child inherits `team-tag, inherited-tag` | PASS | PASS |

Note: tag file must be placed **inside** the classify directory (`{classify}/{classify}.tags`). Placing it at the parent level yields no inheritance (test-methodology correction, not a product bug).

## Live Smoke (Phase 4)

| Category | Exact command | Expected | Actual | Status |
|----------|---------------|----------|--------|--------|
| lifecycle L1 | create→get→stat→top→list --with-stat→delete→recover→delete×2→gc --status ceased | Runs without crash | PASS | PASS |
| orphan scan L2 | Find `.stat.json` in live root | Count 0 | 0 | PASS |
| orphan scan (scratch) | Find `.stat.json` in scratch root | Only for active objects | 7, all active | PASS |

## Blocker Investigation: recover --from with plain file

- Initial finding: `recover rec --from /tmp/rec_new.md` (plain Markdown) → `error: recover: restore write actual data: read tar header: unexpected EOF`; object stayed `deleted`.
- Resolution: Per SKILL.md, `recover <id> [--from <archive|->]` expects a **tar archive** (or stdin), not a plain file. Supplying a plain file is a contract mismatch.
- Positive validation with proper tar (`recover rec --from /tmp/rec.tar`) succeeded: object restored to `active`, actual data (`rec.md`, `extra.txt`) restored, read_count resumed accumulating.
- Verdict: **Not a product bug.** CLI gracefully rejects invalid input and leaves the object in a safe `deleted` state. (Minor UX note: the tar-header error message is terse, but functionally correct.)

## Overall Verdict

**ALL PASS** — the `topsailai_data` skill is verified functional end-to-end across every documented command, the new `stat` observability feature, edge cases, classify tag inheritance, and the full lifecycle live smoke. No source code was modified during testing.
