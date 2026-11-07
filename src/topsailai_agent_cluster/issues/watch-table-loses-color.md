---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
---

# The interactive `watch` table loses its colour and ignores the terminal width

## Trigger

Human report (verbatim):

> watch指令输出的表格怎么没颜色？请分析

## Observed behavior

Inside `agent-cluster-cli -i`, `list`, `refresh` and `endpoints` print a coloured table, but the table
reprinted by `watch` on every tick is plain text. With colour enabled the auto-refresh table is also
missing the `SESSION_STATUS` column, so the operator loses both the colour and the only remaining
per-row state signal.

## Root cause

`internal/tui/watch.go:231-245` renders the table into an internal buffer through a sanitizing writer:

```go
var buffer bytes.Buffer
safe := newSafeWriter(&buffer)
options := tableOptionsFor(safe, c.color, false, ...)
```

`newSafeWriter` (`internal/tui/terminal_writer.go:36`) leaves `keepSGR` false, so every SGR sequence the
table renderer emits through `writeStyled` is stripped before the bytes reach the terminal. The REPL
`list` path instead renders into the real output boundary (`internal/tui/interactive.go:299` passes
`output` as `trustedOut`, dispatched at `interactive.go:413`), which is a `terminalOutput` that is not
sanitized, so its styling survives.

The same construction causes a second defect. `tableOptionsFor` derives the layout from the writer it is
given (`internal/tui/table_width.go:48-54` → `OutputLayout`), and a `*safeWriter` implements neither
`TableLayoutProvider` nor `TerminalWidth`, so the watch render always receives `Width: 0, Full: false`.
A zero width means "no terminal bound", so the auto-refresh table is never fitted to the terminal.

`columnsFor` (`internal/tui/table.go:75-87`) drops `SESSION_STATUS` whenever colour is enabled, because
the row colour is supposed to carry the state. In `watch` the colour is stripped, so the state column is
removed and nothing replaces it.

## Evidence (2026-11-07, `go test -overlay` probes under `.tmp/probe`)

| Probe | Result |
|---|---|
| `watch` render, `ColorPolicy{Enabled:true}` | ANSI sequences **0** |
| `renderListRows` into a raw buffer, same policy | ANSI sequences **58** |
| `watch` render with `keepSGR: c.color.Enabled` | ANSI sequences **58**, byte-identical to `list` (`equal=true`) |
| `watch` header, colour enabled | `NO │ SESSION_NAME │ ...` — no `SESSION_STATUS`, ANSI 0 |
| `watch` header, colour disabled | `NO │ SESSION_STATUS │ ...` — column present |
| `list` at terminal width 40 vs `watch` | max line width **40** vs **79** |
| REPL `endpoints` command, colour enabled | ANSI sequences **78** (unaffected) |

The defect arrived with commit `df89e753 feat: add interactive auto-refresh watch command`; the
`keepSGR` seam already existed from `f3062a1e fix: preserve sgr color in logs output`, so the watch
render was written against the older always-strip behaviour.

## Detection failure

Every `newWatchController(...)` call in `internal/tui/watch_test.go` (lines 183, 208, 230, 253, 275,
297, 316, 333, 350) passes `ColorPolicy{}`, so no test ever exercised the colour-enabled watch path.
No test compares the watch render with the `list` render, and no test renders watch against a writer
that reports a terminal width.

## Impact

Cosmetic for colour, but functional for state: in the default colour-enabled terminal the auto-refresh
table shows neither colour nor `SESSION_STATUS`, so a session that starts waiting for input or stops is
not visible while watching. The unbounded width also wraps the table on a narrow terminal, which in raw
mode prints as a staircase.

## Resolution

Fixed on 2026-11-07 with a minimal change:

1. `internal/tui/watch.go`: the render seam now builds
   `&watchWriter{safeWriter: &safeWriter{target: &buffer, keepSGR: c.color.Enabled}, layout: c.layout}`,
   so trusted styling survives exactly when the colour policy allows it. Provider-derived cell text is
   already sanitized by `escapeCell`, so no untrusted escape can reach the terminal.
2. `internal/tui/watch.go`: `watchWriter` embeds `*safeWriter` and reports the real output boundary's
   `TableLayout`, so the renderer fits the table to the terminal instead of to the internal buffer.
   `startWatch` now receives the output boundary and passes `OutputLayout(out)` into the controller.
3. `internal/tui/watch_test.go`: six regression tests cover the seam. They assert that colour-enabled
   watch output contains SGR and equals the `list` render byte-for-byte, that colour-disabled output
   carries no escape byte, that the state signal survives (colour or `SESSION_STATUS`, never neither),
   that the table honours a reported terminal width, and that keeping SGR never widens the allow list
   to cursor or title sequences.

Verification: the new tests fail against the pre-fix render (no SGR, lost state signal, width 96 over a
40-column bound) and pass after the fix. `go build ./...`, `go vet ./internal/tui/` and
`go test ./... -count=1` are green.

Live verification on 2026-11-07 against the running local cluster, using a freshly built CLI
(`.tmp/live-tmux-audit/bin/agent-cluster-cli`, md5 `d791e0d3a31cef8dee8b142123683298`) and a pre-fix
control binary built from `HEAD` sources through `go build -overlay` (md5 `02bc6d73bac98c61c37d953709be21fb`):

| Case | Pane | Fixed binary | Pre-fix binary |
|---|---|---|---|
| WCH-01 colour enabled, `watch 2s` | 180x40 | 237 SGR sequences, cyan bold headers, per-state row colours | 5 SGR sequences (prompt only), plain table |
| WCH-02 `-no-color`, `watch 2s` | 180x40 | 0 SGR sequences, `SESSION_STATUS` present | not re-run, same plain path |
| WCH-03 narrow pane, `watch 2s` | 40x30 | every table line exactly 40 columns, headers `S...`/`PR...`/`EN...`/`DA...` | 126-column lines, no fitting |
| WCH-04 keypress during `watch` | 180x40 | `auto-refresh stopped`, usable prompt | same |

The manual cases are recorded as WCH-01..WCH-04 in `tests/manual/live-tmux/navigation.md`. Evidence
transcripts are retained under workspace `.tmp/live-tmux-audit/evidence/`.
