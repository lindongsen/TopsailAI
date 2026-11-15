# Runtime Emergency Environment Override

Change one environment variable of an **already running** agent process, in
memory, without restarting it. Nothing is written to disk.

This is an operator procedure. It assumes you did not write the code and may not
know why the process is misbehaving. It tells you how to decide whether to use
it, how to do it without making things worse, and how to prove afterwards that it
worked.

## Background

A TopsailAI agent worker is a long-running process that drives an LLM through a
task. It keeps the whole conversation in memory: the task, every tool call and
its result, and the model's reasoning. That context *is* the work. Restarting
does not resume it — a restart begins a new conversation with an empty context,
and the agent has to redo everything from the beginning.

Configuration reaches the process through environment variables, loaded from
files at startup. Once the process is running those files are no longer
consulted, so editing a file changes nothing until the next start.

That combination — valuable in-memory state plus startup-only configuration — is
why an operator sometimes needs to change a value inside a live process instead
of restarting it.

## What problem this solves

An agent process is stuck, looping, or burning resources because one
configuration value is wrong. Restarting would work, but the process has hours of
unrecoverable work in its context, so a restart is the expensive option.

You can reach into the live process and change that value instead.

## Decide first: is this the right tool

| Situation | Do this |
|---|---|
| The process is cheap to restart and holds nothing valuable | Restart it. Do not use this procedure. |
| The value is wrong in a config file and the process is idle | Fix the file, then restart. |
| The process holds hours of work and one value is blocking it | Use this procedure. |
| You do not know which value is wrong | Do not guess. Diagnose first. |
| The defect is in code logic, not configuration | This procedure cannot help. Record an issue. |

Two rules that are not negotiable:

1. **This is a mitigation, not a fix.** The underlying defect still exists. Record
   it as an issue in the same session, or the next operator will hit it again.
2. **Record the original value before you change anything.** You cannot roll back
   from memory, and the process environment snapshot is not a reliable source
   (see Pitfalls).

## Before you start: three checks

### Check 1 — is the process actually running

Do not trust the session status command alone. It can report `idle` for a process
that is actively working, because it infers state from a lock it may be unable to
acquire. A session with locking disabled is reported `idle` while it is busy.

Confirm with two independent signals:

```bash
# Signal A: the process exists and is not a zombie
ps -o pid,stat,etime,cmd -p PID

# Signal B: the session output file is growing
ls -la {TOPSAILAI_HOME}/workspace/task/SESSION_ID.PID.session.stdout
# wait a few seconds, then read it again and compare the size
```

A `stat` of `Z` means a zombie; the process is gone. An unchanged file size over
a meaningful interval means the process is not producing output, which may be
normal for a long LLM call but is not evidence of health.

`topsailai workspace --format json` lists every discovered session with its
`session_id`, `pid`, and `status`, and is a convenient way to find the PID.

### Check 2 — is the control channel reachable

```bash
topsailai runtime control heartbeat -s SESSION_ID -p PID --json
```

Look for `"alive": true` inside `response.result`. A reachable channel proves the
process can accept instructions. It does **not** prove the agent is making
progress.

If this fails with `target_not_found`, the session ID and PID do not match a
running process. Re-discover them rather than retrying the same pair.

### Check 3 — do you know the original value

Read it before changing it:

```bash
topsailai runtime control call_instruction -s SESSION_ID -p PID \
  -a '{"instruction":"env.get","args":["VARIABLE_NAME"]}' --json
```

The value is in `response.result`. Write it down. If the result is `null`, the
variable was never set and the effective value comes from the code default, which
you must look up separately.

## Procedure

### Step 1 — read the current value

As in Check 3. Record it verbatim.

### Step 2 — set the new value

```bash
topsailai runtime control call_instruction -s SESSION_ID -p PID \
  -a '{"instruction":"env.set","args":["VARIABLE_NAME","NEW_VALUE"]}' --json
```

Success looks like `"status": "ok"` with a result beginning
`set environment ok:`. The result echoes the old and new values, **except** for
keys that look sensitive, which are masked (see Pitfalls).

### Step 3 — verify inside the process

Repeat Step 1 and confirm the returned value is the new one.

This is the only valid verification. Do not verify by reading the process
environment file, and do not verify by reading the config file on disk.

### Step 4 — confirm the effect

Setting a value is not the same as fixing the symptom. Observe the actual
behaviour you were trying to change: the log line that should stop appearing, the
counter that should stop growing, the error that should no longer be raised.

If the symptom persists, the variable was not the cause, or it is not read at
call time. Revert before trying something else, so you do not stack unknown
changes.

## Which variables can be changed at runtime

A variable takes effect immediately only if its reader re-reads the environment
on every use. A value captured once — in a constructor, at import time, or in a
module-level constant — is frozen for the process lifetime, and setting it later
changes nothing while appearing to succeed.

You cannot tell which kind a variable is from its name. Check the source:

```bash
grep -rn "VARIABLE_NAME" --include=*.py . | grep -v tests
```

Then look at each hit:

- Read inside a function that runs per request, per check, or per turn → **hot-changeable**.
- Read inside `__init__`, at module top level, or assigned to an attribute once → **frozen**.

A frozen variable will accept the set and report success. The only way to change
it is a restart.

## Pitfalls

### Instruction names need the module prefix

`env.set` and `env.get` are the registered names. A bare `set` or `get` is
rejected:

```json
{"status": "error", "error": "unknown instruction: set"}
```

The CLI reports this as `exit_code: 6`, `error_code: "control_rejected"`. It is
not a transport failure; the request reached the process and was refused.

To list every registered instruction, call `help`:

```bash
topsailai runtime control call_instruction -s SESSION_ID -p PID \
  -a '{"instruction":"help","args":[]}' --json
```

### The set echo cannot verify a sensitive-looking key

`env.set` masks the old and new values when the variable name contains a
sensitive word such as `key`, `token`, `secret`, `password`, or `credential`. The
result then reads:

```text
set environment ok: SOME_TOKEN_THRESHOLD old=*** new=***
```

That is a successful set with a masked echo, not a failure. Because the echo
carries no value, **`env.get` is the only way to confirm what the process now
holds**. Never conclude "the set failed" from a masked echo.

### The process environment file cannot verify the change

The per-process environment snapshot is taken at process start. An in-memory
mutation is not written back to it, so it keeps showing the startup value
forever. Reading it after a successful override will show the old value and lead
you to believe the override failed.

It is still useful for one thing: recovering the **original** value when you
forgot to record it, because it reflects the configuration the process started
with.

### Related values must move together

A threshold often does not decide behaviour on its own; a derived limit may gate
it first. Raising a threshold while the limit that feeds it stays small leaves
the old ceiling in place, and the new threshold is never reached.

Change the whole chain, then verify each value. A worked example is below.

### The change dies with the process

Nothing is persisted. A restart restores the original values. If the override
must survive, it belongs in the environment file, which is a separate and
deliberate change that requires its own review.

### Do not stack unverified changes

If the first override does not fix the symptom, revert it before trying a second
one. Two unknown changes make it impossible to attribute the result, and the
process may end up in a state nobody can reproduce.

## Worked example: a derived limit chain

Many limits are computed from other values rather than configured directly:

```text
send_limit         = model_max_context - max_completion_tokens
summary_safe_limit = send_limit - operation_margin
low_limit          = low_ratio  * summary_safe_limit
high_limit         = high_ratio * summary_safe_limit
```

With a `1000000` context, `30000` completion tokens, an `8192` margin, and ratios
`0.73` / `0.93`, the chain resolves to `970000`, `961808`, `702119`, `894481`.

Two consequences an operator must understand:

- **Raising only the outer value does nothing** if an inner derived limit is
  still the binding constraint. Change the input, then re-read the derived
  values.
- **A lower branch may act unconditionally.** If the low branch triggers a
  behaviour regardless of any threshold, then the low limit is the real ceiling.
  Setting a threshold above it makes the threshold meaningless: it claims no
  action is needed while the branch forces the action anyway. Set the threshold
  at or below the binding limit, not above it.

Verify the chain by reading the process's own report of its effective limits
rather than recomputing them by hand.

## Rollback

Set each variable back to the recorded original value with the same procedure,
then verify with `env.get`.

Because nothing was persisted, a restart also restores the original state. If the
process is going to be restarted anyway, restarting is the cleaner rollback: it
cannot leave a partially reverted set of values behind.

Revert in the reverse order of application, and revert every variable you
changed, not only the one that seemed to matter.

## Reporting

Whoever reads your handover needs five things:

1. **What was changed** — every variable, with old and new values.
2. **Why** — the symptom, and the evidence that pointed at this variable.
3. **Verification** — the `env.get` output proving the new value is live, and the
   observation proving the symptom changed.
4. **Scope** — that the change is process-scoped and dies with the process.
5. **The underlying defect** — the issue you recorded, so the override is not
   mistaken for a fix.

State the residual risk explicitly. An override that re-enables a known-bad path,
or that lowers a safety ceiling, is a decision someone must be able to see and
reverse. Do not let it look like a clean fix.

## Quick reference

| Action | Command |
|---|---|
| Find session and PID | `topsailai workspace --format json` |
| Confirm process alive | `ps -o pid,stat,etime,cmd -p PID` |
| Confirm output growing | `ls -la {TOPSAILAI_HOME}/workspace/task/SESSION_ID.PID.session.stdout` |
| Probe control channel | `topsailai runtime control heartbeat -s SESSION_ID -p PID --json` |
| Read a value | `topsailai runtime control call_instruction -s SESSION_ID -p PID -a '{"instruction":"env.get","args":["NAME"]}' --json` |
| Set a value | `topsailai runtime control call_instruction -s SESSION_ID -p PID -a '{"instruction":"env.set","args":["NAME","VALUE"]}' --json` |
| List instructions | `topsailai runtime control call_instruction -s SESSION_ID -p PID -a '{"instruction":"help","args":[]}' --json` |
| Recover original value | `tr '\0' '\n' < /proc/PID/environ \| grep NAME` |

Exit codes from the control CLI: `0` acknowledged, `2` usage error, `3` target
not found, `5` timeout, `6` control rejected by the process.
