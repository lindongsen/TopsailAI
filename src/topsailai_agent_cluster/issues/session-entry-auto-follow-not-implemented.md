---
maintainer: AI
author: DawsonLin
---

# Session entry renders a snapshot instead of following the output

## Symptom

Entering session scope in the interactive CLI renders one bounded output
snapshot and then stops. The operator must type `logs -f` to see new output.

The human proposed that entering session scope should behave like
`logs -n 300 -f`, so the session's output keeps arriving without an extra
command.

## Current behaviour

`interactiveCD` calls `autoLogsOnSessionEntry` after every successful navigation
into session scope (`internal/tui/navigation.go:99`), which calls
`renderAutomaticSnapshot` (`navigation.go:111`). The guard at `navigation.go:24`
restricts this to a real scope transition, so re-selecting the same session and
leaving session scope both emit nothing.

The snapshot already tails 300 lines by default: `DefaultInteractiveMaxLines` is
300 (`internal/tui/interactive.go:31`) and `interactiveOutputBounds`
(`navigation.go:167`) resolves the request through `NormalizeInteractiveMaxLines`.
The `-n 300` half of the proposal is therefore already implemented.

The `-f` half is not. `logs -f` already exists and works, but only when the
operator asks for it.

## Why the follow half is feasible

The arming seam already exists. `interactiveLogs`
(`internal/tui/interactive_ops.go:22`) parses `-f`/`--follow` and arms
`state.follow` instead of starting the stream inline (`interactive_ops.go:66`),
because the editor owns the terminal and is the only writer. `startFollow`
(`internal/tui/follow.go:195`) consumes the armed intent at the next prompt and
returns a `followSession` implementing `WatchSession`. The REPL loop
(`internal/tui/interactive.go:311`) gives follow precedence over the
auto-refresh watch and stops the superseded loop.

The editor polls at 50 ms (`internal/tui/terminal_editor.go:397`) and calls
`watch.Idle()` on each idle tick, so `followSession.Idle()`
(`follow.go:143`) drains available records without blocking a keypress. Any
keypress stops the stream and prints `follow stopped`
(`follow.go:190`).

The provider supports the operation: `topsailai runtime logs` accepts
`-f`/`--follow` (`cli/cli_topsailai/runtime_cli.py:107`), rejects it combined
with `--json` (line 169), and `execute_log_follow`
(`cli/cli_topsailai/runtime_operations.py:145`) prints the initial tail then
polls appended records through one held descriptor. The adapter already invokes
it correctly (`internal/adapter/topsailai/adapter.go:620`).

## Blocking concerns

Three concrete problems must be resolved before auto-follow is safe.

### Follow silently does nothing without a terminal reader

`startFollow` returns `nil` when `options.WatchReader == nil`
(`follow.go:201`), discarding the armed intent with no diagnostic.
`wireEditorReaders` (`src/main/agent-cluster-cli/terminal.go:156`) attaches the
reader only when a real terminal editor exists.

The current snapshot needs no `WatchReader` and works everywhere. Replacing it
with an unconditional auto-follow would degrade a REPL without a TTY from
"shows output" to "shows nothing", with no explanation.

### The follow tail would be 20 lines, not 300

`FollowOutput` clamps `lines` to 20 when the value is absent or above 10000
(`internal/adapter/topsailai/adapter.go:626`). An auto-armed request must carry
`MaxLines` resolved from `interactiveOutputBounds`, otherwise the operator would
see a 300-line snapshot followed by a stream that only tailed 20 lines.

### Every session entry would hold a provider process

`execute_log_follow` keeps a descriptor open and polls indefinitely. Entering a
session would spawn a `topsailai runtime logs --follow` process that lives until
the operator presses a key. Rapid navigation across sessions would spawn and
kill these repeatedly, each holding a provider process and an open descriptor.

The stream also shares the terminal block with the prompt through
`applyWatch`/`redraw`, so a session producing output continuously makes the
prompt hard to read while the operator types. The existing design accepts this
for an explicitly requested `logs -f`; making it automatic turns an opt-in cost
into a default one.

## Options

### Option A: keep the snapshot, advertise the follow

Keep `renderAutomaticSnapshot` and print one line such as
`logs -f to follow` after the snapshot. No capability guard is needed, no
provider process is held, and the operator keeps full control. The cost is one
extra line of output and one extra command to type.

### Option B: follow when the capability exists, fall back otherwise

Arm a `followRequest` with `MaxLines` from `interactiveOutputBounds` when both
`OutputFollower` and `WatchReader` are present, and fall back to
`renderAutomaticSnapshot` with a one-line explanation when either is absent.
This never degrades silently, but it still holds a provider process per session
entry and still competes with the prompt for terminal rows.

Option B was preferred during review because it states the degradation
explicitly instead of hiding it. Option A costs less provider resource.

## Decision

Not implemented. The human chose to record the proposal as an issue rather than
change behaviour now, so the current snapshot-on-entry behaviour stands.

## Affected files if implemented

| File | Change |
|---|---|
| `internal/tui/navigation.go` | `autoLogsOnSessionEntry` arms a follow request instead of calling `renderAutomaticSnapshot`, with capability guards and a snapshot fallback. |
| `internal/tui/navigation.go` | Pass the `interactiveOutputBounds` result as `MaxLines` so the follow tail matches the snapshot tail. |
| `internal/tui/session_entry_auto_logs_test.go` | Existing tests assert one output call; they must assert the armed intent and the fallback path. |
| `docs/agent-cluster-architecture.md` | Note that entry-time follow is demand-driven and stops on the first keypress, so it does not contradict the no-periodic-snapshot-refresh decision. |

## Status

Open. Recorded from the human's proposal on 2026-11-09; behaviour deliberately
unchanged.
