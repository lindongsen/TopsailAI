---
name: agent-cluster-watch-trigger
description: Use when a user wants a local script to run automatically when a watched Agent Cluster session becomes blocked on input, or when they ask what environment variables such a script receives, why it did not run, how to make `watch --trigger` fire, or how to add a reaction of their own. Covers the `watch --trigger` command surface, the default script path, the thirteen `AGENT_CLUSTER_*` payload variables, the whitelisted child environment, the five second timeout, the foreground-only limits of the mechanism, and the shipped generic executor that dispatches on the state transition and runs one independent behaviour script per reaction (a system bell sound and a desktop notification popup on `running -> waiting_input`).
version: 1.3.0
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
watch [interval] [--force] [-t|--trigger[=<path>]]
```

| Form | Meaning |
|---|---|
| `watch --trigger` | Use the default script path. |
| `watch -t` | The same request, written with the short spelling. |
| `watch --trigger=<path>` | Use the named script. |
| `watch -t=<path>` | The same request, written with the short spelling. |
| `watch 2s --trigger` | Combine with an interval and with `--force` in any order. |
| `watch --trigger --trigger` | Rejected. A repeated flag is a usage error, never a silent override. |
| `watch -t --trigger` | Rejected. The two spellings name one flag, so repeating it in any combination is a usage error. |
| `watch --trigger=` | Rejected. An empty path is a usage error rather than a silent fallback to the default. |
| `watch -t=` | Rejected for the same reason. |
| `watch -t <path>` | Rejected. The value is attached with `=`, because the interval is already positional. |

A relative `--trigger=<path>` or `-t=<path>` is resolved with `filepath.Abs`, so it is
relative to the directory the CLI was started in, not to the session working directory.

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
| `--trigger=<path>`, `-t=<path>` | Hard error, `watch` refuses to start | Hard error | Hard error |
| `--trigger`, `-t` (default) | One diagnostic note, loop still runs | One diagnostic note | One diagnostic note |

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

### The executor and its behaviour scripts

The shipped trigger is split in two, and the split is the point:

| File | Role | Owns |
|---|---|---|
| `scripts/watch-trigger-exec.py` | Executor | **When** something runs. It reads the transition, resolves the behaviour directory, and runs every behaviour in it under one deadline. |
| `scripts/behaviours/<previous>_to_<state>/<name>` | Behaviour | **What** runs. One reaction per file: a sound, a popup, a log line, a chat message. |
| `scripts/behaviours/_desktop.py` | Shared helper | Desktop session discovery used by more than one behaviour. It is not a behaviour, so the executor never runs it. |

The executor contains no reaction and no transition-specific condition. Adding a reaction is a
new file in a transition directory, not an edit to shared code. That is what keeps the two
concerns from drifting: a behaviour cannot change *when* it runs, and the executor cannot change
*what* a reaction does.

```text
scripts/
- watch-trigger-exec.py
- behaviours/
  - _desktop.py
  - running_to_waiting_input/
    - bell.py
    - notify.py
```

### The transition key

A behaviour directory is named after the transition it reacts to:

```text
<AGENT_CLUSTER_PREVIOUS_STATE>_to_<AGENT_CLUSTER_STATE>
```

So `running -> waiting_input` resolves to `running_to_waiting_input/`.

The separator is `_to_` rather than `->` on purpose. A directory name is also a shell word, and
`->` is a redirection operator: `cd running->waiting_input` would create a file named
`waiting_input` instead of entering a directory. A key that cannot be typed into a shell is a key
that will be mistyped during debugging.

An empty state becomes `unknown`, so a partial payload resolves to a real directory name instead
of a name with a hole in it.

### Behaviour resolution

The executor searches these roots in order, and a file name is the behaviour identity:

| Order | Root | Purpose |
|---|---|---|
| 1 | `$AGENT_CLUSTER_TRIGGER_BEHAVIOURS` | Explicit override, for running the executor by hand. |
| 2 | `$HOME/.topsailai/topsailai-agent-cluster.triggers` | Per-user additions and overrides. |
| 3 | `scripts/behaviours` beside the executor | The shipped reactions. |

A user file **shadows** a shipped file of the same name rather than running beside it. Without
that rule, overriding `notify.py` would fire two popups, and a double-fire is the one failure a
user cannot see by reading the code. Files whose names begin with `_` or `.` are skipped, which is
how `_desktop.py` stays a helper instead of becoming a behaviour.

The override variable exists for hand runs only. The trigger runner builds the child environment
from a whitelist, so it never reaches a script in normal operation; behaviour discovery is
path-based for that reason.

### Behaviour execution

| Property | Behaviour |
|---|---|
| Invocation | One argv array per behaviour, never a shell. |
| Executable file | Run directly, so the kernel honours its own shebang and a behaviour may be written in any language. |
| Non-executable `.py` | Run through the executor's interpreter instead of being skipped, because a missing mode bit is a packaging mistake rather than an intent. |
| Process group | Each behaviour runs in its own session, so a timeout kills the behaviour **and everything it started**. |
| Deadline | One four-second budget shared by every behaviour in the dispatch, below the runner's five-second kill. |
| Output | Discarded. The editor owns the terminal. |
| Failure | Ignored. One behaviour cannot prevent the next one from running. |
| Exit | Always 0, so a headless run never adds a diagnostic row to the table. |

The shared budget is a deliberate trade: a behaviour that spends it leaves nothing for the next
one. A bounded total matters more than every behaviour getting a turn, because the runner kills
the whole group at five seconds regardless.

### The shipped behaviours

`running_to_waiting_input/bell.py` plays the system bell sound. `running_to_waiting_input/notify.py`
raises a desktop notification popup. Both are external channels, because the runner captures and
discards the script's terminal streams and a terminal BEL was not audible to the operator.

```python
def behaviour_files(key):
    """Return the behaviour files for one transition, highest precedence first."""
    selected = {}
    for root in behaviour_roots():
        directory = os.path.join(root, key)
        if not os.path.isdir(directory):
            continue
        for name in sorted(os.listdir(directory)):
            if name.startswith(".") or name.startswith("_"):
                continue
            path = os.path.join(directory, name)
            if not os.path.isfile(path):
                continue
            selected.setdefault(name, path)
    return [selected[name] for name in sorted(selected)]
```

Read the shipped files rather than retyping this excerpt, so the installed scripts and the
documented behaviour cannot drift apart.

The popup body names the session and the Endpoint, for example
`demo-session on ai-dev is waiting for input`. It is built from `AGENT_CLUSTER_SESSION_NAME` and
`AGENT_CLUSTER_ENDPOINT_ID`, and it degrades to a generic sentence when either is empty, so a
popup never shows a dangling `on`. The title and the phrase come from the observed state rather
than from a hardcoded transition, so the same file reads correctly under any transition directory;
an unrecognised state falls back to naming the transition itself instead of inventing a sentence
that would be wrong.

Six details make the pair correct rather than merely short:

- **They find the real PulseAudio socket.** The trigger environment deliberately omits
  `PULSE_SERVER`, so the behaviour discovers accessible `/tmp/pulse-*/native` sockets instead
  of relying on the caller's default.
- **They find the real session bus.** The trigger environment is a whitelist, so it carries no
  `DBUS_SESSION_BUS_ADDRESS` and no `DISPLAY`. A bare `notify-send` therefore fails with
  `Cannot autolaunch D-Bus without X11 $DISPLAY`, which is why the behaviour discovers the bus
  itself: it checks `/run/user/<uid>/bus` and also reads `DBUS_SESSION_BUS_ADDRESS` from the
  processes of the desktop account. The second source is required, not redundant: a desktop
  session started by a display manager publishes an abstract socket such as
  `unix:abstract=/tmp/dbus-XXXXXXXX`, and `/run/user/<uid>/bus` does not exist on such a host.
- **They send as the desktop account when needed.** A session bus refuses a connection from
  another account, and the refusal is reported as `The connection is closed` rather than as a
  permission error. A root-owned trigger therefore drops only the notification subprocess to the
  desktop account's UID and primary group, so the popup reaches the session the operator is
  actually looking at.
- **They share one deadline.** The runner kills the whole process group after five seconds, so
  every behaviour draws from one four-second budget instead of each taking its own timeout. A slow
  audio service therefore cannot consume the time the popup needs.
- **Missing desktop support is not a failure.** Both behaviours exit 0 when `paplay`,
  `notify-send`, a sound file, an audio socket or a reachable session bus is unavailable, because a
  headless run has no operator to alert and a non-zero exit would only add a diagnostic row.
- **The popup is not a durable alert.** It is one notification with a 15-second expiry. It is
  not retried, it does not survive a closed session, and it is not a substitute for the
  Endpoint drive controller when the operator is away from the screen.

The transition check lives in the executor, not in a behaviour. `watch` already fires only on
`running -> waiting_input`, and the directory name is the second guard: a behaviour installed
under `running_to_waiting_input/` cannot run for any other transition, so it needs no condition of
its own. That is why a behaviour file can be reused under a different transition directory without
an edit.

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

To install the shipped executor instead of writing your own, point the default path at it with a
one-line bash wrapper. The wrapper keeps the shebang `bash` and the body a single executable
command:

```bash
mkdir -p "$HOME/.topsailai"
cat > "$HOME/.topsailai/topsailai-agent-cluster.on-state-change.trigger" <<'SCRIPT'
#!/bin/bash
exec /usr/bin/python3 /absolute/path/to/scripts/watch-trigger-exec.py
SCRIPT
chmod +x "$HOME/.topsailai/topsailai-agent-cluster.on-state-change.trigger"
```

Both paths in the wrapper must be absolute, because the runner starts the script in the
directory the CLI was launched from, not in the skill folder. `exec` replaces the shell with
the interpreter, so the runner sees one process instead of a shell waiting on a child, and a
timeout kills the interpreter directly rather than orphaning it.

The wrapper is required rather than optional: the default path is a single fixed file, so the
trigger must live there to be found by a bare `watch --trigger`. Keeping the logic in the skill
folder also means an edit to a behaviour takes effect on the next transition without reinstalling
the wrapper.

To add a reaction of your own, create the transition directory under the per-user root and drop
one executable file in it. No wrapper change is needed, because the executor already searches that
root:

```bash
mkdir -p "$HOME/.topsailai/topsailai-agent-cluster.triggers/running_to_waiting_input"
cat > "$HOME/.topsailai/topsailai-agent-cluster.triggers/running_to_waiting_input/log.sh" <<'SCRIPT'
#!/bin/bash
printf '%s %s\n' "$(date -Is)" "$AGENT_CLUSTER_SESSION_NAME" >> "$HOME/.topsailai/trigger.log"
SCRIPT
chmod +x "$HOME/.topsailai/topsailai-agent-cluster.triggers/running_to_waiting_input/log.sh"
```

Then inside the REPL:

```text
watch --trigger
watch -t
watch 2s --trigger=/path/to/another/script
watch 2s -t=/path/to/another/script
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
  notification should use the system audio service, the desktop notification service, or write
  to a file, never to stdout.
- **Calling `notify-send` without a session bus.** The trigger environment is a whitelist, so a
  bare `notify-send` fails with `Cannot autolaunch D-Bus without X11 $DISPLAY`. Discover the bus
  address first, and send as the account that owns the desktop session, because a session bus
  refuses a connection from another account.
- **Trusting a zero exit status as proof of a popup.** A script that cannot find `notify-send`,
  a bus, or a desktop account still exits 0 by design. Confirm the popup on screen, or capture
  the `org.freedesktop.Notifications.Notify` call, before claiming it works.
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
- [ ] The script uses the system audio service, the desktop notification service, or a file
      instead of printing to stdout, which the runner discards.
- [ ] The script quotes every payload value and never evaluates one.
- [ ] The script finishes well inside five seconds, or does its slow work in the background.
- [ ] The script tolerates `AGENT_CLUSTER_STALE=true` and `AGENT_CLUSTER_UNVERIFIED=true`
      when an alert on retained or unverified data would be wrong.
- [ ] The banner printed `trigger: <path> on running -> waiting_input`, not a note.
- [ ] The user was told the delay is the collection interval and that the mechanism ends
      with the terminal.
- [ ] A popup was observed on the operator's screen, not merely a zero exit status. A script
      that cannot reach the session bus still exits 0, so the exit status alone proves nothing.

## File Structure Description

- **bin/**: None. This skill documents an existing CLI capability and needs no executable.
- **scripts/**: `watch-trigger-exec.py` is the generic executor. It reads the transition from the
  payload, resolves the behaviour directory and runs every behaviour in it under one deadline. It
  contains no reaction and no transition-specific condition. `behaviours/` holds the reactions:
  `running_to_waiting_input/bell.py` plays one system bell sound and
  `running_to_waiting_input/notify.py` raises one desktop notification popup, while
  `behaviours/_desktop.py` is a shared helper that the executor skips because its name begins with
  an underscore. Install the executor by pointing a one-line bash wrapper at it from the default
  path; add a reaction by dropping one executable file into a transition directory.
- **references/**: None. The payload table and the execution contract above are complete.
- **assets/**: None.
