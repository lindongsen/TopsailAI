---
name: agent-cluster-watch-trigger
description: Use when a user wants a local script to run automatically when a watched Agent Cluster session becomes blocked on input, or when they ask what environment variables such a script receives, why it did not run, or how to make `watch --trigger` fire. Covers the `watch --trigger` command surface, the default script path, the thirteen `AGENT_CLUSTER_*` payload variables, the whitelisted child environment, the five second timeout, the foreground-only limits of the mechanism, and a ready-to-install Python script that rings one terminal bell on `running -> waiting_input`.
version: 1.1.0
author: DawsonLin
license: Apache-2.0
metadata:
  tags: [agent-cluster, watch, trigger, notification, environment-variables, cli]
  related_skills: [topsailai-agent-worker]
---

# Agent Cluster Watch Trigger

## Overview

`agent-cluster-cli` runs an interactive REPL. Its `watch` command re-renders the session
table on a timer until any key is pressed. With `--trigger`, `watch` also runs one local
script when a watched session transitions from `running` to `waiting_input`.

The mechanism exists so an operator who is already looking at the table can react without
typing a second command. It is a **foreground convenience**, not a reliability promise:

- It lives in the operator's own client process. Closing the terminal ends it.
- It observes whatever the Endpoint last collected. It does not subscribe to provider
  events.
- The delay is the Endpoint collection interval (about 10 seconds), not the watch
  interval. A transition that completes between two collections is never observed.

State that plainly when a user expects unattended or instant reaction, and point them at
the Endpoint drive controller or a provider hook instead.

## When to Use

Use this skill when the user wants a local script to run on a session state transition
while they are watching, or when they are debugging why such a script did not run.

Do not use this skill when the user needs:

- Reaction that survives a closed terminal, a disconnect, or a reboot. That belongs in the
  Endpoint or in the provider's own hook surface.
- Reaction to a transition that may complete in under ten seconds. Sampling cannot see it.
- Reaction to a state other than `running -> waiting_input`. Only that transition fires
  today; other transitions are a code change, not a configuration change.

## Command Surface

```text
watch [interval] [--force] [--trigger[=<path>]]
```

| Form | Meaning |
|---|---|
| `watch --trigger` | Use the default script path. |
| `watch --trigger=<path>` | Use the named script. |
| `watch 2s --trigger` | Combine with an interval and with `--force` in any order. |
| `watch --trigger --trigger` | Rejected. A repeated flag is a usage error, never a silent override. |
| `watch --trigger=` | Rejected. An empty path is a usage error rather than a silent fallback to the default. |

A relative `--trigger=<path>` is resolved with `filepath.Abs`, so it is relative to the
directory the CLI was started in, not to the session working directory.

`watch` is available in workspace and endpoint scope. It is unavailable in session scope,
because a forced refresh can invalidate the pinned session.

`--json` is rejected in interactive mode, so a trigger script is the only machine-readable
output path `watch` offers.

### Default script path

```text
${HOME}/.topsailai/topsailai-agent-cluster.on-state-change.trigger
```

The file name names the event rather than the command, so a future event can add its own
file without renaming this one. The directory is the same per-user configuration directory
the CLI already reads, so a trigger script needs no second convention.

### Path validation

The two forms are validated differently, and the difference is deliberate:

| Form | Missing file | Not executable | Is a directory |
|---|---|---|---|
| `--trigger=<path>` | Hard error, `watch` refuses to start | Hard error | Hard error |
| `--trigger` (default) | One diagnostic note, loop still runs | One diagnostic note | One diagnostic note |

An explicit path is strict because the operator named it: a silent no-op would look like a
working trigger. The default path is lenient because the operator only asked for the
convention: an absent script is reported so the banner never claims a script will run when
none is installed.

## Environment Payload

The script receives exactly these variables and nothing else. Every value is a string,
including the booleans and the timestamp.

| Variable | Value | Meaning |
|---|---|---|
| `AGENT_CLUSTER_EVENT` | `state_change` | The event type. Dispatch on this value, so a future event type is a new value rather than a new payload shape. |
| `AGENT_CLUSTER_STATE` | `waiting_input` | The state just observed. It is the standard cluster vocabulary, never a provider word. |
| `AGENT_CLUSTER_PREVIOUS_STATE` | `running` | The state observed on the previous collection for the same session identity. |
| `AGENT_CLUSTER_ENDPOINT_ID` | opaque ID | The Endpoint that reported the session. Use it to address the machine in a follow-up CLI call. |
| `AGENT_CLUSTER_CLUSTER_SESSION_ID` | opaque ID | The cluster's own session identity. **This is the identity to use in a follow-up CLI call.** |
| `AGENT_CLUSTER_PROVIDER_SESSION_ID` | provider string | The provider's own session identifier. It is provider detail, so prefer the cluster ID. |
| `AGENT_CLUSTER_SESSION_NAME` | provider string | The display name the provider reported. It is untrusted text, so never `eval` it. |
| `AGENT_CLUSTER_PROVIDER_GENERATION` | opaque string | The provider process generation. A changed generation means a different process, so the trigger treats it as a new subject rather than a transition. |
| `AGENT_CLUSTER_ADAPTER_ID` | opaque ID | The adapter that produced the observation. |
| `AGENT_CLUSTER_PROJECT_WORKSPACE` | path string | The session working directory the provider reported. Untrusted text, so never `eval` it. |
| `AGENT_CLUSTER_UNVERIFIED` | `true` or `false` | Whether the provider could not verify the liveness of the process behind the record. |
| `AGENT_CLUSTER_STALE` | `true` or `false` | Whether the observation is retained last-known data rather than a fresh collection. |
| `AGENT_CLUSTER_OBSERVED_AT_MS` | epoch milliseconds, or empty | When the provider observed the state. Empty means the report carried no time. |

### Why `OBSERVED_AT_MS` matters

The trigger fires on a sampled state, so the observation can already be seconds old. A
script that wants to say "just now" must compare this value against the current time
instead of assuming the transition happened at invocation time.

### Why there is no PID

The payload deliberately carries no process ID. A PID is a locator hint rather than an
identity, it is recycled by the operating system, and a script that killed a bare PID could
kill an unrelated process. A script that needs to act on the session calls the CLI with
`AGENT_CLUSTER_CLUSTER_SESSION_ID`, which goes through the normal permission, confirmation
and generation checks.

### Inherited variables

Only these are forwarded from the client process, because a script needs them to resolve
its interpreter and locate its own configuration:

```text
PATH  HOME  LANG  LC_ALL  TZ  TMPDIR
```

`TERM` is set to `dumb` rather than forwarded, so a script cannot emit escape sequences
into a surface the editor owns.

**Nothing else is inherited.** The client process holds the cluster credentials, including
one variable that maps every Endpoint to its token. Inheriting the environment would hand
each notification script the authority to operate the whole fleet, so the child environment
is built from a whitelist. A script that needs a credential must read it from its own file,
never from the environment.

## Execution Contract

| Property | Behaviour |
|---|---|
| Shell | Never used. The script is executed as one argv array, so a payload value can never be reinterpreted as syntax. |
| Process group | The script runs in its own process group, so a timeout kills the whole tree rather than only the direct child. |
| Timeout | 5 seconds. A notification that has not finished in five seconds is already useless to an operator watching the screen. |
| Output | Captured and discarded. The editor is the only writer, so a script that printed could corrupt the table. |
| Failure | Reported once as a diagnostic. It is never retried, because the transition was already consumed. |
| Overlap | A transition that arrives while a script is still running is dropped with one diagnostic. It is never queued, because a backlog would describe states the operator already saw. |
| Stop | Pressing any key cancels the in-flight script and waits for it, so no orphan process survives the loop. |

## Writing a Script

A trigger script is an ordinary executable file. It needs a shebang and the executable bit.

```bash
#!/bin/bash
# Append one line per transition to a local log.
printf '%s %s %s %s -> %s\n' \
  "$(date -Is)" \
  "$AGENT_CLUSTER_ENDPOINT_ID" \
  "$AGENT_CLUSTER_SESSION_NAME" \
  "$AGENT_CLUSTER_PREVIOUS_STATE" \
  "$AGENT_CLUSTER_STATE" \
  >> "$HOME/.topsailai/trigger.log"
```

```bash
#!/bin/bash
# Post to a chat channel. The credential is read from the script's own file,
# never from the environment, because the environment carries no credential.
set -euo pipefail
token=$(cat "$HOME/.config/my-notifier/token")
curl -sS -X POST https://example.invalid/hook \
  -H "Authorization: Bearer $token" \
  -d "text=session $AGENT_CLUSTER_SESSION_NAME on $AGENT_CLUSTER_ENDPOINT_ID needs input"
```

```bash
#!/bin/bash
# Ignore stale observations, so a retained last-known row never raises an alert.
[ "$AGENT_CLUSTER_STALE" = "true" ] && exit 0
[ "$AGENT_CLUSTER_UNVERIFIED" = "true" ] && exit 0
notify-send "agent needs input" "$AGENT_CLUSTER_SESSION_NAME"
```

### Ring the terminal bell

The shipped script `scripts/watch-trigger-bell.py` rings one bell on the documented
transition. It is the smallest useful trigger, and it demonstrates the only channel that
actually reaches the operator.

```python
import signal

PREVIOUS_STATE = "running"
STATE = "waiting_input"
BELL = b"\a"
TERMINAL_DEVICE = "/dev/tty"


def should_ring(previous_state, state):
    """Return True only for the running -> waiting_input transition."""
    return previous_state == PREVIOUS_STATE and state == STATE


def ring():
    """Write one bell to the controlling terminal."""
    try:
        signal.signal(signal.SIGTTOU, signal.SIG_IGN)
    except (AttributeError, ValueError, OSError):
        pass
    try:
        with open(TERMINAL_DEVICE, "wb", buffering=0) as terminal:
            terminal.write(BELL)
        return True
    except OSError:
        return False
```

`scripts/watch-trigger-bell.py` is the complete file; read it rather than retyping this
excerpt, so the installed script and the documented behaviour cannot drift apart.

Three details make it correct rather than merely short:

- **It writes to `/dev/tty`, not to stdout.** `print("\a")` would be captured and discarded
  with the rest of the script's output, so the operator would hear nothing. The terminal
  device is the only channel the runner does not own.
- **It ignores `SIGTTOU`.** The runner puts the script in its own process group, so a
  terminal with `TOSTOP` set would otherwise stop the script on that write.
- **A missing terminal is not a failure.** The script exits 0 without a bell, because a
  headless run has no operator to alert and a non-zero exit would only add a diagnostic row
  to the table.

The state check is a guard, not a second detection path: `watch` already fires only on
`running -> waiting_input`. It keeps the script correct when it is invoked by hand or by a
future caller, and it costs one string comparison.

### Install and run

```bash
mkdir -p "$HOME/.topsailai"
cat > "$HOME/.topsailai/topsailai-agent-cluster.on-state-change.trigger" <<'SCRIPT'
#!/bin/bash
printf '%s %s %s\n' "$(date -Is)" "$AGENT_CLUSTER_ENDPOINT_ID" "$AGENT_CLUSTER_SESSION_NAME" \
  >> "$HOME/.topsailai/trigger.log"
SCRIPT
chmod +x "$HOME/.topsailai/topsailai-agent-cluster.on-state-change.trigger"
```

To install the shipped bell script instead of writing your own, point the default path at it
with a one-line bash wrapper. The wrapper keeps the shebang `bash` and the body a single
executable command:

```bash
mkdir -p "$HOME/.topsailai"
cat > "$HOME/.topsailai/topsailai-agent-cluster.on-state-change.trigger" <<'SCRIPT'
#!/bin/bash
exec /usr/bin/python3 /absolute/path/to/scripts/watch-trigger-bell.py
SCRIPT
chmod +x "$HOME/.topsailai/topsailai-agent-cluster.on-state-change.trigger"
```

Both paths in the wrapper must be absolute, because the runner starts the script in the
directory the CLI was launched from, not in the skill folder. `exec` replaces the shell with
the interpreter, so the runner sees one process instead of a shell waiting on a child, and a
timeout kills the interpreter directly rather than orphaning it.

The wrapper is required rather than optional: the default path is a single fixed file, so the
trigger must live there to be found by a bare `watch --trigger`. Keeping the Python logic in
the skill folder also means an edit to the shipped script takes effect on the next transition
without reinstalling the wrapper.

Then inside the REPL:

```text
watch --trigger
watch 2s --trigger=/path/to/another/script
```

The banner prints `trigger: <path> on running -> waiting_input` when a script is armed, or
one note explaining why none will run.

## Debugging a Script That Never Runs

Check these in order. Each one has a distinct symptom.

1. **The banner names no script.** The path was not resolved. Read the note it printed:
   a missing default script, a directory, or a missing executable bit.
2. **The script is not executable.** `chmod +x` it. An explicit path is refused at arm
   time; a default path is reported as a note and the loop still runs.
3. **The transition never happened.** The trigger fires only on `running -> waiting_input`.
   A session that was already waiting when the loop started only records a baseline, and a
   session that goes `idle -> waiting_input` does not fire.
4. **The transition happened between two collections.** Sampling cannot see it. This is a
   property of the mechanism, not a defect.
5. **The provider reports a different word.** The adapter normalizes provider vocabulary
   onto the standard states, so a provider word never reaches the payload. If a state looks
   unexpected, the adapter mapping is the place to look, not the script.
6. **The script ran but produced nothing.** Its output is discarded by design. Write to a
   file or send a message instead of printing.
7. **The script failed.** One diagnostic names the failure. It is not retried, so a
   transient failure is lost on purpose.

## Common Pitfalls

- **Expecting unattended reaction.** The mechanism dies with the terminal. Say so before
  writing the script, and route the requirement to the Endpoint or a provider hook.
- **Expecting instant reaction.** The delay is the collection interval, about ten seconds.
  Shortening the watch interval does not help, because it only re-reads the same document.
- **Expecting every transition.** Only `running -> waiting_input` fires. A round trip that
  completes between two collections is invisible.
- **Reading a credential from the environment.** The environment is a whitelist and carries
  no credential. A script that needs one reads its own file.
- **Printing to the terminal.** Output is discarded, and the editor owns the terminal. A
  bell or a message must go to `/dev/tty` or to a file, never to stdout.
- **`eval`-ing a payload value.** `SESSION_NAME` and `PROJECT_WORKSPACE` are provider text.
  Quote them, never evaluate them.
- **Killing a PID.** The payload carries no PID on purpose. Use the cluster session ID with
  the CLI.
- **Assuming a script failure is retried.** It is reported once and dropped.
- **Assuming a dropped overlap is queued.** It is dropped with one diagnostic, because a
  backlog would describe states the operator already saw.

## Verification Checklist

- [ ] The script has a shebang and the executable bit set.
- [ ] The script reads only the documented `AGENT_CLUSTER_*` variables and the six
      inherited basics.
- [ ] The script writes to a file, sends a message, or rings `/dev/tty` instead of printing
      to stdout, which the runner discards.
- [ ] The script quotes every payload value and never evaluates one.
- [ ] The script finishes well inside five seconds, or does its slow work in the background.
- [ ] The script tolerates `AGENT_CLUSTER_STALE=true` and `AGENT_CLUSTER_UNVERIFIED=true`
      when an alert on retained or unverified data would be wrong.
- [ ] The banner printed `trigger: <path> on running -> waiting_input`, not a note.
- [ ] The user was told the delay is the collection interval and that the mechanism ends
      with the terminal.

## File Structure Description

- **bin/**: None. This skill documents an existing CLI capability and needs no executable.
- **scripts/**: `watch-trigger-bell.py` is a ready-to-install trigger that rings one terminal
  bell on `running -> waiting_input`. It is a reference implementation of the payload check
  and of the `/dev/tty` output channel; install it by pointing a one-line bash wrapper at it
  from the default path.
- **references/**: None. The payload table and the execution contract above are complete.
- **assets/**: None.
