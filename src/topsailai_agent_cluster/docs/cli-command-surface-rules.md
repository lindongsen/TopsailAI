---
maintainer: AI
author: DawsonLin
status: active
created: 2026-11-07
---

# CLI command surface rules

## Non-interactive first

Every command MUST be usable non-interactively before an interactive form is added.

The non-interactive surface is the contract: it is what scripts, CI jobs and other
programs can call, and it is the only surface that can be verified without a terminal.
An interactive form is a convenience layer over the same behaviour, never the place
where behaviour is first defined.

Consequences for a new command:

- Implement the standalone entry point first, with an explicit syntax, argument
  validation and a machine-readable `--json` mode.
- Reuse the same runner method from both surfaces so the two cannot diverge.
- Add the command to the standalone help order and to the dispatch switch in the
  same change, so an advertised command is always executable.
- Only then add the interactive spelling, scope rules and prompt-driven flow.
- A command that exists only interactively is a defect, not a design choice.

## Why the order matters

- A non-interactive-first command can be tested end to end without a terminal, so
  its behaviour is pinned by automated tests rather than by manual keystrokes.
- Automation cannot drive a prompt, so an interactive-only command is unreachable
  for scripts and forces callers to scrape terminal output.
- Defining behaviour once in the runner and exposing it twice prevents the two
  surfaces from drifting into different semantics.

## Failure semantics

A non-interactive command MUST NOT silently degrade to a weaker behaviour.

- If the stronger behaviour is unavailable, return an explicit error instead of
  returning cached or partial data under the same command name.
- A command named after an action must perform that action or fail; it must not
  quietly become a read of the previous result.
- Interactive surfaces may degrade with a visible diagnostic, because a human is
  present to read it. Non-interactive surfaces must fail, because no human is.

## Automatic follow-up steps

An interactive command MAY perform bounded follow-up steps after its own action
has already succeeded, so the operator does not have to type a second command to
see the effect.

- A follow-up step runs only after the primary action returned successfully. A
  rejected, cancelled or failed action performs no follow-up.
- A follow-up step never changes the outcome of the primary action. Its failure is
  reported as a diagnostic that names the primary action, and the prompt stays
  usable, because the durable receipt of the primary action is already the
  authority for what happened.
- A follow-up step gets its own bounded budget. It must not reuse a deadline the
  primary action may already have exhausted.
- A follow-up step is interactive-only. The standalone surface keeps one command
  per action, so a script never receives extra output it did not ask for.
- `send` renders one bounded output snapshot and then forces one collection for the
  selected endpoint and revalidates only the selected session, so a later `list`
  reads a newer persisted document. The snapshot runs first because it uses the
  generation validated before the send, while a refresh can replace that
  generation.

## Audit

The table records the verified state of every command. Each standalone entry was
executed against an unreachable Server, so the observed message proves the command
was dispatched rather than rejected as unknown.

| Command | Standalone spelling | Interactive spelling | Compliant |
|---|---|---|---|
| `list` | `list` | `list`, `l` | yes |
| `refresh` | `refresh` | `refresh`, `r` | yes |
| `endpoints` | `endpoints` | `endpoints` | yes |
| `show` | `show` | `show` | yes |
| `info` | `info` | `info` | yes |
| `logs` | `logs` | `logs` | yes |
| `status` | `status` | `status` | yes |
| `send` | `send` | `send`, `>` | yes |
| `context.inject` | `btw`, `inject` | `inject`, `btw` | yes |
| `execution.interrupt` | `control` | `interrupt`, `control` | yes |
| `ctl.<action>` | `ctl` | `ctl` | yes |
| `command.exec` | `exec` | `!<argv...>` | yes |
| `agent.start` | `start` | `start` | yes |
| `agent.resume` | `resume` | `resume` | yes |
| `agent.stop` | `stop` | `stop` | yes |
| `agent.drive.start` | `drive start` | `drive start` | yes |
| `agent.drive.stop` | `drive stop` | `drive stop` | yes |
| `drive status` | `drive status` | `drive status`, `drive` | yes |
| `watch` | not applicable | `watch`, `w` | yes |
| `help` | `help` | `help`, `?` | yes |
| `cd` | not applicable | `cd` | not applicable |
| `quit` | not applicable | `quit`, `exit`, `q` | not applicable |

Two spellings are intentionally asymmetric:

- `interrupt` is interactive-only as a spelling, but its behaviour is reachable
  standalone through `control`, which maps to the same `execution.interrupt`
  operation. The standalone surface therefore covers the behaviour even though it
  does not accept the interactive word.
- `inject` is accepted standalone as an alias of `btw`; both map to
  `context.inject`.

The `>` prefix is interactive-only and is deliberately absent from the standalone
surface, where `>` is a shell redirect. It is resolved before tokenisation, so
`>hello world` and `> hello world` both send `hello world`. Because the prefix is
disjoint from every command word, a message can never be read as a command and a
typo can never be read as a message; an unprefixed unknown word still returns the
unknown-command diagnostic. The alias keeps the confirmation gate and the
session-only scope rule of `send`.

The `l` alias is interactive-only and resolves to `list` through the same alias
registry as `r` and `q`. It is absent from the standalone surface, which accepts
only the canonical `list` spelling. Because `canonicalCommandName` runs before the
dispatch switch, `l` inherits `list`'s arguments, scope availability and usage
diagnostics unchanged, and it does not shadow the longer `logs` spelling.

`cd` and `quit` navigate a session that only exists inside the interactive loop, so
they have no standalone meaning and are not gaps.

`watch` is interactive-only for a different reason, and it is not a gap either. It
adds no behaviour: every tick performs exactly `list` (re-read the persisted
projection) or `refresh` (forced collection), and both of those are fully
reachable standalone with `--json`. What `watch` adds is a presentation cadence —
re-rendering a table on a timer while a prompt sits idle, and stopping on the first
keypress. A non-interactive caller that wants repeated reads writes its own loop
around `list`, which is strictly more expressive because it controls the exit
condition and the output format. The loop therefore has no standalone contract to
pin, and inventing one would duplicate `list` behind a second name.

Two consequences follow, and both are enforced:

- `watch` rejects `--json` in interactive mode instead of silently ignoring it, so
  a caller cannot believe it received a machine-readable stream.
- The standalone surface rejects `watch` as an unknown command rather than
  accepting it and degrading to a single read, which would violate the
  failure-semantics rule above.

The behaviour `watch` drives is pinned by the standalone tests for `list` and
`refresh`; the loop itself is pinned by the editor-level tests that inject a tick
channel, so no part of it depends on manual keystrokes for verification.

Removed spellings must stay rejected rather than silently reinterpreted: `table`
returns an explicit removal message pointing at `list --clean`, and `use` is
rejected as unknown in favour of `cd`.

Every interactive spelling in the table also accepts the optional `/` command-word
prefix described below, so the table lists command words rather than every accepted
input form.

## Provider control and allowlisted command execution

Both families are implemented and appear in the audit table above. The verified
standalone behaviour, executed against an unreachable Server so the message proves
dispatch rather than rejection:

```text
$ agent-cluster-cli ctl ep-1 res-1 heartbeat
confirmation required for ctl heartbeat target=res-1 parameters={}; rerun with --yes

$ agent-cluster-cli exec ep-1 res-1 gen-1 -- git status
confirmation required for exec target=res-1 parameters={"argv":["git","status"]}; rerun with --yes

$ agent-cluster-cli ctl ep-1 res-1
usage: ctl <endpoint-id> <resource-id> <action> [json] [generation]

$ agent-cluster-cli exec ep-1 res-1 gen-1
usage: exec <endpoint-id> <resource-id> <generation> -- <argv...>
```

`ctl` follows the non-interactive-first rule directly. The standalone form carries the
action name and an explicit payload; the interactive form is a convenience layer that
prompts for the action when it is omitted. The prompt renders its action list from the
advertised capabilities rather than from a hardcoded list, so it cannot offer an action
the Endpoint does not support. A bare `ctl` in non-interactive mode is a usage error,
not a prompt, as the fourth command above shows.

`!` is an input-prefix form, not a command word. It is recognised before the command
word is split, so `!git status` never reaches the dispatcher as a command named `!git`.
Its behaviour is reachable non-interactively through `exec`, which is the contract
surface.

This is deliberately NOT an exception like `cd` and `quit`. Those navigate state that
exists only inside the interactive loop, so they have no standalone meaning. `!`
performs a remote operation that is fully meaningful without a terminal, so declaring
it an exception would leave its behaviour unpinned by automated tests and reachable
only by scraping terminal output.

Both families are one-shot: a single bounded snapshot carrying its observation time,
never a stream, a follow or a durable subscription. Neither may silently degrade; an
unavailable capability returns an explicit error rather than cached or partial data.

Two properties are worth stating because they are easy to get wrong:

- `exec` takes its argv array from the shell's own word splitting and never
  re-tokenizes it. Re-splitting a string at the Endpoint would reintroduce the shell
  semantics the allowlist cannot reason about, so `exec ep res gen -- ls -la` passes
  `-la` as an argument rather than as a misplaced option.
- The allowlist decision belongs to the Endpoint policy hook, not to the client. A
  denied command therefore surfaces as a durable `rejected` receipt with
  `policy_denied`, which is the same evidence an operator sees for any other
  admission refusal. The client never decides policy locally.

## Command-word prefix

The interactive REPL accepts an optional `/` before the command word, so `send hi`
and `/send hi` are the same command. The prefix is a form, not a command word: it is
stripped from the first token only, before alias resolution and scope checks.

- Only the command word is affected. Argument text stays literal, so `send /help`
  sends the text `/help` and never opens help.
- A bare `/` is still an unknown command. It is not silently treated as an empty
  line, because swallowing input hides a mistake instead of reporting it.
- `cd /` is unchanged: `/` in argument position still means the workspace root. The
  two meanings never collide because the prefix is recognised only at the command
  word.
- The prefix is optional in both directions. Bare command words remain valid, so
  existing scripts, recorded input and muscle memory keep working.
- Completion and `help <command>` accept the prefix too, so `/se` completes and
  `help /send` resolves like `help send`. A prefix that worked for dispatch but not
  for completion would look unreliable.
- The non-interactive surface does not accept `/`. There the first argument is a
  command word and a leading `/` is a path, so accepting it would change path
  semantics.
- The wizard is not a REPL. Answers typed during `start` are literal values, so a
  `/start` answer stays a folder or task value and is never dispatched as a command.

`/` and `!` are the two registered command-word prefix forms. `!` is recognised
before the command word is split because it carries an argv tail; `/` is stripped
from the command word because it carries nothing. Neither is an alias entry: an
alias maps one word to another, while a prefix changes the accepted spelling of
every command at once.

## Unrecognized input in session scope

In session scope the common mistake is typing a message without the command word.
Such a line is offered as a `send` instead of only being rejected:

```text
session[ai-dev/fixture-session]> hello world
unknown command hello; send hello world as a message? [y/N]
```

- The offer applies only in session scope. `send` is unavailable in workspace and
  endpoint scope, so an offer there could never be honoured and the plain
  unknown-command diagnostic is kept.
- The whole literal line is the message, not the words after the unrecognized
  word. The operator typed one piece of text, and dropping its first word would
  silently change what is sent.
- Accepting runs the normal `send` flow with that text and does not ask the send
  confirmation again, because the offer already named the exact text and action.
  Declining, an empty answer, a partial answer or an unreadable answer keeps the
  unknown-command diagnostic, so a typo is never swallowed and no mutating action
  is inferred from silence.
- The offer is a question, not a capability claim. The `send` flow keeps the
  authoritative capability preflight, so an unsupported operation is still
  reported precisely and the capability decision has one implementation.
- A payload the `send` command itself rejects, such as a `--json` flag payload, is
  rejected before the question is asked, so the offer never promises a send that
  cannot be admitted.
- The offer is interactive-only. A non-interactive caller passes the command word
  explicitly, so no prompt can appear where no human is present.

## Global presentation flags

Presentation flags are global: they are parsed before the command word and apply
to every table command and to the interactive REPL started by the same
invocation. They never change query semantics or the data returned by the API.

| Flag | Effect |
|---|---|
| `--no-color` | Disable terminal colors |
| `--no-truncate` | Disable table truncation; a narrow terminal wraps instead of clipping |

`--no-truncate` is the switch for a small terminal. Truncation stays the default,
because a bounded table is what keeps a wide fleet readable. With the switch set,
the renderer ignores both the terminal width bound and the per-column caps, so a
long session ID, endpoint ID, hostname or capability revision is printed in full
and the terminal wraps it. The switch does not weaken sanitization: terminal
control sequences in provider data are still stripped.

`PROJECT_WORKSPACE` is clipped from the left, so an over-wide path keeps its
identifying tail (`...topsailai_agent_cluster/internal/tui`) instead of a prefix
that every sibling path shares. Every other column keeps its head. The rule
applies to both the framed and the narrow layout, and `--no-truncate` still
prints the complete path.

The output boundary owns the policy. The CLI writer reports a `TableLayout` of
width plus truncation state, so every render path inherits the switch without
threading a new parameter through each command, and the interactive prompt editor
keeps the real terminal width as its editing budget.

## Verification

- The standalone help order and the dispatch switch must list the same commands.
- A test must prove each advertised syntax is executable, not merely printed.
- A test must prove a command that cannot perform its action returns an error
  instead of cached data.
- A new command must be added to the help order, the dispatch switch and the
  availability matrix in the same change.
