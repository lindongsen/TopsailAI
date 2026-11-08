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
- `send` asks for confirmation only when the payload is not already on screen. An
  explicit `send <text>`, `send {"text":"..."}` or `> <text>` submits directly,
  because the command word and the text are both visible. A bare `send` reads a
  multi-line block and asks once, because the assembled block is never echoed as a
  whole and the question is the only place the operator can see it before it is
  admitted. The confirmation gate stays on every operation that cannot be undone:
  `stop`, `inject`, `interrupt`, `ctl` and `drive start`.
- A confirmation question names the provider session identifier first, followed by
  the opaque cluster resource ID in parentheses, for example
  `stop session provider-res-1 (res-1)? Confirm stop?`. The provider identifier is
  the value the list renders in `SESSION_ID`, so the operator can match the question
  against the selected row before answering; the opaque ID stays visible because
  `status` and `info` accept it. A session with no reported provider identifier
  falls back to the opaque ID alone, so the question never names an empty session.

## Audit

The table records the verified state of every command. Each standalone entry was
executed against an unreachable Server, so the observed message proves the command
was dispatched rather than rejected as unknown.

| Command | Standalone spelling | Interactive spelling | Compliant |
|---|---|---|---|
| `list` | `list` | `list`, `l` | yes |
| `refresh` | `refresh` | `refresh`, `r` | yes |
| `history` | `history <endpoint-id-or-hostname>` | `history [endpoint-id-or-hostname]` | yes (standalone requires the endpoint argument; interactive requires it in workspace scope, and in endpoint scope it defaults to the current endpoint while rejecting a different one) |
| `endpoints` | `endpoints` | `endpoints` | yes |
| `show` | `show` | `show` | yes |
| `info` | `info` | `info` | yes |
| `logs` | `logs`, `logs --follow` | `logs`, `logs -f` | yes |
| `status` | `status` | `status` | yes |
| `send` | `send` | `send`, `>` | yes (explicit text submits directly; a bare `send` asks once) |
| `context.inject` | `btw` | `btw` | yes |
| `execution.interrupt` | `interrupt` | `interrupt` | yes |
| `ctl.<action>` | `ctl` | `ctl`, `control`, `ctl.<action>` | yes |
| `command.exec` | `exec` | `!<argv...>` | yes |
| `agent.start` | `start` | `start` | yes |
| `agent.resume` | `resume` | not applicable | yes (standalone only: session scope requires a live generation while resume authorizes on a proven absence, so the interactive spelling was removed) |
| `agent.stop` | `stop` | `stop` | yes |
| `agent.drive.start` | `drive start` | `drive start [session]` | yes |
| `agent.drive.stop` | `drive stop` | `drive stop [session]` | yes |
| `drive status` | `drive status` | `drive status [session]`, `drive [session]` | yes |
| `watch` | not applicable | `watch`, `w` | yes |
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

The transport is the existing authenticated WebSocket. One `output_follow_request`
starts a stream, repeated `output_chunk` frames carry records, and exactly one
`output_end` frame closes it, all correlated by the same request ID. No new
connection, no subscription resource and no durable stream state are introduced.

## Interactive output line budget

Entering session scope renders one bounded snapshot automatically, so the REPL
needs a line budget before the operator types anything. That budget is 300 lines
by default, and the startup `--lines` option sets it within 100-1000.

- The budget is one quantity with one meaning: how many trailing output lines a
  read returns. `--lines` keeps that name on both surfaces instead of adding a
  second flag that would raise a precedence question and a silent loser.
- The default is surface-aware. A standalone `logs` keeps 100, because a script
  asking for a snapshot is not the same as an operator who deliberately selected
  a session. The REPL uses 300, because the entry snapshot is the first thing an
  operator reads and a session tail is usually read to see what just happened.
- An explicit startup value outside 100-1000 is rejected with an error naming the
  range. It is never silently clamped, because an operator who asked for 5000
  lines and silently received 1000 would believe the terminal showed everything.
- The range is a terminal budget, not a provider limit. The standalone surface
  still accepts any positive count, and the Server still clamps a provider read
  to its own documented maximum.
- The per-command override is unaffected: `logs -n 7` inside the REPL still reads
  7 lines, because a per-command read is a deliberate, visible request.
- The budget is resolved once when the REPL starts, so the entry snapshot, a bare
  `logs` and the post-`send` snapshot cannot disagree about how many lines they
  show. Two separate literals would be free to drift apart.
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
identifying tail (`...topsailai_agent_cluster/internal/tui`) instead of a prefix
that every sibling path shares. Every other column keeps its head. The rule
applies to both the framed and the narrow layout, and `--no-truncate` still
prints the complete path.

The output boundary owns the policy. The CLI writer reports a `TableLayout` of
width plus truncation state, so every render path inherits the switch without
threading a new parameter through each command, and the interactive prompt editor
keeps the real terminal width as its editing budget.

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

Progress never animates. The interactive diagnostics writer strips carriage
returns and cursor control, so an in-place animation would be printed as
replacement runes; and a spinner unrelated to real progress would be a fabricated
signal. Stages are printed as discrete lines instead.

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
