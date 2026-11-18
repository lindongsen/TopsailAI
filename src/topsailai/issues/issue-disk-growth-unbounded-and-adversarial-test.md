---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
author: DawsonLin
status: open
---

# Issue: Disk growth is unbounded and lacks adversarial coverage

## Symptom

Disk usage kept rising while sessions were running, and the volume that holds the
session database reached 95% and then filled. Measured on 2026-11-14:

| Mount | Size | Used | Avail | Use% |
|---|---|---|---|---|
| `/opt` (`nvme0n1p3`) | 377G | 381.5G | 22.8G | 95% |
| `/` (`nvme0n1p2`) | 92G | 82G | 5.3G | 94% |

The human stated the disk was full on `/opt`, and that is correct. `/opt` is the
filesystem that holds the session data: `/root/.topsailai` resolves through
`/work/hosts/.topsailai` to
`/opt/git/ai/lindongsen/work/hosts/.topsailai`, and the session database
`memory.db` (790 MB) lives there. `/` is a separate filesystem and is not the
cause of the session crashes.

## Confirmed root cause: deleted-but-open log files held by orphaned processes

Two orphaned test processes on host `topsail`, PID `3413563` and PID `3425078`,
kept writing to log files that had already been deleted. Because the file
handles stayed open, the space was never reclaimed.

Measured deleted-but-open accounting, captured while both processes were alive:

```
=== deleted-but-open files (top) ===
    324 (deleted)

=== sum of deleted open file sizes ===
total MB: 314939.9 count: 327
38654.3 MB /proc/3413563/fd/2 /TopsailAI/src/topsailai/.tmp/e2e_agent.log (deleted)
38654.3 MB /proc/3413563/fd/1 /TopsailAI/src/topsailai/.tmp/e2e_agent.log (deleted)
38654.3 MB /proc/3413557/fd/2 /TopsailAI/src/topsailai/.tmp/e2e_agent.log (deleted)
38654.3 MB /proc/3413557/fd/1 /TopsailAI/src/topsailai/.tmp/e2e_agent.log (deleted)
38654.3 MB /proc/3413556/fd/2 /TopsailAI/src/topsailai/.tmp/e2e_agent.log (deleted)
38654.3 MB /proc/3413556/fd/1 /TopsailAI/src/topsailai/.tmp/e2e_agent.log (deleted)
13737.2 MB /proc/3425078/fd/2 /TopsailAI/src/topsailai/.tmp/live_agent.log (deleted)
13737.2 MB /proc/3425078/fd/1 /TopsailAI/src/topsailai/.tmp/live_agent.log (deleted)
13737.2 MB /proc/3425071/fd/2 /TopsailAI/src/topsailai/.tmp/live_agent.log (deleted)
13737.2 MB /proc/3425071/fd/1 /TopsailAI/src/topsailai/.tmp/live_agent.log (deleted)
13737.2 MB /proc/3425070/fd/2 /TopsailAI/src/topsailai/.tmp/live_agent.log (deleted)
```

Aggregated by unique file:

```
deleted files: 180 total GB: 51.75
37.78 GB /TopsailAI/src/topsailai/.tmp/e2e_agent.log (deleted)
13.43 GB /TopsailAI/src/topsailai/.tmp/live_agent.log (deleted)
0.09 GB /opt/git/ai/lindongsen/work/hosts/.topsailai/log/topsailai.log.1 (deleted)
0.09 GB /opt/git/ai/lindongsen/work/hosts/.topsailai/log/... (deleted)
```

So **37.78 GB + 13.43 GB = 51.75 GB** of deleted-but-still-open data was held by
180 unique deleted files across 327 open descriptors. Measured growth was
**~145 MB / 20 s**. After the human killed both PIDs, `/opt` dropped from 95% to
81% and the growth rate returned to zero.

### Process state at the time of measurement

```
=== pid 3413563 ===
cwd -> /TopsailAI/src/topsailai/.tmp/e2e-home (deleted)
state=R
0 -> /dev/null
1 -> /TopsailAI/src/topsailai/.tmp/e2e_agent.log
11 -> /TopsailAI/src/topsailai/.tmp/e2e-home/memory.db
=== pid 3425078 ===
cwd -> /TopsailAI/src/topsailai/.tmp/live-home (deleted)
state=R
0 -> /dev/null
1 -> /TopsailAI/src/topsailai/.tmp/live_agent.log
10 -> /TopsailAI/src/topsailai/.tmp/live-home/memory.db
```

Both were in state `R` (running), with their working directories already deleted
and their stdout still pointed at deleted log files. They were launched as
`sh -c -- topsailai_agent_chats` -> `uv run cli/agent_chats.py` ->
`/TopsailAI/.venv/bin/python3 cli/agent_chats.py`, parented by PID `1296094`
(`/pause`, a container init), so no supervising process ever reaped them.

### The repeated output that filled the logs

This is the "repeated large output of specific content" the human described.
Both processes were stuck in infinite loops with no exit condition, writing the
same lines forever.

`e2e_agent.log` tail, read through `/proc/3413563/fd/1`:

```
 the same LLM request
2. Back to chat
3. Exit
Select [1-3]: LLM retry attempts exhausted.
1. Retry the same LLM request
2. Back to chat
3. Exit
Select [1-3]: LLM retry attempts exhausted.
1. Retry the same LLM request
2. Back to chat
3. Exit
Select [1-3]: LLM retry attempts exhausted.
1. Retry the same LLM request
2. Back to chat
3. Exit
Select [1-3]:
```

`live_agent.log` tail, read through `/proc/3425078/fd/1`:

```
ct] >>> Your input:
[AgentReAct] >>> Your input:
[AgentReAct] >>> Your input:
[AgentReAct] >>> Your input:
[AgentReAct] >>> Your input:
[AgentReAct] >>> Your input:
[AgentReAct] >>> Your input:
[AgentReAct] >>> Your input:
[AgentReAct] >>> Your input:
[AgentReAct] >>> Your input:
[AgentReAct] >>> Your input:
[AgentReAct] >>> Your input:
[AgentReAct] >>> Your inpu
```

Two distinct unbounded loops are visible, and both are confirmed in source.

**Correction (2026-11-14):** the two loops named below are real, but neither was
the actual spinner. Both funnel through `workspace/input_tool.py::input_one_line`,
which swallowed every `EOFError` and `continue`d. With stdin at `/dev/null` the
read raises `EOFError` immediately and forever, so the prompt re-printed without
bound. That function is the producer of the repeated `>>> Your input:` lines, and
it has been fixed in commit `68e5e80a`. The analysis below is retained because it
correctly identifies the surrounding unbounded structures, but fixing only the two
sites it names would have left the spinner intact.

Loop 1, the ReAct input prompt. `ai_base/agent_types/tool.py:346` is an
unbounded `while True`:

```python
while True:
    input_func = get_agent_runtime_input()
    if input_func is None:
        input_func = input
    user_input = input_func(f"\n[{get_agent_name()}] >>> Your input: ")
    if not user_input.strip():
        continue
    return user_input
```

The prompt is printed before the read, and an empty result loops straight back
to print it again. There is no EOF branch and no iteration bound. The pipe reader
`utils/input_tool.py:989` defaults `raise_eof_error=False`, so an EOF marker is
returned as an empty string rather than raising, which feeds the `continue`
branch. With stdin at `/dev/null` the read returns empty forever, so the prompt
re-prints forever.

Loop 2, the LLM retry prompt. `ai_base/llm_base.py:659` calls
`_read_retry_exhaustion_action` at the start of every retry cycle, and
`ai_base/llm_control/llm_retry.py:59-63` builds the prompt text
`LLM retry attempts exhausted.` plus `Select [1-N]: `. The helper itself is
bounded (`max_invalid_choices=3`, and `EOFError` returns `"exit"`), but the
surrounding cycle is driven by `max_total_attempts = attempts_per_cycle *
(policy.max_manual_retry_cycles + 1)` with `attempts_per_cycle = 18`, so the
prompt is re-emitted once per cycle. When the input source cannot supply a
choice, the cycle repeats and the prompt is printed again.

Both loops write to stdout, stdout is redirected to a log file, and the log file
was deleted while the descriptor stayed open. The result is unbounded growth that
`df` reports as used but that no directory listing can show.

## Evidence: strace

No raw strace output file exists. `/TopsailAI/src/topsailai/.tmp/` holds only
`opt_du.txt`, `docker_du.txt`, `data_du.txt`, `du_done` and two runtime context
files; a search for `*strace*` under `.tmp`, `/tmp` and `/root/.topsailai`
returns nothing.

Every `strace` literal in `topsailai.4109219.session.events` (147 occurrences)
and `topsailai.4109219.session.stdout` (185 occurrences) is a self-match from the
analyst's own grep commands, not captured syscall output. A scan for the real
syscall form `write(1, "...", N) = N`, for `[pid N]` markers, and for
`= -1 ENOSPC` across all `.session.events` files found no genuine strace output
for this incident.

The only genuine syscall record in the store belongs to a different, older
incident and must not be conflated with this one:
`data/object/2026/0725/0010/incidents/ai_team-stdout-backpressure-deadlock-2026-07-24/`.
There, PID 1810293 blocked in `write(1, "[AIManager.DawsonLin] ...", 197)`,
stdout pointed at `/dev/pts/58`, the dtach client `/dev/pts/57` had
disconnected, 53504 bytes were queued on the socket, and the pty buffer filled.

For this disk incident the decisive evidence is the deleted-but-open accounting,
the `/proc/<pid>/fd` inspection, the repeated log tails, and the 95% -> 81% drop
after the kill. A syscall trace was never captured and is not required to prove
the mechanism.

## Causal link to abnormal session exit

Disk exhaustion produced `sqlite3.OperationalError: database or disk is full`,
which reached `utils/db_io_tool.py:226` and called `os._exit(code)`. That bypasses
`atexit`, so `workspace/session_meta.py:261` `_finalize_on_exit` never ran and the
meta stayed `running` with `end_ts: null` forever. Three real crashes map to exact
sessions:

| Time | Session | PID | Host |
|---|---|---|---|
| 2026-11-14 05:52:48 | `wa-a1ad42ea0a3f` | 3552162 | ai-dev |
| 2026-11-14 06:14:35 | `wa-ecd67a6e691e` | 1048853 | topsail |
| 2026-11-14 06:14:48 | `wa-a79cafc1f220` | 3680645 | topsail |

These three match the human's recollection of "2-3 on topsail, 2-3 in ai-dev".

## Secondary leaks

### Orphaned Go test binaries under `/tmp`

Four orphaned `TestFeatures*` directories total 16G:

| Directory | Size | Last modified |
|---|---|---|
| `/tmp/TestFeatures117276512` | 5.6G | 2026-11-13 10:32 |
| `/tmp/TestFeatures777279922` | 5.6G | 2026-11-13 10:32 |
| `/tmp/TestFeatures3314287415` | 3.7G | 2026-11-12 11:08 |
| `/tmp/TestFeatures3724724312` | 779M | 2026-11-07 19:57 |

Each holds 217 numbered subdirectories of about 65M of compiled Go binaries
(`endpoint` 24M, `server` 16M, `agent-cluster-cli` 18M, plus certificates and a
40K `server.db`), 2085 files per directory.

Producing code: `tests/bdd/suite_test.go:40 func TestFeatures` is the BDD entry
point, so Go names each temporary directory `TestFeatures<random>`.
`tests/bdd/world.go:63` calls `t.TempDir()` for the scenario root, and
`tests/harness/cluster.go:198` calls `t.TempDir()` again, then builds three
binaries into it at lines 204, 207 and 210 via
`tests/harness/process.go:66 exec.Command("go", "build", ...)`.

`t.TempDir()` is removed only on normal completion. A killed, timed-out or
interrupted run leaves the whole 65M tree behind with no cleanup path.

### Session metadata cleanup deadlock

`workspace/session_meta.py:414 cleanup_session_meta_files` uses
`TOPSAILAI_SESSION_META_RETENTION_DAYS=7` and
`TOPSAILAI_SESSION_META_MAX_COUNT=0`, and `:420` documents `0` as unlimited, so
only the retention window can select a candidate.

491 meta files exist and 55 are older than 7 days, so candidates are selected but
never removed. The reaper log ends with
`session reaper finished: reaped=0 of 51`, preceded by 105
`Preserve session ...: unknown (unverified recorded home)` and 1
`incomplete owner evidence`.

The rejection comes from `context/session_activity.py:42`
`_CLEANABLE_OWNER_STATUSES = frozenset({"completed", "error", "interrupted"})`,
enforced at `:268`. A `running` owner, or one whose home cannot be verified, is
never cleanable, so its meta and events persist indefinitely. Every disk-full
crash therefore permanently adds an unreapable session.

### Events files grow without a count bound

`TOPSAILAI_EVENTS_FILE_MAX_COUNT=0` is read at `events/backends/file.py:99` and
`events/config.py:55` with `default=0`, meaning no count limit. The task directory
holds 487M of `.session.events` files, the largest at 35M, 25M, 23M, 20M and 19M.
Only 10 `.session.stdout` files exist against 491 meta files, so stdout/events
retention is asymmetric.

### Remaining orphan processes

Six orphan test processes are still alive, all with deleted working directories:
`3437597`, `3454037`, `3466942` on topsail and `996363`, `997207`, `997931` in
ai-dev. Terminating them is destructive and requires explicit human approval.

## Retracted attributions

Recorded so they are not repeated:

1. **`/` as the critical partition.** Wrong. The session data is on `/opt`. `/`
   is a separate filesystem.
2. **`/tmp/TestFeatures*` (16G) as the primary cause.** Wrong. It is a real but
   secondary leak; it does not explain the `/opt` growth.
3. **Deleted-but-open data being only 569 MB.** Wrong. The recorded measurement
   is 51.75 GB across 180 unique files, corroborated by the 95% -> 81% drop after
   the kill.
4. **The six leftover test processes as the growth source.** Wrong. They hold
   only KB-sized descriptors at 0.0% CPU. The growth came from PIDs `3413563` and
   `3425078`.
5. **`/var/lib/minidlna` occupying `/`.** Wrong. It is a symlink into a JuiceFS
   mount.

## Impact

Unbounded growth fills `/opt`, and a full `/opt` is exactly what triggers the
`database or disk is full` crashes that kill interactive sessions. The defects are
causally linked: disk exhaustion is the trigger, the unconditional exit is the
amplifier, and the cleanup deadlock prevents recovery. Without a bound, the same
failure recurs after any manual cleanup.

## Required Behavior

Growth MUST be bounded, and every accumulating artifact MUST have a matching
cleanup path that actually runs. Test requirements:

- A bounded-growth assertion: a repeated session lifecycle MUST NOT grow disk
  without limit, and the measured growth MUST stay within a declared bound.
- An adversarial test: drive the disk-full condition and assert the interactive
  session survives it, reaching the input prompt, with meta and stdout retained.
- An adversarial test for the repeated-output loop: simulate a process whose
  stdin is `/dev/null` while the retry prompt and the ReAct input prompt are
  active, and assert the process exits instead of re-printing the prompt
  indefinitely. The assertion MUST measure bytes written, not just that the
  process eventually dies.
- A deleted-but-open assertion: a process writing to a log file that has been
  deleted MUST be detected, and the reclaimed space MUST be measured before and
  after termination.
- A cleanup test: verify orphaned test artifacts and caches are actually removed
  and that cleanup does not affect unrelated data.
- A test-artifact cleanup assertion: a killed or interrupted test run MUST NOT
  leave its temporary build tree behind, verified by measuring the temporary
  directory before and after.
- A reaper assertion: a `running` meta whose PID is verifiably dead MUST become
  cleanable, without weakening the fail-closed rule for live sessions.
- An events-bound assertion: `TOPSAILAI_EVENTS_FILE_MAX_COUNT` MUST enforce a
  finite bound when set.

## Current state re-measured on 2026-11-14 14:01

The conditions that produced the original incident have partly changed, so the
disposition below is based on fresh measurements rather than the original ones.

| Mount | Size | Used | Avail | Use% |
|---|---|---|---|---|
| `/` (`nvme0n1p2`) | 92G | 66G | 21G | 77% |
| `/opt` (`nvme0n1p3`) | 377G | 314G | 63G | 84% |

- The 51.75 GB of deleted-but-open data is gone, and the two producing PIDs
  (`3413563`, `3425078`) are no longer running.
- The four `/tmp/TestFeatures*` directories are gone; `/tmp` now holds 2.4G and no
  `TestFeatures*` entry remains.
- The task directory holds 941M across 492 meta, 15 stdout and 754 events files.
  The largest events files are 35M, 25M, 23M and 20M.
- The oldest events file is 6d23h old, just inside the 7-day retention window, so
  age-based events cleanup is working and orphaned events are reclaimable.
- The oldest meta file is about 9.7 days old, past the same 7-day window, and is
  still present. Meta cleanup is therefore still blocked, not merely slow.
- 29 meta files claim `running`. Checking each recorded PID shows 6 alive and 23
  dead, so 23 ghost sessions remain permanently unreclaimable because `running`
  is excluded from the cleanable statuses.
- 508 events files have no matching meta file. They are reclaimed by age, not by
  the meta cleanup path, so the two cleanup mechanisms are independent.

Disposition: the issue stays open. The acute disk exhaustion is resolved, and the
prompt-loop producer is now fixed, but the remaining structural defects are
unchanged: the reaper still cannot reclaim a dead `running` owner, and the events
count bound is still unlimited. The ghost-session count is now measured at 23
rather than the 21 recorded earlier.

Note on scope: the committed change `87791479` prevents new ghost sessions by
removing the unconditional exit, and it reclaims stdout and events together with
an authorized meta removal. It does not reclaim the 23 existing ghosts, because
that requires the reaper fix described in action 3, which is not implemented.

## Resolution

Partially resolved.

Action 1 is complete in commit `68e5e80a`. The actual spinner was
`workspace/input_tool.py::input_one_line`, which swallowed every `EOFError` and
reprompted. It now propagates the condition when pipe input is disabled, because
a closed stdin can never answer. `input_multi_line` was converted from unbounded
tail recursion to a bounded loop that distinguishes a closed channel from a user
who deliberately ended an empty message. The three agent-loop prompts and the
`agent_chats` / `llm_chats` entry points now end the conversation on `EOFError`
instead of printing a traceback or reprompting.

Measured: with stdin at `/dev/null`, the bounded implementation writes 117 bytes
and exits 0, while a deliberate reproduction of the old behaviour wrote 1,301,180
bytes in 5 seconds before being killed. Both `cli/agent_chats.py` and
`cli/llm_chats.py` previously spun until a 45-second timeout at pristine HEAD and
now exit 0.

Remaining actions, in order of value:

2. Make the BDD harness build into a bounded, reusable location instead of a
   per-scenario `t.TempDir()`, or register a cleanup that survives interruption.
3. Break the reaper deadlock so a `running` owner with no live process becomes
   cleanable, which also removes the 23 ghost sessions.
4. Set a finite `TOPSAILAI_EVENTS_FILE_MAX_COUNT` and align stdout/events
   retention with meta retention.
5. Obtain human approval to terminate the six remaining orphan processes by exact
   PID and to purge the 23 stale `running` metas.
6. Reclaim the Docker space on `/opt` (24G images, 10G volumes, 3.5G build cache)
   as a separate, non-urgent action.

## Verification

Action 1 verified. With stdin at `/dev/null` and pipe input disabled, the bounded
implementation writes 117 bytes and exits 0; a deliberate reproduction of the old
swallow-and-reprompt behaviour wrote 1,301,180 bytes in 5 seconds before being
killed. `cli/agent_chats.py` and `cli/llm_chats.py` spun until a 45-second timeout
at pristine HEAD and now exit 0 with no traceback. The regression tests fail at
pristine HEAD and pass with the fix.

Still pending for the remaining actions: growth measured across a scripted session
lifecycle stays within the declared bound; the adversarial disk-full test reaches
the input prompt instead of exiting; a killed test run leaves no temporary build
tree; the reaper reclaims a dead `running` meta while preserving a live one; the
events count bound is enforced.

## Action 1 re-verified on 2026-11-17

`68e5e80a fix: bound the interactive prompt loops on a closed input channel` (2026-11-14) is an
ancestor of HEAD `5da6bb49f651a501b041486590a0c87e5acd85c6`, so the completed part of this issue is committed and live.

Actions 2 through 6 remain open. Action 5 requires human approval to terminate specific orphan
processes by exact PID and to purge the stale `running` metas, so this issue cannot be closed
autonomously. Action 3 overlaps
[issue-reaper-cannot-clean-sigkilled-owner-record.md](./issue-reaper-cannot-clean-sigkilled-owner-record.md),
which is blocked on the same cleanup-authorization decision.

## Actions 3, 4 and 5 re-measured on 2026-11-18

Every number below came from a command executed in this workspace, not from the
earlier text of this issue.

### Action 3 is implemented

`git merge-base --is-ancestor 1956f24a HEAD` returns success, and
`1956f24a fix: reclaim unfinalized owner residue after its artifacts expire`
changed `context/session_activity.py` (53 insertions) plus its unit test
(131 insertions). `_unfinalized_residue` is defined at
`context/session_activity.py:305` and consumed at `:395`, inside the branch that
previously returned `UNKNOWN` for any status outside
`_CLEANABLE_OWNER_STATUSES` (`completed`, `error`, `interrupted`).

`tests/unit/test_topsailai_context_session_activity.py` reports **78 passed**.

So the reaper deadlock described in action 3 no longer exists. The issue text
above still lists it as open and should be read as superseded by this section.

### Action 3 does not reclaim the current ghost sessions, and the reason is age

A probe over the live task directory reported:

```
running metas: 10   alive=4   dead=6
retention=7d (production): cleanable=0  blocked=10
retention=1d (simulated):  cleanable=2  blocked=8
```

The two sessions that become cleanable at a one-day window are
`wa-1fb57b5948b4` and `wa-a1ad42ea0a3f`, both flipping to `stopped`. The
remaining dead owners stay blocked because at least one of their artifacts is
still younger than the retention window, which is exactly the guard the residue
path is supposed to apply. Artifact ages for the blocked dead owners are 0.79d
to 5.02d, so a seven-day window correctly refuses them.

This means the ghost-session count is a **retention-window** consequence, not a
reaper defect. Shortening `TOPSAILAI_SESSION_META_RETENTION_DAYS` would reclaim
them sooner, but that is a policy decision rather than a code fix.

### Action 4: the enforcement exists, only the default is unlimited

`events/backends/file.py:212` deletes the oldest files once
`self._max_count > 0` is exceeded, and `events/config.py:55` reads
`TOPSAILAI_EVENTS_FILE_MAX_COUNT` with `default=0`. The documented meaning of
`0` is "unlimited".

`tests/unit/events/test_backends.py` reports **12 passed**, including the
count-bound and retention-days cleanup cases.

So the mechanism required by action 4 already works. What remains is choosing a
finite default, which would begin deleting event files on every deployment and
therefore needs an explicit decision.

Retention is already aligned: `TOPSAILAI_SESSION_META_RETENTION_DAYS` and
`TOPSAILAI_EVENTS_FILE_RETENTION_DAYS` both default to `7`.

### Action 5: the six orphan processes are gone

```
3437597 gone   3454037 gone   3466942 gone
996363  gone   997207  gone   997931  gone
```

No termination is needed, so the destructive half of action 5 is moot. The
remaining half, purging stale `running` metas, is now governed by the action 3
residue path and the retention window described above.

### Action 2 is outside this workspace

`/TopsailAI/src/topsailai_agent_cluster` exists as a sibling project, and this
workspace contains no `.go` files. The harness that builds into a per-scenario
`t.TempDir()` therefore belongs to that project and cannot be changed here.

### Current disk state

```
~/.topsailai/workspace/task   927M
.session.meta        453
.session.events     1409
.session.stdout       80
.session.stats.jsonl 728
```

Compared with the 2026-11-14 measurement recorded above (941M, 492 meta, 754
events, 15 stdout), the events count has nearly doubled while stdout stayed low.
The asymmetry this issue describes is therefore still present.

### What is genuinely still open

1. Adversarial assertions that do not exist yet: bytes written by a prompt loop,
   detection of a deleted-but-open descriptor, and bounded growth across a
   scripted session lifecycle.
2. Whether to set a finite `TOPSAILAI_EVENTS_FILE_MAX_COUNT` default.
3. Whether to shorten the meta retention window so dead owners are reclaimed
   sooner.
4. Action 2, routed to the sibling Go project.
5. Action 6, an operational Docker cleanup on `/opt`.

## Adversarial tests written on 2026-11-18

The Human authorized the three missing adversarial assertions and explicitly
rejected the other two open items: `TOPSAILAI_EVENTS_FILE_MAX_COUNT` keeps its
`0` default, and the meta retention window stays at 7 days.

New file: `tests/unit/test_topsailai_disk_growth_adversarial.py`, 6 tests,
`6 passed in 1.33s`.

### Bytes written by a prompt loop

`test_closed_stdin_writes_bounded_bytes` runs `input_one_line` in a child
process with stdin at `/dev/null` and asserts the child exits 0, writes fewer
than 200 bytes, and prints the prompt exactly once.

`test_negative_control_reproduces_unbounded_output` runs the pre-fix loop
(`except EOFError: message = ""` then reprompt) in the same harness and asserts
it writes more than 1000 bytes and more than 10x the fixed path. Without this
control a green byte assertion could pass because the child never reached the
prompt at all.

`test_session_lifecycle_keeps_total_output_bounded` runs 50 turns over a closed
channel and asserts total output stays under 20x one prompt per turn and that
exactly 50 prompts were written. A per-turn bound alone would not catch growth
accumulating across a long run, which is how the incident reached 51.75 GB.

Measured: fixed path 8 bytes, pre-fix path 7992 bytes for one turn, and 399600
bytes for 50 turns.

### Deleted-but-open detection

`test_deleted_descriptor_keeps_size_until_close` writes 64 KiB, unlinks the
path, and asserts the open descriptor still reports the full size while the path
is gone. This is the exact mechanism that made the space invisible to
path-based inspection.

`test_orphan_descriptor_is_visible_in_descriptor_table` reads
`/proc/self/fd/<n>` and asserts the target is marked `deleted` and still names
the removed file, so the condition is diagnosable before the descriptor closes.
Skipped when `/proc` is unavailable.

`test_closing_the_descriptor_releases_the_held_space` asserts the release is
tied to the descriptor rather than the path, which is why killing the owning
processes resolved the incident.

### Negative control result

Reverting only the `if not env_tool.is_input_pipe_enabled(): raise` branch in
`workspace/input_tool.py` turned 3 of the 6 tests red with
`7992 not less than 200`, `7992 not greater than 79920`, and
`399600 not less than 1000`. Restoring the branch returned all 6 to green, so
the tests observe the real behaviour rather than the test harness.

### Probe harness defect found and fixed

The first probe hung for 180 seconds. The cause was not the product code:
`topsailai/__init__.py` loads `.env.local` at import time, and that file sets
`TOPSAILAI_INPUT_PIPE_ENABLED=1` on this host, so the probe blocked on a named
pipe instead of reaching the closed-stdin branch. The test harness now forces
`TOPSAILAI_INPUT_PIPE_ENABLED=0` in the child environment; `load_dotenv` does not
override an existing value, so the explicit setting wins.

### Regression

`tests/unit/test_topsailai_workspace_input_tool.py` plus
`tests/unit/events/test_backends.py`: **88 passed in 1.19s**.

### Still open after this change

1. Action 2, routed to the sibling Go project.
2. Action 6, an operational Docker cleanup on `/opt`.
3. The two rejected configuration decisions are recorded as deliberate, not
   pending: the events count default stays unlimited and the meta retention
   window stays 7 days.

## Required-behavior gaps 2 and 5 covered on 2026-11-18

The Human authorized closing the two remaining test gaps: "如果是测试要补齐的话，就去补".
Both were test gaps, not product defects. No production code was modified.

### Gap 2: disk-full retains meta and stdout

`tests/unit/test_topsailai_workspace_agent_agent_shell_base_db_io.py:498`
`test_interactive_disk_full_retains_meta_and_stdout_artifacts`

Creates a real `{session_id}.{pid}.session.meta` with `status: running` and
`end_ts: null`, redirects the meta and tee folders to `tmp_path`, enables
`TOPSAILAI_ENABLE_SESSION_TEE_OUT`, and drives `AgentChat.run()` with
`ai_agent.run` raising `sqlite3.OperationalError(13, "database or disk is full")`
on the first turn and returning a normal answer on the second.

Asserts the session survives and reaches the next prompt
(`input_mock.assert_called_once_with(hook=...)`), the meta file still exists and
is finalized to `status: completed` with a non-null `end_ts`, and the stdout
artifact still exists and contains both `Database write failed` and
`database or disk is full`.

The requirement wording says "meta and stdout retained". The real contract is
that metadata is finalized rather than left `running`, because the session
recovered and ended normally. The assertion targets the actual behavior and the
docstring records the distinction, so a future reader does not mistake
`completed` for a weakened assertion.

### Gap 5: orphaned artifacts are actually removed

`tests/unit/test_topsailai_session_cleanup_edges.py:97`
`test_orphaned_artifacts_are_actually_removed_and_unrelated_data_survives`

Builds one stopped owner whose stdout anchor is absent (three orphan artifacts
plus its own meta) and one unrelated live owner (stdout anchor present), plus an
unrelated plain file. Captures each orphan's size before cleanup, runs
`clean_orphaned_session_files` with a probe reporting `STOPPED`, then asserts the
reported deleted set equals the orphan set, every orphan path is gone, the
unrelated owner's files and the plain file are byte-identical, and the owner's
own meta is preserved because it is an owner record rather than a lifecycle
artifact.

`tests/unit/test_topsailai_session_cleanup_edges.py:161`
`test_orphan_cleanup_reports_without_deleting_in_dry_run` asserts a dry run
reports the orphan while leaving it on disk.

Scope narrowing: the requirement also names "caches". No cache-cleanup API
exists in this project (`grep` for `clean.*cache`, `purge`, `prune` across
`workspace/`, `context/`, `utils/` returns nothing), so the assertion covers
session lifecycle artifacts, which is the class that actually accumulated during
the incident. A future cache-cleanup path needs its own assertion.

### Negative controls

Three deliberate regressions, each reverted from a backup:

| Regression | Result |
|---|---|
| `TOPSAILAI_ENABLE_SESSION_TEE_OUT` forced to `False` | `1 failed, 17 passed` — stdout artifact missing |
| `os.remove(full_path)` removed from `clean_orphaned_session_files` | `1 failed, 10 passed` — `orphan survived cleanup: a.123.session.stderr` |
| Completion `update_session_meta_status` removed from `run()`'s `finally` | `1 failed, 17 passed` — `assert 'running' == 'completed'` |

Each control proves the new test observes the behavior rather than passing
vacuously.

### Regression

Six related files: **192 passed in 6.37s**.

```
tests/unit/test_topsailai_session_cleanup_edges.py
tests/unit/test_topsailai_workspace_agent_agent_shell_base_db_io.py
tests/unit/test_topsailai_disk_growth_adversarial.py
tests/unit/test_topsailai_workspace_session_meta.py
tests/unit/test_topsailai_context_session_activity.py
tests/unit/test_topsailai_context_session_cleanup_guard.py
```

### Required-behavior coverage after this change

| # | Requirement | Status |
|---|---|---|
| 1 | Bounded growth across a repeated lifecycle | covered |
| 2 | Disk-full survives, reaches prompt, meta and stdout retained | covered |
| 3 | Closed stdin exits, measured in bytes | covered |
| 4 | Deleted-but-open detected, space measured | covered |
| 5 | Orphans actually removed, unrelated data unaffected | covered |
| 6 | Killed test run leaves no temp build tree | out of workspace, sibling Go project |
| 7 | Dead-PID `running` meta becomes cleanable | covered |
| 8 | `TOPSAILAI_EVENTS_FILE_MAX_COUNT` enforces a bound when set | covered |

Seven of eight are covered. Only requirement 6 remains, and it cannot be
implemented here because this workspace contains no Go sources.

### Still open after this change

1. Requirement 6, routed to the sibling Go project.
2. Action 6, an operational Docker cleanup on `/opt`.
3. The two rejected configuration decisions are recorded as deliberate, not
   pending: the events count default stays unlimited and the meta retention
   window stays 7 days.
