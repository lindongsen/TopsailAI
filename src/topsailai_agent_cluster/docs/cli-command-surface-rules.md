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
| `agent.start` | `start` | `start` | yes |
| `agent.resume` | `resume` | `resume` | yes |
| `agent.stop` | `stop` | `stop` | yes |
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

Removed spellings must stay rejected rather than silently reinterpreted: `table`
returns an explicit removal message pointing at `list --clean`, and `use` is
rejected as unknown in favour of `cd`.

## Verification

- The standalone help order and the dispatch switch must list the same commands.
- A test must prove each advertised syntax is executable, not merely printed.
- A test must prove a command that cannot perform its action returns an error
  instead of cached data.
- A new command must be added to the help order, the dispatch switch and the
  availability matrix in the same change.
