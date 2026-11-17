---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: topsailai_agent_cluster
programming_language: go
status: resolved
---

# Resume from a history row fails because the resume authority reads a narrower source than history

## Trigger

Reported by the human on 2026-11-16, wording normalized, meaning preserved:

> 我是这样操作的，history 看历史，然后 resume history列表中的某个序号，或者
> resume -s 具体的 session-id。我给定的都是我自己确定能 resume 的。但是 resume
> 失败了。例如，我要 resume 那个 检查会话部署状态 的历史会话，就不行。

The human excluded the analysis-session path, quoted verbatim:

> 你不要理会 sad-xxx

## Symptom

`history ac.ai-dev` lists 30 rows. Row 26 (`wa-ebe04457f195`, "检查节点服务运行状态")
and row 28 (`wa-470fab9b316a`, "检查部署会话运行状态") both report `LIVE=no` and
`RESUMABLE=yes`, and both carry a `resume_resource_id`. Resuming either fails with:

```
failed
error_code: invalid_request
message: invalid request: provider session row was not found
effect_certainty: not_applied
delivery_boundary: not_started
```

`delivery_boundary: not_started` proves the failure happened before any provider
process was launched. The refusal is the provider's own authority check, not the
provider's resume command.

## Root cause: two different provider data sources

`history` and the resume authority read different provider commands, and the two
sets do not intersect for a completed session.

| Purpose | Provider command | Rows | Contains the target |
|---|---|---|---|
| `history` | `project list_sessions --json` | 30 | yes |
| resume authority | `workspace list --json --local` | 1 | no |
| resume authority without `--local` | `workspace list --json` | 3 | no |
| resume authority with `--all` | `workspace --all list --json --local` | 8 | yes |
| targeted read with `--all` | `workspace --all list --json --local -s <id>` | 1 | yes |

Measured on `ac.ai-dev` on 2026-11-16. The three target sessions are
`wa-ebe04457f195`, `wa-470fab9b316a` and `wa-44dba8361809`.

`workspace list` discovers rows by scanning `workspace/task/` for `.stdout` and
`.stderr` files (`cli/cli_topsailai/log_files.py:248-250`), and
`discover_workspace_log_files` drops every row whose session metadata reports
`status == "completed"` unless `include_completed` is set
(`cli/cli_topsailai/log_files.py:480-482`). `project list_sessions` reads the
persisted session database, which retains completed sessions.

A completed session is therefore visible in `history` and invisible to the resume
authority.

## Three distinct defects

### Defect 1: the resume authority omits `--all`

`workspaceAuthority` runs `workspace list --json --local`
(`providers/topsailai/mutation_authority.go:48`). Without `--all`, every completed
row is dropped, so `resolved == nil` and the function returns
`provider session row was not found` (`mutation_authority.go:90`).

This is the direct cause for `wa-470fab9b316a` and `wa-ebe04457f195`. Both have a
`.session.stdout` file and both appear in `workspace --all list --json --local`
with `process_generation = null`, which is exactly the shape
`requireResumableRecord` accepts.

### Defect 2: a session with no `.stdout` file is invisible to `workspace list` entirely

`wa-44dba8361809` has only `.session.events`, `.session.meta`,
`.session.stats.jsonl` and `.agent-launch.log`. It has no `.session.stdout`,
because it was interrupted before producing output. `discover_log_files` scans
only `.stdout` and `.stderr`, so this session is absent from `workspace list` even
with `--all`.

Measured: `workspace --all list --json` returns 14 rows and does not contain
`wa-44dba8361809`, while `project list_sessions --json` returns 30 rows and does
contain it.

Adding `--all` therefore fixes Defect 1 but cannot fix Defect 2. Only a source
that reads the persisted session database can resolve such a session.

### Defect 3: `--all` is silently ignored when placed after the subcommand

`--all` is registered on the parent `workspace` parser
(`cli/cli_topsailai/core.py:1810-1816`), not on the `list` subparser
(`core.py:1818-1836`). The top-level parser uses `parse_known_args`
(`core.py:1966`), so an unrecognized flag is discarded without an error.

Measured on 2026-11-16:

| Invocation | Exit | stderr bytes | Rows |
|---|---|---|---|
| `workspace list --all --json --local` | 0 | 0 | 1 |
| `workspace --all list --json --local` | 0 | 0 | 8 |

The wrong form fails silently. Anyone attempting to fix Defect 1 by appending
`--all` to the existing argv would produce a change that appears correct, passes a
review that reads the argv, and changes nothing at runtime.

## Why the cluster side is not at fault

The cluster mints a `resume_resource_id` for every history row through
`GetOrCreateResourceID` (`internal/adapter/genericcli/adapter.go:377-381`), and the
row reports `resumable=true, live=false`.

The Endpoint's resume gate reads `Inspect` and rejects only a live target
(`internal/endpoint/executor.go:153-160`). `Inspect` deliberately omits `--local`
(`providers/topsailai/read.go:118-125`) so a foreign-host session is not reported
as missing. A completed session is also absent from that read, so `Inspect`
returns `Found=false, Live=false`, which the resume gate accepts. The gate is
permissive here, and the refusal happens later, inside the provider's own
authority check.

## Why the provider's resume command itself is capable

`workspace resume -s <id>` resolves the session through
`lookup_persisted_session` (`cli/cli_topsailai/project_scope.py:1895`), which runs
`topsailai_list_sessions --json -- <id>` (`project_scope.py:1286`). That is the
same source `history` uses, and it returns the record for all three targets.

Liveness is then checked by `session_liveness` (`project_scope.py:1905`). All three
target PIDs are dead (`2872250`, `3969084`, `3660498`), so the answer is `idle` and
the resume would proceed.

The provider command can therefore resume these sessions today. The only blocker
is the cluster provider's own pre-check reading a narrower source.

## Code sites

| Site | Behaviour |
|---|---|
| `providers/topsailai/query.go:191-200` | `history` reads `project list_sessions --json` |
| `providers/topsailai/mutation_authority.go:48` | resume authority reads `workspace list --json --local` |
| `providers/topsailai/mutation_authority.go:90` | missing row becomes `provider session row was not found` |
| `providers/topsailai/mutation_authority.go:130-142` | `requireResumableRecord` rejects a live row |
| `providers/topsailai/mutation_argv.go:87` | argv is `workspace resume -s <id> --background --json` |
| `providers/topsailai/read.go:78` | `discover` reads `workspace list --json --local` |
| `providers/topsailai/read.go:125` | `inspect` reads `workspace list --json` |
| `providers/topsailai/read.go:307` | `resolveWorkspaceTarget` reads `workspace list --json --local` |
| `cli/cli_topsailai/log_files.py:248-250` | only `.stdout` and `.stderr` are discovered |
| `cli/cli_topsailai/log_files.py:480-482` | completed rows are dropped unless `include_completed` |
| `cli/cli_topsailai/core.py:1810-1816` | `--all` is registered on the parent parser |
| `cli/cli_topsailai/core.py:1966` | `parse_known_args` discards an unknown flag silently |
| `cli/cli_topsailai/project_scope.py:1286` | resume lookup runs `topsailai_list_sessions` |
| `cli/cli_topsailai/project_scope.py:1895-1917` | resume lookup, workspace validation and liveness |
| `internal/endpoint/executor.go:153-160` | resume gate rejects only a live target |

## The cluster duplicates a check the provider already performs correctly

This is the decisive finding, and it changes the fix.

The provider's own resume path already validates existence and liveness, and it does so
correctly for every session class:

| Step | Provider function | Source | Behaviour for a session with no `.stdout` |
|---|---|---|---|
| Existence | `lookup_persisted_session` (`project_scope.py:1895`) | `topsailai_list_sessions --json -- <id>` | Found, because it reads the persisted database |
| Workspace | `_validate_resume_workspace` (`project_scope.py:1896`) | the record's `project_workspace` | Validated against the real directory |
| Liveness | `session_liveness` (`process_liveness.py:205`) | `.stdout` candidates, then PID state | Returns `idle` when there are no candidates |
| Late recheck | `late_check` (`project_scope.py:1933`) | same two sources | Repeats both checks immediately before launch |

`session_liveness` returns `idle` when `_session_stdout_candidates` yields nothing
(`process_liveness.py:220-221`). A session that never wrote output therefore reads as
resumable, which is the correct answer: no process holds it.

The cluster's `requireResumableRecord` (`mutation_authority.go:133`) is a second,
independent implementation of the same decision, and it reads a narrower source. It runs
in `mutationArgs` (`mutation.go:161`) before any argv exists, so the provider CLI is never
started and its correct validation never runs. The cluster refuses the target on behalf of
a provider that would have accepted it.

Measured on 2026-11-16 for the two sessions the operator named:

| Session | `.stdout` file | `workspace list --json --local` | `workspace --all list` (correct placement) | `list_sessions -- <id>` | PID state |
|---|---|---|---|---|---|
| `wa-470fab9b316a` | present | absent | present, `gen=None` | found | `2872250` dead |
| `wa-ebe04457f195` | present | absent | present, `gen=None` | found | `3969084` dead |
| `wa-44dba8361809` | **absent** | absent | **absent** | found | `3660498` dead |

`gen=None` means the row is not live, so `requireResumableRecord` would accept it. The
only reason it never sees the row is the missing `--all`.

### The reachability gap is much larger than the two reported sessions

Measured on `topsail` on 2026-11-16 by intersecting the two sources directly:

| Set | Count |
|---|---|
| `history` rows | 30 |
| `history` rows marked resumable (`status=Idle`) | 29 |
| Rows the current authority can see (`workspace list --json --local`) | 1 |
| Rows the authority can see with `--all` in the correct position | 8 |
| Resumable rows reachable today | **0** |
| Resumable rows reachable with `--all` | **7** |
| Resumable rows unreachable even with `--all` | **22** |

The current authority reaches **none** of the 29 resumable rows. That is why the operator
described resume as "completely unusable" rather than "sometimes fails": the intersection is
empty, so no history row can be resumed at all.

Direction B raises reachability from 0 to 7 of 29, which is 24 percent. The remaining 22
rows are unreachable for the Defect 2 reason: they have no `.stdout` file, so
`workspace list` cannot discover them at any flag setting. A fix that only adds `--all`
therefore leaves the majority of the reported symptom in place, and the operator would
reasonably report the same failure again.

### The same primitive answers two different questions

The deepest form of the defect is a category error, not a missing flag.

`history` derives its `status` from the same `.stdout` candidate scan the authority uses:
`_enrich_running_status` (`cli/cli_topsailai/project_scope.py:212-240`) calls
`_check_session_running`, which returns `False` when `_index_candidates` yields nothing
(`project_scope.py:171-173`), and the entry is then labelled `Idle`
(`project_scope.py:238`). `historyResumability` maps `Idle` to resumable
(`providers/topsailai/query.go:312-320`).

So for a session with no `.stdout` file, both surfaces run the same scan and get the same
empty result, and then interpret it in opposite directions:

| Surface | Question asked | Empty scan means |
|---|---|---|
| `history` | "is this session running?" | No, so it is `Idle` and resumable |
| `workspace list` | "does this session exist?" | No, so the row is not emitted at all |

Both readings are correct for the question each one asks. The defect is that the resume
authority asks an existence question of a surface built to answer a liveness question. A
discovery surface requires a file to exist before it can report a row, so it can never
answer "the record exists but no process holds it", which is exactly the resume case.

This is why adding `--all` cannot be the whole fix: `--all` only stops the completed-status
filter, and the file-existence requirement is upstream of that filter.



## Candidate fixes

| Direction | Change | Trade-off |
|---|---|---|
| A | Resume authority reads `project list_sessions`, the same source as `history` | Fixes Defect 1 and Defect 2 together, but that source carries no `pid`, no `process_generation` and no `status`, so liveness would need a second read and the authority becomes two sources again |
| B | Resume authority passes `--all` to `workspace list` | Smallest change; fixes Defect 1 for `wa-470fab9b316a` and `wa-ebe04457f195`; Defect 2 remains, so `wa-44dba8361809` still cannot be resumed |
| C | `history` lists only rows `workspace list` can see | Removes the false promise; hides completed sessions from the operator, which is the reason `history` exists |
| D | Delete the cluster's resume pre-check and let the provider's own validation decide | One authority instead of two; the provider already validates existence, workspace and liveness in the execution path, which is what the architecture requires; the cluster loses its fail-fast error code and must map the provider's exit codes instead |

Direction D is now preferred, and it supersedes the earlier preference for A.

The reason is that A and B both keep two implementations of one decision. A makes the
cluster read the same source as `history` but still cannot judge liveness from it. B makes
the cluster read a wider source but still cannot see a session with no `.stdout` file.
D removes the duplication: `resume_session_result` already performs the existence check,
the workspace check, the liveness check and a late recheck at the launch boundary, so the
cluster's copy adds no safety and subtracts reachability.

Direction D has one real cost that must be accepted explicitly: the cluster currently
returns `invalid_request` with a precise message before spawning the provider. After D, a
refusal arrives as the provider's own exit code and message. `resume_session_result`
already returns definite codes for this (`3` for missing or ambiguous identity, `4` for an
untrusted lookup, workspace or liveness), so the mapping is available rather than invented.

If D is rejected, B is the smallest correct partial fix, and it must be written as
`workspace --all list --json --local`. The flag is registered on the parent `workspace`
parser (`core.py:1810-1814`), and the top-level parser uses `parse_known_args`
(`core.py:1966`), so both wrong placements exit zero with no diagnostic:

| Invocation | Exit | stderr bytes | Rows |
|---|---|---|---|
| `workspace list --json --local` | 0 | 0 | 1 |
| `workspace --all list --json --local` | 0 | 0 | 8 |
| `workspace list --all --json --local` | 0 | 0 | 1 |
| `--all workspace list --json --local` | 0 | 0 | 1 |

A test that asserts the exact argv slice is the only thing that catches the wrong
placement, because the wrong placement is indistinguishable by exit status or stderr.

## Direction D does not violate the documented contract

`docs/agent-cluster-protocol.md:671-678` requires that `agent.resume` recheck "that the exact
record exists and is not live, rejecting a record that has become live", and that the check run
"before the provider invokes the business mutation, so rejection proves that the mutation was not
applied".

That requirement is on the provider CLI, and the provider CLI already satisfies it:
`resume_session_result` performs the lookup, the workspace validation, the liveness check and the
`late_check` recheck immediately before the child is spawned
(`cli/cli_topsailai/project_scope.py:1895-1958`). Direction D therefore removes a redundant
cluster-side copy without weakening the documented guarantee.

What D does change is where the refusal is reported. The cluster currently returns
`invalid_request` with a precise message before spawning the provider; after D the refusal arrives
as the provider's exit code and message. The protocol already allows this, because it states that
"every failed live or non-live authority check is reported before the provider invokes the business
mutation" rather than naming which component reports it.

## Verification still required

- Confirm that `workspace resume -s wa-470fab9b316a --background --json` succeeds when run
  directly, bypassing the cluster pre-check. This is a mutating operation and needs
  explicit authorization before it is executed. It is the single test that proves the
  provider's own validation accepts the target the cluster refuses.
- Confirm the same for `wa-44dba8361809`, which has no `.stdout` file. Success there proves
  Defect 2 is real and that only Direction D reaches it.
- After the chosen fix, confirm the cluster path returns a definite result rather than
  `provider session row was not found`.

## Files

- `providers/topsailai/mutation_authority.go`
- `providers/topsailai/query.go`
- `providers/topsailai/read.go`
- `providers/topsailai/mutation_argv.go`
- `internal/endpoint/executor.go`
- `internal/tui/interactive_history.go`
- sibling project `cli/cli_topsailai/log_files.py`
- sibling project `cli/cli_topsailai/core.py`
- sibling project `cli/cli_topsailai/project_scope.py`

## Resolution

Direction D was implemented in `2ac0a45f`. `requireResumableRecord`
(`providers/topsailai/mutation_authority.go:204`) now branches on the key scope: a
session-scoped key resolves through `sessionAuthority`, which reads
`project list_sessions --json` (`mutation_authority.go:163`), the same source `history`
uses. A row-scoped key keeps the workspace read and its live rejection, because the
registry cannot describe one workspace row.

This removes the duplicated authority rather than widening it. The provider's own
`resume_session_result` still performs the existence check, the workspace check, the
liveness check and the late recheck at the launch boundary, so the documented guarantee
in `docs/agent-cluster-protocol.md` is unchanged. A session with no `.stdout` file is now
reachable, because the registry retains it while the workspace scan cannot discover it.

Verified by `providers/topsailai/mutation_test.go`, which covers both key scopes.
