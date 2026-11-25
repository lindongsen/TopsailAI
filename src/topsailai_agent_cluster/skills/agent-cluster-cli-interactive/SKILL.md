---
name: agent-cluster-cli-interactive
description: Use when a human or agent drives Agent Cluster from the interactive REPL (`agent-cluster-cli -i`) — the surface where row numbers, `cd` scope navigation and bare commands work. Covers the three scopes and how to move between them, the row-number namespaces, the daily "what did the agent just do" workflow with `messages` and `logs`, the auto-tail that `cd` arms, the per-scope command matrix, the `start` launch wizard that resolves the launch profile itself, the `!` allowlisted-command prefix, the aliases and shorthands, and the identifier traps that make a correct-looking command fail.
version: 1.0.0
author: DawsonLin
license: Apache-2.0
metadata:
  tags: [agent-cluster, cli, interactive, repl, tui, scope, row-number]
  related_skills: [agent-cluster-cli-noninteractive, agent-cluster-watch-trigger]
---

# Agent Cluster CLI Interactive Mode

## Overview

`agent-cluster-cli` has two surfaces over one implementation. This skill covers the **interactive
REPL**, which is the surface a human uses to watch agents. The standalone surface is covered by
`agent-cluster-cli-noninteractive`.

The REPL is not a thin wrapper over the standalone commands. It adds three things the standalone
surface does not have, and every one of them changes how a command must be written:

| REPL-only capability | Consequence |
|---|---|
| **Scope** (workspace / endpoint / session) | A command's target may be omitted, because the scope already names it |
| **Row numbers** | A bare number selects a row from the last rendered table, so a number is never a session ID |
| **Bare commands** | `messages`, `logs`, `send`, `stop` work with no argument inside session scope |

The REPL is also the only surface where `--json` is refused. It renders for a human, so a script
must use the standalone surface instead.

## When to Use

Use this skill when the task is to:

- watch what agents are doing right now, and read a session's conversation or recent output;
- navigate the fleet by row number instead of by opaque identifier;
- start, resume, stop, clean or drive a session interactively;
- run one allowlisted command inside a session's working directory with `!`;
- understand why a command that works standalone fails in the REPL, or the reverse.

Do not use this skill for scripting, CI or `--json` parsing. Those belong to
`agent-cluster-cli-noninteractive`.

## Starting and Leaving

```text
agent-cluster-cli -i
agent-cluster-cli interactive
```

Both spellings start the REPL. A bare `agent-cluster-cli` with no command does **not**: it prints
`a command is required: list, show, logs, send, stop` and exits `2`.

The REPL refuses two global options, because neither has a meaning on a human surface:

| Invocation | Result |
|---|---|
| `agent-cluster-cli interactive --json` | `interactive does not support --json or --yes`, exit `2` |
| `agent-cluster-cli interactive --yes` | same refusal, exit `2` |
| `agent-cluster-cli interactive` with no terminal on stdin | `interactive mode requires a terminal on stdin`, exit `2` |

Leaving depends on the scope, and the difference is deliberate:

| Command | Outside workspace scope | In workspace scope |
|---|---|---|
| `quit`, `q` | return to workspace scope | leave interactive mode |
| `exit` | leave interactive mode | leave interactive mode |

`Ctrl+C` at the prompt exits with code `130`.

Every accepted input is recorded to `${HOME}/.topsailai/.topsailai_agent_cluster.history.jsonl` as
one JSON object per line, with `kind` set to `command` for a command line or `answer` for a
confirmation or wizard answer. Only REPL commands are recallable with Up/Down; answers are recorded
but never offered as commands, so a `y` or a `3` cannot become an accidental destructive
confirmation.

## The Scope Model

There are exactly three scopes, and the prompt always shows which one is active:

```text
workspace>                        the root scope; every endpoint and session
endpoint[ai-dev/ac.ai-dev]>       one machine, shown as hostname/endpoint-id
session[ai-dev/20261123131848]>   one session on one machine
```

Navigation is one command, `cd`, with these forms:

| Form | Effect |
|---|---|
| `cd` | return to workspace scope |
| `cd /` | return to workspace scope (the leading `/` is the command prefix, not a path) |
| `cd ..` | go up one scope |
| `cd <hostname>` | enter an endpoint; prompts when the hostname is ambiguous |
| `cd <hostname>/<id>` | enter a specific endpoint |
| `cd <session>` | enter a session inside the current endpoint |
| `cd <hostname>/<id>/<session>` | enter a session directly from workspace scope |
| `cd <row>` | enter the session shown at that row of the last rendered table |

**Entering a session arms a live tail.** `cd <session>` starts the same stream as `logs -f`, so the
operator sees the session's output immediately instead of typing a second command. The prompt shows
`log.follow> res_... (any key stops)` while it streams. **Any key stops it**, and that key is
consumed: typing `help` to stop the tail does not run `help`. Press a single throwaway key first,
then type the next command.

When the client cannot stream, the same `cd` prints one bounded snapshot instead, so the operator
still sees output rather than an empty screen.

`cd` refuses a session it cannot enter, and the refusal names the reason and the recovery:

```text
error: row 3 is unverified: the session record exists but no process holds it, so it cannot be
entered; run refresh to collect a fresh inventory, or use resume to resume it
```

That is correct behaviour, not a defect: entering a session means addressing a live process. `logs`
is the exception, because it reads persisted output and therefore works on an unverified row.

## The Daily Workflow: What Did the Agent Just Do

This is the most common use of the REPL, and it takes three steps.

```text
lb                  # narrow table: NO, SESSION_NAME, MESSAGES, ENDPOINT
cd 1                # enter the session; the live tail starts immediately
messages            # read the conversation of the session you are in
```

`lb` is the shorthand for `list --brief`. The narrow table is the right starting point because it
fits a normal terminal and still shows the two columns that answer "is it working": `MESSAGES`
(inbound/outbound counts) and `ENDPOINT`.

Once inside a session, both reads take no argument:

| Command | Reads | Ordering |
|---|---|---|
| `messages` | the persisted conversation | oldest first, so the newest turn is at the **bottom** |
| `logs` | the persisted output | trailing lines, bounded by `-n` |

`messages` is persisted provider data, so a **stopped** session can still be read. That is why it is
the reliable way to learn what an agent did after it has already finished.

Because `messages` prints oldest first, the newest turn is the last block. To read only the tail,
bound the output rather than scrolling:

```text
messages -c 2000        # cap each message body at 2000 characters
messages -t 500         # cap each message at 500 model tokens
```

Both bounds apply together, so a body is shortened by whichever is tighter. The header counts still
describe the whole message, so a shortened body is never mistaken for a short one.

`logs -n <lines>` bounds the trailing lines. `logs -f` streams until a key is pressed, which is the
same stream `cd` already armed.

## Row Numbers

A row number is a **position in the most recently rendered table**, not an identity. It is rebound
every time a table is rendered, so a row number is only valid until the next `list`, `refresh`,
`history` or `watch` tick.

| Fact | Consequence |
|---|---|
| The number comes from the last rendered table | Re-render before reusing a number you read earlier |
| `list` numbers every endpoint's sessions in one sequence | A row number already names its machine, so no `cd` is needed |
| `history` numbers its own rows separately | A history row number is not a list row number |
| A row number is not durable | Never store one; store the session ID instead |

Commands that accept a row number: `cd`, `show`, `info`, `logs`, `messages`, `stop`, `drive`,
`clean`, `resume`, `model`, `project remove`.

## The Identifier Trap That Breaks the Daily Workflow

`messages` and `logs` resolve a bare token differently, and the difference is not symmetric.

| Command | A bare all-digit token is | A non-numeric token is |
|---|---|---|
| `logs` | tried as a row number, then **retried as a provider session ID** | resolved as a provider session ID |
| `messages` | **always** a row number | resolved as a provider session ID |

So a provider session ID that happens to be all digits — which is the common TopsailAI form, such as
`20261123131848` — cannot be passed to `messages` in workspace scope:

```text
workspace> messages 20261123131848 -c 200
error: row 20261123131848 is out of range; valid rows are 1-14
```

The same token works for `logs`, and it works for `messages` once a scope names the machine:

```text
workspace> logs 20261123131848 -n 2          # works: retried as a session ID
workspace> cd 2                              # enter the session by row
session[ai-dev/wa-378ec90c6615]> messages    # works: the scope names the target
```

Three ways to avoid the trap, in order of preference:

1. **Use the row number.** `cd 1` then bare `messages`. This is the intended workflow and needs no
   identifier at all.
2. **Enter the endpoint first.** `cd ai-dev` then `messages 20261123131848`, because endpoint scope
   resolves the token as a session ID.
3. **Use the standalone surface** when a script must pass an identifier:
   `agent-cluster-cli messages <endpoint> <provider-session-id>`.

A non-numeric provider session ID such as `wa-378ec90c6615` is unambiguous and works in every scope.

## Per-Scope Command Matrix

Availability is fixed by one matrix, so a command that is refused in a scope is refused for a
reason. `help` inside the REPL prints the commands for the current scope.

| Command | workspace | endpoint | session |
|---|---|---|---|
| `list` | yes | yes | yes |
| `endpoints` | yes | — | — |
| `cd` | yes | yes | yes |
| `show` | yes | yes | yes |
| `info` | yes | yes | yes |
| `start` | yes | yes | — |
| `resume` | yes | yes | — |
| `stop` | yes | yes | yes |
| `clean` | yes | yes | — |
| `drive` | yes | yes | yes |
| `logs` | yes | yes | yes |
| `messages` | yes | yes | yes |
| `model` | yes | yes | yes |
| `status` | yes | yes | yes |
| `refresh` | yes | yes | yes |
| `watch` | yes | yes | — |
| `history` | yes | yes | — |
| `project` | yes | yes | — |
| `send` | — | — | yes |
| `btw` | — | — | yes |
| `interrupt` | — | — | yes |
| `ctl` | — | — | yes |
| `help` | yes | yes | yes |
| `quit` | yes | yes | yes |
| `exit` | yes | yes | yes |

Two absences are deliberate and worth knowing:

- **`resume` is not available in session scope.** Resume authorizes on a *proven absence* of a live
  process, while session scope requires a live generation. The two conditions are mutually
  exclusive, so the command cannot exist there.
- **`send`, `btw`, `interrupt` and `ctl` are session-only.** They address a live process, so a scope
  must name one.

## Session-Scope Commands

Inside a session, the target is the scope, so these take no argument:

| Command | Meaning |
|---|---|
| `messages` | the current session's conversation |
| `logs` | the current session's output |
| `send <text>` | submit literal input to the agent |
| `btw <text>` | queue side context, distinct from normal input |
| `interrupt soft\|hard [message]` | interrupt the current turn |
| `ctl <action> [json]` | invoke one advertised provider control action |
| `drive start\|stop\|status` | manage the session driver; `drive stop` leaves the agent running |
| `stop` | stop the session |
| `status` | the last command submitted in this CLI, otherwise the current session state |

`send` and `btw` take **no options at all**, because the rest of the line is literal content. A
`send --help` therefore sends the text `--help` to the agent. Use `help send` for help.

A bare `send` asks for confirmation before submitting. Unrecognized text in session scope is also
offered as a send action, so a typo becomes a question rather than an error:

```text
>>> send the text above as a message? [y/N]
```

Answer `n` unless the text really is what you meant to send.

## Launching an Agent: The `start` Wizard

`start` is available in workspace and endpoint scope, and it is a **wizard**, not a one-line
command. It asks for the two things it cannot infer — the working folder and the task — and it
resolves the launch profile itself, so the operator never types a profile ID or revision.

```text
endpoint[topsail/ac.topsail]> start
1. data-hub (/qrew/data-hub)
2. host-dev (/work/hosts/host-dev)
...
12. topsailai_agent_cluster (/TopsailAI/src/topsailai_agent_cluster)
Choose a project number or enter a folder; empty/cancel cancels.
start.folder> 12
start.folder> 12 (topsailai_agent_cluster (/TopsailAI/src/topsailai_agent_cluster))
start.task> summarize the open issues
```

The wizard has exactly two prompts, and each accepts one answer:

| Prompt | Accepts | Notes |
|---|---|---|
| `start.folder>` | a project number from the printed list, or a literal folder path | The list is the endpoint's **registered projects**, not a filesystem scan. A folder outside that list must be typed as a path. An empty answer cancels. |
| `start.task>` | one line of task text | An empty answer does **not** cancel; it switches to multi-line mode, described below. |

The project list is numbered per launch, so a number is a position in that list, not a project
identity. Re-read the list before reusing a number, exactly as with row numbers.

**An empty task switches to multi-line input.** The wizard prints
`Enter task; finish with a standalone EOF line or Ctrl+D` and changes the prompt to `task>`. This is
the same multi-line reader the standalone `--task`-less form uses. Finish with a standalone `EOF`
line or `Ctrl+D`; the terminator is never part of the task. An empty multi-line task is rejected
rather than submitted as nothing.

**`Ctrl+C` cancels the wizard** and returns to the scope it started from, printing `interrupted`.
Nothing is submitted, so an abandoned wizard leaves no session behind.

After a completed start, the REPL forces one collection for the endpoint and then arms the same live
tail as `logs -f` on the session that appeared, so the new agent is watched without typing `logf`.
The tail is armed **after** the collection because the launched session's generation is minted by
it. No tail is armed when no session appeared, when more than one appeared, when the generation is
unverified, or when the client cannot stream; the reason is reported as a diagnostic instead.

The wizard prints `session submitted but not yet visible; the next collection will show it`. That
line is **not** proof of success. Confirm the launch by reading the session back:

```text
lb                  # the new row appears after the collection
cd <row>            # enter it; the tail shows the agent starting
messages            # the task text you typed is the first user message
```

A new row alone does not prove the task arrived, and the auto-generated session name can differ from
the task wording, so read `messages` rather than trusting the name.

**The wizard is the supported way to launch.** The standalone surface requires `--profile` and
`--profile-revision`, and no CLI command lists their values, so a script cannot discover them. When
a launch must be automated, drive this wizard through a terminal multiplexer rather than guessing a
profile ID.

## The `!` Allowlisted Command Prefix

`!` runs one allowlisted command through the Endpoint's `command.exec` operation, in the session's
working directory. It is the REPL spelling of the standalone `exec` command.

```text
session[ai-dev/20261123131848]> ! ls -1 | head -3
endpoint[ai-dev]> ! git status --short
```

It requires a session or endpoint scope, because the working directory comes from the target:

```text
workspace> !
error: invalid arguments
usage: !<program> [arguments...] requires a session or endpoint scope; use cd <number> to select a
session row, or cd <endpoint-id> to run the command on an endpoint
```

The argv is tokenized by the REPL, not by a shell, and it is matched against an Endpoint-global
allowlist. A command outside the allowlist is refused rather than run. `exec` is not a REPL command
name; `!` is the only spelling.

## Aliases and Shorthands

| Spelling | Expands to |
|---|---|
| `?` | `help` |
| `l` | `list` |
| `m` | `model` |
| `q` | `quit` |
| `r` | `refresh` |
| `w` | `watch` |
| `lf` | `list --full` |
| `lb` | `list --brief` |
| `logf` | `logs -f` |

A leading `/` on the command word is optional, so `/send` and `send` are the same command. It never
changes argument text, and `cd /` still means the workspace root.

`lf` and `lb` are the two shorthands worth memorising: `lb` is the narrow table that fits a terminal,
and `lf` disables truncation when a long cell must be read in full.

## Common Pitfalls

- **Typing a command to stop the auto-tail.** `cd <session>` arms a stream, and the next keypress
  only stops it. Press a throwaway key, then type the command.
- **Passing an all-digit session ID to `messages` in workspace scope.** It is read as a row number
  and fails with `row ... is out of range`. Use the row number, enter the endpoint first, or use the
  standalone surface.
- **Reusing a row number after a re-render.** A row number is a position, not an identity. Re-render
  before reusing one, and never store one.
- **Expecting `--json` to work.** The REPL refuses it. Use the standalone surface for anything a
  script must parse.
- **Expecting `resume` inside a session.** It is workspace and endpoint only, because resume needs a
  proven absence while session scope needs a live generation.
- **Assuming `cd` works on every row.** An unverified row cannot be entered. `logs` and `messages`
  still read it, because they address persisted data rather than a live process.
- **Assuming `drive stop` stops the agent.** A driver injects input on the operator's behalf; it is
  not the agent.
- **Assuming `clean` deleted something.** It removes only provider-owned expired artifacts, and the
  provider reports `nothing_to_delete`, `preview`, `partial` or `deleted`. Read the outcome.
- **Assuming `quit` always quits.** Outside workspace scope it only goes up one scope. Use `exit` to
  leave from anywhere.
- **Sending `--help` to an agent.** `send` and `btw` treat the rest of the line as literal text, so
  `send --help` sends the word `--help`. Use `help send`.
- **Treating `start` as a one-line command.** It is a wizard with two prompts. An empty answer at
  `start.folder>` cancels, but an empty answer at `start.task>` switches to multi-line input instead,
  so a stray Enter does not abort the launch.
- **Trusting `session submitted but not yet visible`.** That line is not proof the launch worked.
  Read the session back with `messages` to confirm the task text arrived, because the auto-generated
  session name can differ from the task wording.

## Verification Checklist

- [ ] The prompt was read to confirm the active scope before omitting a target.
- [ ] A row number was taken from the most recently rendered table, and not reused after a re-render.
- [ ] `messages` was given a row number or a non-numeric session ID, never an all-digit session ID in
      workspace scope.
- [ ] The auto-tail armed by `cd` was stopped with a throwaway key before the next command.
- [ ] `send` and `btw` payloads were quoted as literal text, and `help <command>` was used for help.
- [ ] `!` was used only in session or endpoint scope, with an allowlisted program.
- [ ] `exit` was used to leave from a non-workspace scope.
- [ ] Anything a script must parse was run on the standalone surface instead of the REPL.
- [ ] A launch was confirmed by reading `messages`, not by trusting the wizard's
      `session submitted but not yet visible` line.
- [ ] The `start` project number was taken from the list printed by that launch, not reused from an
      earlier launch.

## File Structure Description

- **bin/**: None. This skill documents the installed `agent-cluster-cli` binary and ships no
  executable of its own.
- **scripts/**: None. Every command is typed at the REPL prompt.
- **references/**: None. The scope model, command matrix, row-number rules and identifier traps are
  complete in this document.
- **assets/**: None.
