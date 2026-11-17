---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
---

# Mutating commands and forced collection print nothing while they wait

## Trigger

Human report (verbatim):

> cli在发送send btw 这类的指令之后会显示一些信息，我希望能把正在做的动作加一些提示信息并标注颜色，例如正在发送/正在查询之类的。你认为呢

## Observed behavior

The non-interactive `send`, `btw`, `inject`, `control`, `ctl`, `exec`, `start`, `resume`, `stop`,
`drive` and `refresh` commands print nothing between the operator pressing Enter and the final
receipt. The silent interval covers the capability preflight, the command admission, and the whole
100 ms polling wait, so the terminal is completely static for the entire operation.

The interactive REPL is only marginally better: `submitSessionMessage` prints one
`command submitted: <id>` line and then waits silently, and the follow-up log read and forced
collection that `send` performs afterwards are also silent.

## Why this is a defect, not a cosmetic gap

The wait is long enough that a static terminal is indistinguishable from a hang. Measured latency
already recorded in `issues/refresh-latency-discovery-and-serial-fanout.md`:

| Command | Measured elapsed |
|---|---|
| `send` end to end | 10-17 s |
| `refresh` (workspace scope, 3 Endpoints) | 10493 / 10754 / 11509 ms |
| `refresh --endpoint ai-dev` | 3151-6626 ms |
| `endpoints` (no forced collection) | 8-9 ms |

An operator cannot tell a 17 s `send` from a wedged process, and cannot tell which stage is slow
when a command does eventually fail.

## Root cause

`action()` in `src/main/agent-cluster-cli/main.go` calls `PrepareAction`, `SubmitAction` and then
`WaitAction`, and none of those three steps writes to the diagnostics stream. `WaitForTerminal` in
`internal/tui/wait.go` already polls the durable command state every 100 ms and therefore already
observes every lifecycle transition, but it discarded that information instead of reporting it.
`Refresh` in `internal/tui/refresh.go` had the same shape: it collected every Endpoint and only
rendered the final table.

The information needed for an honest progress line was therefore already available at no extra
network cost; it was simply not surfaced.

## Fix

Progress lines are derived from the durable lifecycle states the wait loop already reads, so the
wording can never disagree with the final receipt:

- `internal/tui/progress.go` adds `ActionProgress`, which prints a header once and then one dim row
  per distinct stage, reusing `StatusLabel` for the wording.
- `WaitForTerminalWithProgress`, `WaitActionWithProgress` and `RefreshWithProgress` report stages;
  the previous functions delegate with a nil reporter, so existing callers are unchanged.
- `resolveProgressOutput` in `src/main/agent-cluster-cli/terminal.go` decides eligibility from the
  diagnostics stream itself, so a redirected stderr stays silent and `--no-progress` disables the
  lines without touching colour.
- A 200 ms threshold keeps fast commands such as `endpoints` completely silent.

## Constraints that the fix must respect

1. Progress goes to stderr only. stdout is the `--json` machine contract.
2. Colour is resolved from the stderr boundary, not from stdout, because `resolveOutputColor` reads
   stdout and would mis-decide when only one of the two streams is a terminal.
3. No `\r` animation in the REPL, because the REPL diagnostics writer is `safeWriter`, which only
   allows SGR sequences and replaces cursor control with a replacement character.
4. No fabricated state. Only real durable stages are printed, and the wording is shared with the
   receipt so a progress line can never claim success before the receipt does.

## Verification

| Case | Result |
|---|---|
| `send` on a PTY | 5 dim rows, one per stage, 10 SGR sequences, stdout pure JSON |
| `--no-progress` on a PTY | 0 progress bytes |
| `--no-color` on a PTY | 5 rows, 0 escape sequences |
| stderr redirected to a file | 0 progress bytes |
| `endpoints` on a PTY | 0 progress rows, table unchanged |
| `--json` with a PTY stdout | 0 escapes, valid JSON |

## Status

Resolved. The progress reporter is presentation only: a write failure is ignored and never changes
the command outcome.
