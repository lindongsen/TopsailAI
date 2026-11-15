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

## Interactive usability is mandatory

Every interactive CLI behaviour MUST be designed for operator ease of use. The interactive surface is
not a literal copy of the standalone grammar: it is a human-facing convenience layer over the same
contract, and it should remove avoidable typing, lookup and repetition while preserving the operation's
meaning and safety.

Consequences for every interactive command:

- Accept the identifiers an operator can readily see and use in the current context. When a table has
  just rendered stable row numbers, accept those row numbers as well as the underlying resource or
  Session identifier. Resolve a row through the latest rendered table; never put the row number on the
  wire or treat it as durable identity.
- Use the current scope to supply information the operator already selected. Endpoint scope should not
  require the Endpoint again, and session scope should not require the selected Session again. Reject a
  conflicting explicit value instead of silently changing scope.
- Prefer short, discoverable spellings for frequent actions, but rewrite them into the canonical grammar
  before parsing rather than creating a second implementation. Help, completion, examples and errors
  must advertise the convenient form consistently.
- Use prompts, numbered choices and sensible context-derived defaults when they reduce memorization.
  Omission is allowed only when the remaining choice is unambiguous; otherwise show the available choices
  or return an actionable error that tells the operator exactly what to enter.
- Avoid making the operator repeat a successful action merely to observe its effect. A bounded automatic
  refresh, table render or live-tail handoff may follow the action under the automatic follow-up rules.
- Preserve safety boundaries. Convenience must never weaken exact target selection, authorization,
  destructive confirmation, generation checks, capability checks or explicit failure reporting. When
  convenience and certainty conflict, fail closed and explain the shortest safe next step.
- Test the composed interactive path, not only its parser helpers: drive the real command entry point and
  assert the rendered result, prompt behaviour, selected target and zero-submission paths.

`clean <row|session>` is the reference selector pattern. A visible row is the fastest input, while a
literal Session identifier remains available when no table is present. A numeric token that does not
name a current row may be retried as a numeric provider Session identifier, but an ambiguous match is
rejected rather than guessed.

## Interactive input history

Every accepted nonblank input submitted through the interactive CLI is persisted in the operator's
JSONL history file. This includes REPL command lines, confirmation answers, guided choices and wizard
answers. Rejected or overflowed input is not a submission and blank input is omitted as noise.

Recording and recall are separate behaviours:

- REPL command lines are stored as `kind=command` and may be recalled with Up/Down, including after a
  later CLI process loads the same file.
- Prompt and wizard answers are stored as `kind=answer` and never enter recall. An answer such as `y`
  or `3` is meaningful only beside the prompt that asked for it, and recalling it could repeat an
  unintended choice or destructive confirmation.
- History persistence is a convenience, not a startup dependency. Read, parse, append or rotation
  failures are diagnosed, while the interactive CLI continues with the history still available in
  memory where possible.

The path, bounded load count, active-file size and retained backup count are configured by the
`AGENT_CLUSTER_HISTORY_*` variables documented in `docs/Environment_Variables.md`. The default file is
private (`0600`), size-rotated and loaded from a bounded tail rather than read in full.

## Failure semantics

A non-interactive command MUST NOT silently degrade to a weaker behaviour.

- If the stronger behaviour is unavailable, return an explicit error instead of
  returning cached or partial data under the same command name.
- A command named after an action must perform that action or fail; it must not
  quietly become a read of the previous result.
- Interactive surfaces may degrade with a visible diagnostic, because a human is
  present to read it. Non-interactive surfaces must fail, because no human is.

## Receipt rendering and the provider return document

A command result has two parts: this service's own durable receipt and the
provider's own return document. Both surfaces render them through one shared
renderer, so they cannot disagree about which fields are shown or whether the
provider document is escaped.

- The default output of an action command is the rendered receipt: the status
  label, the durable receipt fields, then the provider document as its own
  `provider_response:` section.
- The provider document is rendered as readable text. It is opaque provider
  evidence, so it is never reinterpreted as a provider success claim, but it is
  also not dumped as one line of JSON punctuation: a first-level value that is
  itself an object or a list is indented under its key, so a nested answer stays
  legible. The rendering is display-only; the stored document and the `--json`
  envelope keep the provider's original bytes.
- A document that is not one JSON value is printed unchanged. A failed invocation
  carries the provider's stderr and a truncated answer is invalid JSON by
  construction, so re-encoding either would drop the only diagnostic available.
- `--json` keeps the machine envelope, because a script parses that document. The
  envelope carries the same document in `provider_response`, so no evidence is
  lost by choosing the machine form.
- An absent document prints no section, so a provider that returns nothing keeps
  the previous output unchanged.
- A truncated document is always labelled with `provider_response_truncated`, so a
  shortened provider answer is never presented as complete evidence.

The rule exists because the two surfaces previously disagreed: the interactive
REPL rendered the receipt while the standalone command emitted the envelope for
every invocation, so the same `btw` result appeared as a rendered section in one
surface and as an escaped JSON string in the other. Sharing one renderer makes
that divergence structurally impossible rather than dependent on someone
remembering to change both.

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
- Four interactive steps arm a live tail: entering a session, `send`, `btw` and
  `start`. They share one arm-or-snapshot helper, so the four cannot drift into
  four copies of the capability check, the announcement or the degradation
  wording. `interrupt` is deliberately excluded, because stopping a turn is not a
  reason to expect new output.
- The tail's trailing line count is a per-step budget, not one global value.
  Entering a session and `start` read the REPL budget, because the operator is
  looking at a session for the first time and wants its recent context. `send` and
  `btw` read 10 lines, so they behave as `logs -n 10 -f`: the operator just acted
  on a session they were already reading, so the tail only has to show the effect
  of that action. The two budgets meet in one resolver, so a stream and the
  snapshot that substitutes for it can never read a different amount.
- The 10-line budget is deliberately below the REPL minimum of 100. It is a fixed
  budget for one automatic step, so it must not pass through the startup-budget
  clamp, which would silently turn 10 into 100 and make the step read the whole
  REPL budget again.
- Entering a session arms the tail for the identity the transition already
  validated, so the entry costs one output read and no repeated discovery. It
  degrades to one bounded snapshot, with a diagnostic that says so, when the client
  cannot stream or the input mode cannot observe a keypress.
- `btw` arms the tail after its durable receipt, because injected context usually
  makes the agent keep working and the operator should not have to type `logs` to
  see the effect. It reads 10 trailing lines, so it behaves as `logs -n 10 -f`.
- `send` arms the same 10-line tail as `logs -n 10 -f` and then forces one
  collection for the selected endpoint and revalidates only the selected session,
  so a later `list` reads a newer persisted document. The tail is armed first
  because it binds the generation validated before the send, while a refresh can
  replace that generation; the stream itself opens on the next prompt, through the
  same seam that starts an explicit `logs -f`. A one-shot snapshot is not used
  here, because it stops at the moment it was read while the agent keeps writing.
- `start` arms the same live tail as `logs -f` for the session it launched, so the
  operator watches the new session without typing `logf`. The tail is armed
  **after** the post-start collection, and that order is the opposite of `send` on
  purpose. A `send` addresses a session that already exists, so it binds the
  generation validated before the action. A `start` creates the session, so its
  cluster identity and generation are minted by the collection itself; arming
  earlier would bind an empty generation, which the Endpoint rejects with
  `generation_required`.
- The launched session is identified by diffing the committed document against the
  pre-collection baseline, never by parsing the receipt. The receipt's provider
  document is opaque, and the Server never parses it, so the TUI must not invent a
  second interpretation of it. Exactly one new session is followed; no new session
  keeps the existing pending-visibility notice and arms nothing; more than one new
  session arms nothing and names `logf <session>`, because following a guess would
  stream the wrong session.
- A launched session whose generation is empty is not followed, because liveness
  was never verified and the Endpoint would refuse the stream. The diagnostic names
  the next collection instead of arming a tail that fails on the next prompt.
- The automatic tail degrades to one bounded snapshot, with a diagnostic that says
  so, when the client cannot stream or the input mode cannot observe a keypress.
  A live tail that cannot be stopped would be worse than a snapshot, and a
  snapshot presented as a stream would look complete while silently missing
  everything written after it. The substitute reads the same trailing line count
  the stream would have read, so a degraded `send` or `btw` still shows 10 lines
  and a degraded entry or `start` still shows the REPL budget.
- A refresh that replaces the selected session drops the armed tail and reports
  it, because a stream bound to the replaced generation must never start.
- `send` asks for confirmation only when the payload is not already on screen. An
  explicit `send <text>`, `send {"text":"..."}` or `> <text>` submits directly,
  because the command word and the text are both visible. A bare `send` reads a
  multi-line block, echoes it verbatim and asks once, because the assembled block
  was never shown as a whole and the echo is the only place the operator can see
  it before it is admitted.
- `btw` never asks. Both forms submit directly, because context injection is
  additive and the operator already stated the command and its text, so a question
  could only repeat what is on screen. The bare multi-line form is included on
  purpose: the human directed that `btw` sends as soon as it is entered, and a
  confirmation on one form only would make the same command behave differently
  depending on how the text was typed.
- The confirmation gate stays on every operation that cannot be undone: `stop`,
  `interrupt`, `ctl`, `drive start` and `drive stop`.
- The bare-send confirmation is the block itself followed by one named prompt, not
  a flattened question:

  ```text
  send> first line
  send> second line
  send> EOF
  first line
  second line
  send.confirm[y/N]>
  ```

  The body keeps its own line breaks, indentation and spacing, because a flattened
  preview hides exactly the property the question protects: the operator cannot
  verify line breaks they cannot see. The body carries the payload colour, so a
  message never reads as the application's own prompt, and the prompt name states
  both the decision and the accepted answers, so no separate hint or repeated
  `Confirm send?` wording is needed. The prompt keeps its `[y/N]` hint when a
  narrow terminal clips it, because the hint is the only cue telling the operator
  what to type.
- A confirmation question expresses the session as the canonical identity
  expression, `({provider_session_name}) ({provider_session_id})`, for example
  `stop session (Daily work) (provider-res-1)? Confirm stop?`. The reported name is
  the only value the interactive table shows, because that table hides the
  `SESSION_ID` column, so naming it first lets the operator match the question
  against the row they selected. The provider identifier follows because it is the
  provider's own name for the session. The opaque cluster resource ID is not
  printed, because it is a routing identity rather than a name, and `status` and
  `info` still accept it. A name never replaces an identifier: it can be empty,
  duplicated or changed between collections. A session with no reported name
  renders `(provider-res-1)` alone rather than `() (provider-res-1)`, and a session
  with neither a name nor a provider identifier falls back to the opaque ID alone,
  so the question never names an empty session.

- The interactive tables hide the `SESSION_ID` column, because the provider session
  identifier is a long opaque value that only widens the table while the operator
  selects a session by row number or name. This covers both interactive tables: the
  session list and the `history` table. The column is presentation-only: the
  identifier stays on the row, so `logs`, `stop`, `drive` and the standalone `show`
  command still accept it. `cd` and the interactive `show` accept a row number, an
  internal resource ID or a unique display name, which is why the row number and
  name columns stay visible. The standalone `list` and `history` commands keep the
  column, because their output is parsed by scripts and tests.

## Audit

The table records the verified state of every command. Each standalone entry was
executed against an unreachable Server, so the observed message proves the command
was dispatched rather than rejected as unknown.

| Command | Standalone spelling | Interactive spelling | Compliant |
|---|---|---|---|
| `list` | `list`, `list --full`, `lf`, `list --brief`, `lb` | `list`, `l`, `list --full`, `lf`, `list --brief`, `lb` | yes (the `lf` shorthand implies the full layout and the `lb` shorthand implies the brief column set, on both surfaces) |
| `refresh` | `refresh [endpoint] [-a|--all]` | `refresh [endpoint] [-a|--all]`, `r` | yes (defaults to online Endpoints; an explicit Endpoint wins over that default) |
| `history` | `history <endpoint-id-or-hostname>` | `history [endpoint-id-or-hostname]` | yes (standalone requires the endpoint argument; interactive prints the numbered online endpoints and reads one answer in workspace scope, and in endpoint scope it defaults to the current endpoint while rejecting a different one) |
| `messages` | `messages <endpoint-id-or-hostname> <session-id>` | `messages [row-number-or-session-id]` | yes (standalone requires both arguments and addresses the provider session key; interactive resolves a bare number against the most recently rendered table, either the list or the history table, and rejects a number when neither is available) |
| `endpoints` | `endpoints` | `endpoints` | yes |
| `show` | `show` | `show` | yes |
| `info` | `info` | `info` | yes |
| `logs` | `logs`, `logs --follow`, `logf` | `logs`, `logs -f`, `logf` | yes (the `logf` shorthand implies follow on both surfaces) |
| `status` | `status` | `status` | yes |
| `send` | `send` | `send`, `>` | yes (explicit text submits directly; a bare `send` asks once) |
| `context.inject` | `btw` | `btw` | yes (the interactive form submits directly in both the inline-text and bare multi-line forms; the standalone form keeps its `--yes` gate) |
| `execution.interrupt` | `interrupt` | `interrupt` | yes |
| `ctl.<action>` | `ctl` | `ctl`, `control`, `ctl.<action>` | yes |
| `command.exec` | `exec` | `!<argv...>` | yes |
| `agent.start` | `start` | `start` | yes |
| `agent.resume` | `resume <endpoint> <resource> [text] [generation]` | `resume [-s <session_id>] [row\|session]` | yes (interactive `resume` selects a row from the most recently rendered table, or names a session in endpoint scope; `-s`/`--session` names a provider session identifier directly and the client performs no existence check, because the operator named the exact target and the endpoint mints the mapping when the command arrives; the endpoint still inspects the provider, so a live target is rejected with `target_still_active`) |
| `agent.stop` | `stop` | `stop` | yes |
| `workspace.clean` | `--yes clean <endpoint> <resource> [generation]` | `clean <row|session>` in workspace and endpoint scopes | yes (destructive confirmation is mandatory; session scope does not offer cleanup; row numbers and literal IDs resolve against the current persisted inventory before exact Endpoint-side inspection) |
| `agent.drive.start` | `drive start` | `drive start [session]` | yes |
| `agent.drive.stop` | `drive stop` | `drive stop [session]` | yes |
| `drive status` | `drive status` | `drive status [session]`, `drive [session]` | yes |
| `watch` | not applicable | `watch [interval] [--force] [-a|--all] [-t|--trigger[=<path>]]`, `w` | yes (projection and forced modes default to online Endpoints) |
| `help` | `help` | `help`, `?` | yes |
| `cd` | not applicable | `cd` | not applicable |
| `quit` | not applicable | `quit`, `q` (both navigate back outside workspace scope) | not applicable |
| `exit` | not applicable | `exit` (always leaves the loop) | not applicable |

No spelling is asymmetric any more. Every command word is accepted on both
surfaces, so an operator never has to remember which surface owns a spelling:

- `interrupt` is the single spelling of `execution.interrupt` on both surfaces.
  It takes an optional `soft`/`hard` action word and defaults to `hard`.
- `btw` is the single spelling of `context.inject`. The older `inject` spelling
  was removed rather than kept as an alias, because two spellings of one command
  forced every help, completion and diagnostic path to answer for both.
- `control` is an alias of `ctl`, not a second command. `ctl` stays canonical
  because the dotted form `ctl.<action>` is recognised from the raw command word
  before alias resolution, so a canonical `control` would make `ctl.heartbeat`
  work while `control.heartbeat` failed.

The `>` prefix is interactive-only and is deliberately absent from the standalone
surface, where `>` is a shell redirect. It is resolved before tokenisation, so
`>hello world` and `> hello world` both send `hello world`. Because the prefix is
disjoint from every command word, a message can never be read as a command and a
typo can never be read as a message; an unprefixed unknown word still returns the
unknown-command diagnostic. The alias keeps the session-only scope rule of
`send` and submits directly, exactly like an explicit `send <text>`: the prefix
already states both the action and the text, so a second question could only
repeat what the operator typed.

The `l` alias is interactive-only and resolves to `list` through the same alias
registry as `r` and `q`. It is absent from the standalone surface, which accepts
only the canonical `list` spelling. Because `canonicalCommandName` runs before the
dispatch switch, `l` inherits `list`'s arguments, scope availability and usage
diagnostics unchanged, and it does not shadow the longer `logs` spelling.

An alias answers with the spelling the operator typed. `help btw` is headed `btw`
and `help l` is headed `l`, while the body stays the canonical command's body, so
an alias never advertises a different contract and never answers with a name the
operator did not use. The heading is the only difference: syntax, scope line,
description, parameters, examples and fields are identical, which is why the
alias tests compare bodies rather than whole output. The standalone surface adds
an `Alias of:` line after the body, because there the operator may not know that
the spelling they typed is an alias.

`cd` and `quit` navigate a session that only exists inside the interactive loop, so
they have no standalone meaning and are not gaps.

`drive` is available in all three scopes, because a driver belongs to one session
but an operator usually starts from a fleet or endpoint listing. Its grammar is
`drive [start|stop|status] [session]`: the first token is read as an action only
when it names one, so `drive 3` and `drive res_abc` are the literal
`drive [number-or-session-id]` form and report controller state. Session scope
keeps its pinned selection and rejects a target argument, exactly as `stop` does;
workspace and endpoint scope require one, because there is no current session to
fall back to. Workspace scope resolves the row's own endpoint, and a token that
matches sessions on several endpoints is rejected rather than guessed. `status`
stays a read of the persisted projection and never admits a command, while
`start` and `stop` keep the confirmation gate and revalidate the exact generation
before dispatch. `stop` and `drive` share one target resolver, so the two cannot
drift into different authority checks.

`quit` is scope-aware, and this is a dispatch rule rather than a scope-availability
rule. Outside workspace scope `quit` navigates back to workspace scope and
re-renders the list, exactly like a bare `cd`; in workspace scope it leaves the
interactive loop. `q` is only an alias of `quit`, so it carries no rule of its own
and the two are one behaviour rather than two: the dispatch rule keys on the
canonical command name, so both spellings always agree. A surplus argument is still
a usage error, so `quit foo` can never be read as a navigation target.

`exit` is a separate canonical command, not an alias of `quit`, and it always
leaves the loop from every scope. It is deliberately absent from the alias registry:
if it were an alias it would inherit the scope-aware `quit` behaviour and stop being
an unconditional way out. Keeping it separate means an operator always has one
spelling that leaves the process no matter which scope they are in.

The `q` spelling inside the start and launch prompts keeps abandoning the draft and
leaving the loop, because those are prompt contexts rather than scope contexts.

`watch` is interactive-only for a different reason, and it is not a gap either. Its
ticks add no behaviour: every tick performs exactly `list` (re-read the persisted
projection) or `refresh` (forced collection), and both of those are fully
reachable standalone with `--json`. What the ticks add is a presentation cadence —
re-rendering a table on a timer while a prompt sits idle, and stopping on the first
keypress. A non-interactive caller that wants repeated reads writes its own loop
around `list`, which is strictly more expressive because it controls the exit
condition and the output format. The loop therefore has no standalone contract to
pin, and inventing one would duplicate `list` behind a second name.

`--trigger` is the one behaviour `watch` adds, and it is deliberately the only one.
It runs a local script when a watched session transitions from `running` to
`waiting_input`, so an operator who is already watching the table can react without
typing a second command. `-t` is a spelling of the same flag, not a second flag, so
it accepts exactly the two forms `--trigger` accepts: a bare `-t` selects the default
script and `-t=<path>` names one. `-t <path>` stays rejected for the same reason
`--trigger <path>` is rejected, because the interval is already positional and a bare
path would be indistinguishable from it. A repeated spelling in any combination,
such as `-t --trigger` or `-t=/a --trigger=/b`, is a usage error rather than a silent
override, because the duplicate guard is keyed on the request rather than on the
spelling. It stays inside `watch` rather than becoming a standalone
command because it is a foreground convenience, not a reliability promise: it lives
in the operator's own client process, so closing the terminal ends it, and it
observes whatever the Endpoint last collected rather than subscribing to provider
events. A caller that needs unattended reaction belongs in the Endpoint or in the
provider's own hook surface, not in a client-side loop.

Three properties keep the addition from turning `watch` into a second automation
surface:

- The trigger fires only on a real transition. The first observation of a session
  and a changed provider generation only record a baseline, so starting the loop
  never fires a script for a session that was already waiting, and a replaced
  process is never mistaken for a transition.
- The script runs directly without a shell, in its own process group, with a
  bounded timeout, and its output never reaches the terminal, because the editor is
  the only writer. A script that hangs therefore cannot delay a keypress, and a
  script that prints cannot corrupt the table.
- The child environment is built from a whitelist rather than inherited, because
  the client process holds every Endpoint token. A trigger script receives the
  documented `AGENT_CLUSTER_*` payload and nothing else, so a notification script
  never receives a cluster credential it did not ask for.

The delay is the Endpoint collection interval, not the watch interval, and a
transition that completes between two collections is never observed. That is a
property of sampling rather than a defect to fix: the provider reports a state, not
an event stream, so a client-side loop can only see states that were sampled.

The loop collects once immediately on start, before the first tick, so the operator
sees the current inventory at once instead of waiting a whole interval for a table
that is already available. The immediate collection is the same bounded collection a
tick performs, including the forced-collection path under `--force`, so it adds no
new capability and no new failure mode. A repeated identical failure is still
reported once, because the de-duplication applies to the immediate collection too.

Both watch modes apply the same Endpoint selection before every request. The default
projection mode does not read known-offline Endpoints, and `watch --force` does not
force provider discovery on them. `-a` and `--all` restore those Endpoints in either
mode. An explicit Endpoint scope still wins, because naming one machine is a request
to observe that machine even when it is offline. This rule must run before the read
or forced collection; hiding a row after the request would repeat the unavailable
diagnostic on every tick.

The presentation policy is re-read on every render rather than sampled once when the
loop starts, so a terminal resize during a watch run is honoured on the next tick.
Sampling it once would freeze the width at the moment the operator entered the
command, which is the same defect as caching a terminal width anywhere else.

Two consequences follow, and both are enforced:

- `watch` rejects `--json` in interactive mode instead of silently ignoring it, so
  a caller cannot believe it received a machine-readable stream.
- The standalone surface rejects `watch` as an unknown command rather than
  accepting it and degrading to a single read, which would violate the
  failure-semantics rule above.

The behaviour `watch` drives is pinned by the standalone tests for `list` and
`refresh`; the loop itself is pinned by the editor-level tests that inject a tick
channel, so no part of it depends on manual keystrokes for verification. Those tests
assert the immediate collection without delivering a tick, and assert that a layout
change between ticks reaches the next render.

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
action name and an explicit JSON payload; the interactive form is a convenience layer that
prompts for the action when it is omitted and then guides the parameters as `key=value`
pairs, so no JSON document is ever typed interactively. The prompt renders its action list
from the advertised capabilities rather than from a hardcoded list, so it cannot offer an
action the Endpoint does not support. A bare `ctl` in non-interactive mode is a usage
error, not a prompt, as the fourth command above shows.

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

That one-shot rule is scoped to `ctl.<action>` and `command.exec`, because both answer
one question about one invocation and then stop. It does not describe output reading.
Output follow is a separate capability, `output.follow`, and it is a real stream; see
the output follow section below. The two are never interchangeable: a follow request
that cannot stream returns an explicit error rather than a snapshot, and a snapshot
request never silently becomes a stream.

Two properties are worth stating because they are easy to get wrong:

- `exec` takes its argv array from the shell's own word splitting and never
  re-tokenizes it. Re-splitting a string at the Endpoint would reintroduce the shell
  semantics the allowlist cannot reason about, so `exec ep res gen -- ls -la` passes
  `-la` as an argument rather than as a misplaced option.
- The allowlist decision belongs to the Endpoint policy hook, not to the client. A
  denied command therefore surfaces as a durable `rejected` receipt with
  `policy_denied`, which is the same evidence an operator sees for any other
  admission refusal. The client never decides policy locally.

## Output follow

`logs` reads output. Without a flag it is one bounded snapshot. With `-f` or
`--follow` it is a stream, and the two forms are different capabilities rather than
two spellings of one behaviour.

- Standalone: `agent-cluster-cli [options] [--lines <lines>] [--follow] logs <endpoint> <session>`.
  The stream runs until the process is interrupted, because a non-interactive caller
  has no terminal to observe a keypress. An interrupt is a normal stop, not a failure.
- Interactive: `logs [-n <lines>] [-f|--follow] [session]`. The stream runs until any
  key is pressed, reusing the same watch seam that stops an auto-refresh loop, so the
  editor remains the only writer to the terminal.
- Both surfaces call the same runner method, so the two cannot diverge.
- A repeated follow flag is rejected rather than silently accepted, and an unknown
  flag still returns the usage line.
- A client without the streaming seam refuses follow explicitly. It never degrades to
  a snapshot, because a snapshot presented as a stream would look complete while
  silently missing everything written after it.
- The stream is bound to the session generation resolved from the committed inventory
  before the request is sent, so a replaced session is never followed by accident.
- Every stream ends with exactly one terminal record. A consumer that stops receiving
  records without that terminal record treats the stream as interrupted rather than
  complete, and the client reports `stream_interrupted` in that case.
- Provider lines are sanitized through the same boundary the snapshot renderer uses.
  A stream must not be able to move the cursor or retitle the window just because it
  arrives in pieces.
- `--json` emits one JSON document per record, so a machine-readable stream stays
  parseable line by line.

## The `logf` shorthand

`logf` is the shorthand of `logs -f`, so an operator who follows output often does
not have to type the flag. It is a form of `logs`, not a second command and not an
alias entry.

- Standalone: `agent-cluster-cli [options] logf <endpoint> <session>`.
- Interactive: `logf [-n <lines>] [session]`.
- Follow is implied, so every other argument keeps the meaning it has under `logs`:
  `logf -n 7` reads the same budget as `logs -f -n 7`.
- A repeated follow flag is rejected, because the shorthand already states follow
  and the combination is a contradiction rather than a harmless duplicate.
- The shorthand inherits the scope rule of `logs`, so it is unavailable in workspace
  scope for the same reason.
- Both surfaces resolve the shorthand into the canonical `logs` tail before parsing,
  so one grammar stays authoritative and the shorthand cannot drift into a second
  set of rules.
- It is deliberately absent from the interactive alias registry. An alias maps one
  word to another, while this form also supplies a flag; registering it would also
  make `lo` ambiguous between `logs` and `logf`, so Tab would stop completing the far
  more common `logs`. The shorthand is documented in the `logs` help body instead, so
  it stays discoverable without entering that registry.
- `help logf` answers with the canonical `logs` body and keeps `logf` as the heading,
  so the shorthand never advertises a different contract.

The transport is the existing authenticated WebSocket. One `output_follow_request`
starts a stream, repeated `output_chunk` frames carry records, and exactly one
`output_end` frame closes it, all correlated by the same request ID. No new
connection, no subscription resource and no durable stream state are introduced.

## Online Endpoint defaults and the `-a|--all` flag

`list`, `watch` and `refresh` select Endpoints before issuing a request. `list`
renders sessions from Endpoints that are online. An Endpoint that is not online is
not queried at all, so it produces neither a placeholder row nor an
`endpoint <id> unavailable` diagnostic. `-a` and `--all` are one flag in two
spellings, and they include those Endpoints again.

The decision belongs to the load, not to the render. Filtering after the fetch
would still issue the request and still print the failure the skip exists to
remove, which is why `--clean` previously hid the rows while leaving the
diagnostics in place. The loader therefore skips the request, and the renderer
drops the row that request would have produced.

The skip is never silent. One line states the count:

```text
offline endpoints hidden: 4 (use --all to include)
```

The count is printed instead of the identifiers, because naming each one would
reproduce the per-endpoint noise the skip removes, and `--all` is the documented
way to see them. The line is part of the answer rather than a diagnostic, so a
redirected stream receives it too. It is not printed in `--json` mode, because a
machine-readable document must stay one parseable document.

An explicit filter wins over the skip. `list --endpoint <offline-id>` renders that
Endpoint and reports its failure, because the operator named that exact machine and
an empty table would describe it as absent instead of offline.

`--clean` keeps a separate meaning. It also hides an online Endpoint whose fetch
failed, which the default still shows with its diagnostic. The two flags therefore
answer different questions and neither is redundant.

`watch` uses the same selection for every tick. Projection mode skips inventory
reads for known-offline Endpoints, while `watch --force` skips their forced
collections; `watch --all` restores them in both modes. `refresh` likewise forces
only online Endpoints by default and accepts `refresh [endpoint] [-a|--all]` on both
surfaces. A named Endpoint is attempted even when offline so its real failure is
reported instead of being misrepresented as absence.

The shared target-resolution load keeps its previous behaviour, because `resume`
exists precisely for a session whose process is gone: a resolver must still read a
disconnected Endpoint's retained document. Only fleet rendering and explicit
collection commands apply the online-only default.

## The `list --full` flag and the `lf` shorthand

`--full` is the per-command request to render the session table without truncation,
so an operator can read a long value in the middle of a session instead of
restarting the CLI with `--no-truncate`. `lf` is its shorthand, so the common case
does not require typing the flag. It is a form of `list`, not a second command and
not an alias entry.

- Standalone: `agent-cluster-cli [options] [--endpoint <id>] list [--clean] [-a|--all] [--full]`
  and `agent-cluster-cli [options] [--endpoint <id>] lf [--clean] [-a|--all]`.
- Interactive: `list [endpoint] [--clean] [-a|--all] [--full]` and
  `lf [endpoint] [--clean] [-a|--all]`.
- The full layout is implied by the shorthand, so every other argument keeps the
  meaning it has under `list`: `lf --clean` renders the same table as
  `list --clean --full`.
- A repeated `--full` is rejected, because the shorthand already states it and the
  combination is a contradiction rather than a harmless duplicate.
- `--full` is ORed with the startup `--no-truncate` option rather than replacing it,
  so a command that omits the flag cannot silently re-enable truncation.
- Both surfaces resolve the shorthand into the canonical `list` tail before parsing,
  so one grammar stays authoritative and the shorthand cannot drift into a second
  set of rules.
- It is deliberately absent from the interactive alias registry, for the same reason
  `logf` is: an alias maps one word to another, while this form also supplies a flag.
  Registering it would resolve the word and drop the flag, so `lf` would silently
  render the ordinary truncated table, which looks complete while hiding the tail of
  every over-wide value. It would also make `l` ambiguous between `list` and `lf`, so
  Tab would stop completing the far more common `list`. The shorthand is documented
  in the `list` help body instead, so it stays discoverable without entering that
  registry.
- `help lf` answers with the canonical `list` body and keeps `lf` as the heading, so
  the shorthand never advertises a different contract.

The full layout disables the terminal width bound and the per-column caps, so a
narrow terminal wraps a long cell onto several lines instead of clipping it. It does
not widen the terminal, and it does not change which rows are selected. The
`--no-truncate` startup option keeps its existing meaning and remains the way to make
every command full for a whole session.

## The `list --brief` flag and the `lb` shorthand

`--brief` is the per-command request to print only the columns that identify a row:
`NO`, `SESSION_NAME` and `ENDPOINT`. It exists so an operator can scan which session
runs on which machine without the descriptive columns pushing the table past a narrow
terminal. `lb` is its shorthand. It is a form of `list`, not a second command and not
an alias entry.

- Standalone: `agent-cluster-cli [options] [--endpoint <id>] list [--clean] [-a|--all] [--full] [--brief]`
  and `agent-cluster-cli [options] [--endpoint <id>] lb [--clean] [-a|--all] [--full]`.
- Interactive: `list [endpoint] [--clean] [-a|--all] [--full] [--brief]` and
  `lb [endpoint] [--clean] [-a|--all] [--full]`.
- The brief layout is implied by the shorthand, so every other argument keeps the
  meaning it has under `list`: `lb --clean` renders the same table as
  `list --clean --brief`.
- A repeated `--brief` is rejected, because the shorthand already states it and the
  combination is a contradiction rather than a harmless duplicate.
- `--brief` and `--full` are independent axes. `--brief` chooses the column set and
  `--full` chooses whether a value is truncated, so `lb --full` is a coherent request:
  the three identifying columns, printed without truncation. `--brief` is not ORed
  with any session-wide option, because no startup flag selects a column set.
- Both surfaces resolve the shorthand into the canonical `list` tail before parsing,
  so one grammar stays authoritative and the shorthand cannot drift into a second set
  of rules.
- It is deliberately absent from the interactive alias registry, for the same reason
  `lf` and `logf` are: an alias maps one word to another, while this form also supplies
  a flag. Registering it would resolve the word and drop the column set, so `lb` would
  silently render the wide table, which looks complete while showing every column the
  operator asked to hide. It would also make `l` ambiguous between `list` and `lb`, so
  Tab would stop completing the far more common `list`. The shorthand is documented in
  the `list` help body instead, so it stays discoverable without entering that registry.
- `help lb` answers with the canonical `list` body and keeps `lb` as the heading, so
  the shorthand never advertises a different contract.

The brief column set is a set rather than a list of removals, so a column added later
is absent from a brief table by default instead of silently widening it. It is applied
after the colour-dependent layout, so a brief table prints the same three columns
whether or not colour is enabled, which is what makes the layout predictable for an
operator who redirected the output.

The status summary line is kept. With `SESSION_STATUS` and `DATA_STATUS` dropped, the
summary is the only remaining signal of how the reported states are distributed, and
removing it would leave a brief table with no state information at all.

The spelling is `lb` rather than `ll` on purpose. `ll` is the shell mnemonic of
`ls -l`, which means more detail, so it would name the opposite of what this command
does. It also sits one key away from `lf` while meaning the reverse, so a typo would
produce a table that looks normal and hides half the information.

## Interactive output line budget

Entering session scope starts the same live tail as `logs -f` automatically, so the
REPL needs a line budget before the operator types anything. That budget is 300
lines by default, and the startup `--lines` option sets it within 100-1000.

- The budget is one quantity with one meaning: how many trailing output lines a
  read returns. `--lines` keeps that name on both surfaces instead of adding a
  second flag that would raise a precedence question and a silent loser.
- The default is surface-aware. A standalone `logs` keeps 100, because a script
  asking for a snapshot is not the same as an operator who deliberately selected
  a session. The REPL uses 300, because the entry tail is the first thing an
  operator reads and a session tail is usually read to see what just happened.
- An explicit startup value outside 100-1000 is rejected with an error naming the
  range. It is never silently clamped, because an operator who asked for 5000
  lines and silently received 1000 would believe the terminal showed everything.
- The range is a terminal budget, not a provider limit. The standalone surface
  still accepts any positive count, and the Server still clamps a provider read
  to its own documented maximum.
- The per-command override is unaffected: `logs -n 7` inside the REPL still reads
  7 lines, because a per-command read is a deliberate, visible request.
- The budget is resolved once when the REPL starts, so the entry tail, a bare
  `logs` and the degraded post-`send` snapshot cannot disagree about how many lines
  they show. Two separate literals would be free to drift apart. Every automatic
  tail uses the same resolved budget, so a follow and a snapshot never disagree
  about the bound either.
- The startup value is validated before the editor takes the terminal, so a
  rejected value never leaves the screen in raw mode.

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
hello world
>>> send the text above as a message? [y/N]
```

- The message row comes first and the question row comes second, so the operator
  reads exactly what would be sent before reading the question. The message row
  carries only the payload and its own colour, so a payload can never be read as
  the application's own question.
- The question row is the input row. The `>>>` marker separates the application's
  question from the message row above it, and the cursor waits after the answer
  hint, so no separate `answer>` prompt is printed for this offer.
- The offer does not repeat the unknown-command diagnostic inline. The message row
  and the question row already say what would happen, and the diagnostic is still
  reported when the offer is declined.
- The offer applies only in session scope. `send` is unavailable in workspace and
  endpoint scope, so an offer there could never be honoured and the plain
  unknown-command diagnostic is kept.
- A bare ASCII number is message text in session scope, not a navigation attempt.
  The numeric shorthand is a navigation form, and session scope has no row table to
  navigate, so `1` reaches this same offer and is sent as the literal text `1`. Only
  the explicit `cd 1` spelling reaches the row-number rule, which still rejects it
  with `row-number navigation is unavailable in session scope`. Rewriting a bare
  number into `cd <number>` would answer the operator's message with a navigation
  error instead of offering to send it.
- The whole literal line is the message, not the words after the unrecognized
  word. The operator typed one piece of text, and dropping its first word would
  silently change what is sent.
- Accepting runs the normal `send` flow with that text and does not ask the send
  confirmation again, because the offer already named the exact text and action.
  This is the same rule that lets an explicit `send <text>` submit directly: a
  question is asked only when the action or the payload is not already on screen.
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
- With colour disabled the offer is the plain form of the same two rows, so a
  redirected run carries no escape sequence.

## Global presentation flags

Presentation flags are global: they are parsed before the command word and apply
to every table command and to the interactive REPL started by the same
invocation. They never change query semantics or the data returned by the API.

| Flag | Effect |
|---|---|
| `--no-color` | Disable terminal colors |
| `--no-truncate` | Disable table truncation; a narrow terminal wraps instead of clipping |
| `--no-progress` | Disable progress lines for long-running commands |

`--no-truncate` is the switch for a small terminal. Truncation stays the default,
because a bounded table is what keeps a wide fleet readable. With the switch set,
the renderer ignores both the terminal width bound and the per-column caps, so a
long session ID, endpoint ID, hostname or capability revision is printed in full
and the terminal wraps it. The switch does not weaken sanitization: terminal
control sequences in provider data are still stripped.

`PROJECT_WORKSPACE` is clipped from the left, so an over-wide path keeps its
identifying tail (`...cluster/internal/tui`) instead of a prefix that every
sibling path shares. Every other column keeps its head. The rule
applies to both the framed and the narrow layout, and `--no-truncate` still
prints the complete path.

The column is capped at 23 display cells by default, because a workspace path is
descriptive context rather than a selector and must not push the fleet table past
the terminal. The `list` and `history` layouts read the same constant, so the two
tables cannot drift apart.

The cap is a default, not a ceiling. A terminal with width to spare grows the
column back towards the complete path, so a wide screen shows the whole value
while a narrow one still keeps the identifying tail. Growth spends only the width
the table does not need: a table that already fills the terminal grows nothing,
and a table that cannot fit the whole value grows by the spare width and stays
clipped. Growth runs before the width fitting, so the shrinker remains the final
safety net and a table can never exceed the terminal.

Growth is enabled only where the width is a real budget. A redirected stream
reports no width, so it keeps the capped layout and its output stays
byte-identical to the previous behaviour; a script that parses that output is
therefore unaffected. `--no-truncate` is unaffected too, because a full layout
already prints every value in full.

The output boundary owns the policy. The CLI writer reports a `TableLayout` of
width, truncation state and growth state, so every render path inherits the
switches without threading a new parameter through each command, and the
interactive prompt editor keeps the real terminal width as its editing budget.

## Time rendering

Every time the CLI shows a human must be readable. A raw epoch millisecond count
such as `1793885072943` is not acceptable on a human surface: an operator cannot
tell whether it is today, last week or a different unit, and comparing two of them
by eye is hopeless.

The rule applies to every human surface, including a table cell, a detail line, a
snapshot header and a conversation record. It does not apply to `--json` output,
which is a machine contract: a JSON field keeps its integer `*_at_ms` value so a
script, a BDD step or an integration assertion reads the exact instant. A human
label therefore never ends in `_ms`, because that suffix promises a millisecond
count and a rendered date and clock time is not one.

Three layouts exist, and each is justified rather than chosen for variety:

| Layout | Form | Used where |
|---|---|---|
| clock | `15:04:05` | a table cell, which has a width budget shared with the columns that address a row |
| date and clock | `2006-01-02 15:04:05` | a detail or standalone line, which has no width budget and can describe an earlier day |
| date and clock with milliseconds | `2006-01-02 15:04:05.000` | a conversation record, where two records can share one second |

A table cell keeps only the clock because the row's own stale marker already
carries the "this is not from now" signal, so the date is not the only freshness
evidence. A detail line prints the date because a bare clock would make yesterday's
observation look like today's. A conversation record keeps milliseconds because a
coarser layout would make two records written inside one second look simultaneous.

A time that was never reported renders as `-`, never as `0` and never as an empty
cell. A zero would read as a real instant at the epoch, and an empty cell would read
as a formatting gap rather than as an absent observation.

Times are rendered in the operator's local zone, so a value can be compared with
the clock on the wall in front of them. The layout definitions and the formatters
live in one place, `internal/tui/timefmt.go`, so no two surfaces can disagree about
how a time is written.

## Help option and the literal terminator

`--help` and `-h` are global meta-options, not per-command syntax. They are
documented once in the usage header and never repeated in each command entry,
because a repeated description drifts into inconsistent wording and reads like a
different feature per command.

- A help request is a successful request: it exits `0` and writes to stdout, so
  `agent-cluster-cli list --help | less` works and a script never mistakes help
  for a failure.
- `--help` renders exactly the same detail as `help <command>`, including
  parameters, examples and fields. One renderer serves both surfaces, so the two
  spellings cannot diverge.
- The option is recognized after the command word and before that command's own
  argument validation, so `list --help` is answered instead of being reported as
  a usage error.
- `--` ends option parsing. Before it, `--help` is a help request; after it,
  everything is literal data. `send ep res -- --help` therefore sends the text
  `--help`, and `ctl ep res action -- {"k":"v"}` accepts a payload that begins
  with a dash. `exec` keeps its own `--` because the terminator is part of its
  documented syntax.
- The interactive REPL has no `--help`. `send`, `btw` and `interrupt` take the
  rest of the line as literal content, so `send --help` sends the text `--help`;
  `help send` is the only help entry there. The standalone command can separate
  the command word from the payload by argv position, which is why the option
  exists only there.

### Exception: interactive `send` and `btw` accept no options

`send` and `btw` are the two commands whose entire remaining line is the payload,
so in the REPL they accept no options at all. This is an explicit exception, not
an oversight, and it applies only to the interactive surface.

- `send --help` and `btw --help` send the literal text `--help`. They do not
  render help, because the REPL cannot tell an option from a message: the rest of
  the line is the message.
- `help send` and `help btw` are the only help entries in the REPL. The
  interactive help for both commands states this exception, so an operator learns
  it from the help text instead of discovering it by sending `--help` as a
  message.
- `--json` is rejected rather than sent, because a payload that is only the
  option is a mistake, not a message. Ordinary prose that merely contains
  `--json` stays literal text.
- The standalone `send` and `btw` commands keep `--help`, because argv position
  separates the command word from the payload there. `agent-cluster-cli send
  --help` renders the same detail as `agent-cluster-cli help send`, and the
  standalone help does not advertise the interactive restriction.
- `interrupt` also takes literal content, but it is not part of this exception
  because its first token is an action word, not free text. A message without an
  explicit `soft` is rejected rather than guessed, so `interrupt please summarize`
  reports a usage error instead of silently choosing an action.

## Progress lines

A command that waits for a durable result reports what it is doing while it waits.
The wait is real: a `send` takes seconds and a forced collection can take longer,
so a silent terminal leaves the operator unable to tell work from a hang.

Progress is written to the diagnostics stream, never to the output stream. The
output stream is the machine contract, so `--json` output stays a single valid
document and a redirected stdout never receives a progress line.

The diagnostics boundary owns the decision, exactly as the output boundary owns
colour. Progress is enabled only when the diagnostics stream is a terminal, so a
redirected or piped stderr stays silent without the caller configuring anything.
`--no-progress` disables the lines explicitly. `--no-color` keeps the lines and
removes only their styling, because the lines carry the information and the colour
does not.

A command that finishes within 200 milliseconds prints nothing, because a hint
that appears and disappears within one frame is noise rather than information. The
fast read commands therefore stay silent, and only a command that actually makes
the operator wait reports progress.

Every stage row comes from a durable command state the client already polled, and
the wording comes from the same label the final receipt uses. A progress row
therefore never claims more than the receipt will: it reports delivery and
execution stages, and it never reports success before the receipt does. A repeated
stage is not a new fact and is printed once.

The header names the same target the confirmation question named, in the same
form: the canonical session identity expression, for example
`starting drive controller for session (Daily work) (provider-res-1) (ep-1)...`.
The operator therefore reads one target description before answering and the same
one while waiting, instead of an opaque identifier the interactive table never
showed. The name is descriptive report data: it is sanitized like every other
provider value, it never replaces the provider identifier, and an unnamed session
renders `(provider-res-1)` alone rather than `() (provider-res-1)`.

Progress never animates. The interactive diagnostics writer strips carriage
returns and cursor control, so an in-place animation would be printed as
replacement runes; and a spinner unrelated to real progress would be a fabricated
signal. Stages are printed as discrete lines instead.

That rule governs diagnostics this application writes, not provider log content.
Provider output is rendered through a separate boundary that normalizes a carriage
return to a line break, because a provider progress frame such as
`\rGenerating... 0 chars` is ordinary log content the operator must be able to
read. A raw carriage return is still never emitted, because it would move the
cursor to column zero and let provider data overwrite a trusted prompt row.

Progress is presentation only. A write failure is ignored, so a closed diagnostics
stream never changes the outcome of the command it describes, and a caller that
supplies no diagnostics stream keeps the previous silent behaviour.
## Interactive input block

The prompt editor renders the current edit as a soft-wrapped block instead of a
single horizontally scrolled row. A long message therefore keeps its head visible,
which is what an operator needs in order to review what was actually typed.

- The first row shares its width with the prompt; continuation rows use the whole
  terminal width, and one column stays reserved so a full row never auto-wraps.
- The block is bounded by the terminal height reported through the output
  boundary. A block taller than the screen scrolls by whole rows, so the cursor
  row always stays visible, and a writer without a terminal size falls back to a
  bounded default instead of rendering unbounded rows.
- Every redraw erases the previously rendered block first, so a block that shrank
  leaves no stale row behind. Submit, interrupt and EOF move the cursor to the
  block end before writing the newline, so the operator's input is never split.
- A Tab completion candidate list is printed below the erased block rather than
  inside it, so the next redraw cannot erase the candidates.
- Completion offers every canonical command plus each multi-character alias the
  scope permits, so `con` completes to `control` in session scope. A
  one-character alias is excluded because it is already complete the moment it is
  typed: offering it would never add a character and would only turn a unique
  completion into a false ambiguity. Completion and dispatch therefore agree on
  the same spelling set, and an advertised alias is always reachable by Tab.
- Unsafe runes are dropped, matching `sanitizeTerminal`, so the rendered block is
  byte-identical to the sanitized form of the typed text.

## Verification

- The first-use `help` overview must list the aliases the current scope accepts,
  filtered by the same availability rule the dispatcher uses, so a scope never
  advertises a spelling it rejects.
- Completion must offer every canonical command plus each multi-character alias,
  so an advertised alias is always reachable by Tab.
- The standalone help order and the dispatch switch must list the same commands.
- A test must prove each advertised syntax is executable, not merely printed.
- A test must prove a command that cannot perform its action returns an error
  instead of cached data.
- A new command must be added to the help order, the dispatch switch and the
  availability matrix in the same change.
- A test must prove no human surface prints a bare epoch number, and it must be
  seen to fail when a formatter is reverted to a raw value.
- A test must prove a human time label does not end in `_ms`, so the label never
  promises a millisecond count for a rendered date and clock time.
