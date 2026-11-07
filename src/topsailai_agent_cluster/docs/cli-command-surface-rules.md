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

## Audit

The table records the verified state of every command. Each standalone entry was
executed against an unreachable Server, so the observed message proves the command
was dispatched rather than rejected as unknown.

| Command | Standalone spelling | Interactive spelling | Compliant |
|---|---|---|---|
| `list` | `list` | `list` | yes |
| `refresh` | `refresh` | `refresh`, `r` | yes |
| `endpoints` | `endpoints` | `endpoints` | yes |
| `show` | `show` | `show` | yes |
| `logs` | `logs` | `logs` | yes |
| `status` | `status` | `status` | yes |
| `send` | `send` | `send` | yes |
| `context.inject` | `btw`, `inject` | `inject`, `btw` | yes |
| `execution.interrupt` | `control` | `interrupt`, `control` | yes |
| `agent.start` | `start` | `start` | yes |
| `agent.resume` | `resume` | `resume` | yes |
| `agent.stop` | `stop` | `stop` | yes |
| `agent.drive.start` | `drive start` | `drive start` | yes |
| `agent.drive.stop` | `drive stop` | `drive stop` | yes |
| `drive status` | `drive status` | `drive status`, `drive` | yes |
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

`cd` and `quit` navigate a session that only exists inside the interactive loop, so
they have no standalone meaning and are not gaps.

Removed spellings must stay rejected rather than silently reinterpreted: `table`
returns an explicit removal message pointing at `list --clean`, and `use` is
rejected as unknown in favour of `cd`.

Every interactive spelling in the table also accepts the optional `/` command-word
prefix described below, so the table lists command words rather than every accepted
input form.

## Planned additions: provider control and allowlisted command execution

Two command families are designed but not yet implemented. They are recorded here so
the surface contract is fixed before code exists. They MUST NOT be added to the audit
table above until each one is executable and verified, because that table records
observed state, not intent.

| Command | Standalone spelling | Interactive spelling | Status |
|---|---|---|---|
| `ctl.<action>` | `ctl <action> [--payload JSON]` | `ctl`, `ctl <action>`, `ctl <action> <json>` | planned |
| `command.exec` | `exec <session> -- <argv...>` | `!<argv...>` | planned |

`ctl` follows the non-interactive-first rule directly. The standalone form carries the
action name and an explicit payload; the interactive form is a convenience layer that
prompts for the action when it is omitted. The prompt MUST render its action list from
the advertised capabilities rather than from a hardcoded list, so it cannot offer an
action the Endpoint does not support. A bare `ctl` in non-interactive mode is a usage
error, not a prompt.

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
