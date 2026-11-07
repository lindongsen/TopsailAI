---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
---

# Post-action tables lose their colour in the interactive REPL

## Trigger

Human report (verbatim):

> 我发现一些指令执行完毕后会输出表格，这是符合预期的，例如启动新任务的时候，发送消息的时候。但是，我发现表格没有颜色，你分析原因。

## Observed behavior

Inside `agent-cluster-cli -i`, the tables printed *after* an action are plain text, while the tables
printed by `list`, `refresh` and `logs` are coloured. The same session therefore mixes coloured and
plain tables. When colour is disabled the renderer also keeps the `SESSION_STATUS` column, so a plain
table is visually distinguishable from a coloured one.

## Root cause A: the REPL renders post-action tables through a sanitizing writer

`RunInteractive` builds two writers (`internal/tui/interactive.go:193-194`):

```go
out := newSafeWriter(output)
errOut := newSafeWriter(errors)
```

and then passes both the sanitizing `out` and the raw `output` (as `trustedOut`) into the dispatcher
(`interactive.go:299`). Each command chooses one of them:

| REPL command | Writer | Colour |
|---|---|---|
| `list` (`interactive.go:413`) | `trustedOut` | kept |
| `refresh` (`interactive.go:437`) | `trustedOut` | kept |
| `logs` (`interactive.go:433`) | `trustedOut` | kept |
| `cd` re-render (`interactive.go:421`) | `trustedOut` | kept |
| `endpoints` (`interactive.go:415`) | `out` | **stripped** |
| `start` (`interactive.go:485`, `startOut` wraps `out`) | `out` | **stripped** |
| `send` (`interactive.go:499` → `submitSessionMessage`) | `out` | **stripped** |
| `stop` (`interactive.go:491`) | `out` | **stripped** |
| `drive` (`interactive.go:497`) | `out` | **stripped** |

`newSafeWriter` (`internal/tui/terminal_writer.go:36`) leaves `keepSGR` false, and
`consumeSequence` (`terminal_writer.go:123`) replays an SGR sequence only when `keepSGR` is set.
Every SGR sequence the table renderer emits through `writeStyled` is therefore discarded before the
bytes reach the terminal. `filterProviderOutput` (`terminal_writer.go:253`) already shows the correct
pattern, because it sets `keepSGR: policy.Enabled`.

The post-`start` table is affected twice: `refreshAfterStart` (`internal/tui/interactive_ops.go:552-557`)
passes the sanitizing `out` as both the output and the diagnostics writer.

## Root cause B: terminal detection reads stdin instead of stdout

`defaultTerminalDetector` (`src/main/agent-cluster-cli/main.go:45-48`) tests `os.Stdin.Fd()`. Colour is
therefore enabled only when **stdin** is a terminal. Any invocation whose stdin is a pipe or a
redirected file — `printf 'list\nquit\n' | agent-cluster-cli -i`, a heredoc-fed `send`, or an automation
harness — disables colour for every table even though stdout is a real terminal. The colour decision
belongs to the output boundary, not the input boundary.

## Root cause C: `ctl` and `exec` hardcode colour off

`src/main/agent-cluster-cli/ctl_exec.go:135` calls
`tui.RenderCommandExecResult(output, result, tui.ResolveColorPolicy(false, true, true, true, true))`,
so the `exec` result is permanently plain regardless of the terminal.

## Evidence (2026-11-07)

Live cluster under `.tmp/local-cluster` (server pid 2052267, endpoint pid 2100310).

| Probe | Result |
|---|---|
| Real pty, stdin a TTY: `agent-cluster-cli list` | ANSI present, 6 coloured header cells |
| Real pty, stdin `/dev/null`: `agent-cluster-cli list` | ANSI **0**, and `SESSION_STATUS` column reappears |
| tmux REPL (real TTY): `list` header | `^[[1m^[[36mNO^[[0m...` — coloured |
| tmux REPL (real TTY): `endpoints` header and rows | no ANSI at all |
| `RenderEndpoints`, `ColorPolicy{Enabled:true}`, raw writer | ANSI **88** |
| `RenderEndpoints`, `ColorPolicy{Enabled:true}`, `newSafeWriter` | ANSI **0** |
| REPL SGR totals vs baseline 98: `list` / `refresh` | 158 / 158 (+60 each) |
| REPL SGR totals vs baseline 98: `endpoints` / `start` | 100 / 100 (+2 each, prompt only) |

The `+2` deltas prove the `endpoints` and post-`start` tables contribute no styling at all, while
`list` and `refresh` contribute 60 sequences each.

## Detection failure

Every colour test injects `ColorPolicy{Enabled:true}` and calls the renderer directly on a raw
`strings.Builder`, so it never crosses the REPL writer boundary. `endpoints_test.go:137` asserts
coloured output from `RenderEndpoints` and passes, while the REPL path that calls it is plain.
`start_refresh_test.go`, `send_auto_logs_test.go` and `watch_test.go` all pass `ColorPolicy{}`, so no
test ever exercises a colour-enabled post-action render. No test asserts that a REPL command's table
carries the same styling as `list`, and no test covers a non-TTY stdin with a TTY stdout.

## Impact

Cosmetic for colour, functional for state: `columnsFor` drops `SESSION_STATUS` whenever colour is
enabled, because the row colour is meant to carry the state. When the colour is stripped, the state
column is already gone, so a post-`start` or `endpoints` table shows neither colour nor the state
column. The operator loses the only per-row state signal on exactly the tables printed after an action.

## Related issue

`issues/watch-table-loses-color.md` reports the same writer defect for the `watch` auto-refresh table,
which additionally loses the terminal width because `tableOptionsFor` derives the layout from the
sanitizing writer.

## Resolution

Fixed on 2026-11-07 in two parts.

Part 1 (REPL writer boundary and the `exec` policy):

1. `internal/tui/interactive.go`: `endpoints` renders through `trustedOut` like `list` and `refresh`, and
   `start`/`send` now receive a separate `trustedOut` so the post-action table and the automatic snapshot
   keep their styling. The receipt stays on the sanitizing `out` because it carries the provider's own
   return document verbatim. Provider-derived cell text is already sanitized by `escapeCell`, and
   `filterProviderOutput` sanitizes the snapshot body, so no untrusted escape reaches the terminal.
2. `internal/tui/style.go`: added `ColorPolicyProvider` and `OutputColorPolicy`, so a renderer reached
   through a generic writer honours the boundary policy instead of probing global terminal state. An
   unknown boundary keeps colour disabled.
3. `src/main/agent-cluster-cli/terminal.go`: `terminalOutput` carries the resolved `color` policy and
   reports it through `ColorPolicy()`; `resolveOutputColor` decides eligibility from the output stream.
4. `src/main/agent-cluster-cli/ctl_exec.go`: `exec` renders with `tui.OutputColorPolicy(output)` instead
   of the hardcoded disabled policy.

Part 2 (the remaining stdin-based decision, fixed in this session):

5. `src/main/agent-cluster-cli/main.go`: `list`, `refresh`, `endpoints`, `logs` and the interactive
   options still resolved colour from the **stdin** detector, so a TTY stdin with a redirected stdout
   emitted escape sequences into a pipe or file. All five now use `tui.OutputColorPolicy(output)`, which
   is the same seam the `action` path already used. `defaultTerminalDetector` keeps its stdin meaning
   only for the interactive-editing decision, which genuinely depends on the input stream.

Regression tests:

- `internal/tui/interactive_color_test.go` crosses the real REPL writer boundary: colour-enabled
  `endpoints`, post-`start` and post-`send` output must contain SGR; colour-disabled output must contain
  no `\x1b`; a hostile reported value and a hostile provider log body must still be stripped; the state
  column must survive whenever colour does not carry it.
- `src/main/agent-cluster-cli/terminal_test.go` covers the boundary decision: a redirected stdout stays
  plain even with a TTY stdin, `--no-color` still wins, the boundary reports its policy, and the whole
  `list` command emits no escape byte into a redirected stdout while keeping `SESSION_STATUS`.

Verification (2026-11-07):

| Check | Result |
|---|---|
| Probe before the part-2 fix: `list`, stdin TTY, stdout pipe | ANSI sequences **58** |
| Same probe after the fix | ANSI sequences **0** |
| Live TTY (`tmux`, 180x40): `list` | **60** SGR, `SESSION_STATUS` omitted (colour carries state) |
| Live redirected stdout, stdin a TTY: `list` | **0** SGR, `SESSION_STATUS` present, real table rendered |
| Live REPL: `endpoints` | **161** SGR, styled `ENDPOINT_ID` header |
| Live REPL: `watch 2s` | **226** SGR, styled `NO` header |
| `gofmt -l`, `go vet ./...`, `go build ./...` | clean |
| `go test ./... -count=1` | all packages pass, including `tests/bdd` and `tests/packaging` |
