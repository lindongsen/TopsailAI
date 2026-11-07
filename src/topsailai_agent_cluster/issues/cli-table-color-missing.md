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

## Recurrence report: the deployed binary was stale, not the source

Human report (verbatim):

> cli中的endpoints指令会显示表格，怎么没有颜色呢？要加颜色

The source already coloured the `endpoints` table, so this report was not a new code defect. The
installed commands `/usr/local/sbin/topsailai2` and `/usr/local/bin/topsailai_agent_cluster` are
symlinks to `bin/agent-cluster-cli`, and that file was built at 14:45, before commit `6fbad888`
(18:28) resolved the colour policy from the output boundary. The operator therefore ran the
pre-fix REPL, where `endpoints` was routed through the sanitizing writer.

Evidence (2026-11-07, real pty via tmux, `TERM=xterm-256color`):

| Probe | Result |
|---|---|
| Stale `bin/agent-cluster-cli`, REPL `endpoints` | **0** SGR: plain header, plain rows, plain `online(3)` |
| Stale `bin/agent-cluster-cli`, REPL `list` | coloured, so only `endpoints` looked wrong |
| Stale `bin/agent-cluster-cli`, non-interactive `endpoints` | **5** SGR, because that path never used the sanitizing writer |
| Fresh build, REPL `endpoints` | styled `ENDPOINT_ID` header, green rows, green `online(3)` |
| Fresh build, redirected stdout | **0** SGR, so a pipe still receives no escape byte |
| Fresh build, `--no-color` in a pty | **0** SGR |

Resolution: `make build` rebuilt `bin/agent-cluster-cli`, and `topsailai2 -i` then rendered the
coloured table. No source change was required. `go test ./internal/tui/ -run 'Endpoints|ColorPolicy'`
passes, and `TestInteractiveEndpointsKeepsColour` already crosses the REPL writer boundary.

Prevention: a colour report must be reproduced against a freshly built binary before any source
change is considered, because `bin/` is a gitignored build output and can lag the committed source.

## Interactive-mode report: a long-running REPL keeps the binary it started with

Human report (verbatim):

> 交互模式里没颜色，你看看

The interactive REPL was not a separate defect. The operator's REPL process (pid 4060408) started on
2026-11-06 23:11 and its executable was already `(deleted)` in `/proc`, because `make build` replaced
`bin/agent-cluster-cli` underneath it. A running process keeps the image it was started with, so that
session kept rendering with the pre-fix code even after the file on disk was corrected.

Evidence (2026-11-07, real pty via tmux):

| Probe | Result |
|---|---|
| Operator REPL pid 4060408, `/proc/4060408/exe` | `bin/agent-cluster-cli (deleted)`, started Nov 6 23:11 |
| Operator REPL environment | `TERM=screen`, no `NO_COLOR`, so colour is eligible |
| Fresh REPL, `TERM=screen`, `endpoints` | **23** SGR, styled header and green rows |
| Fresh REPL, `TERM=screen`, `list` | **33** SGR |
| Fresh REPL, `TERM=screen`, `refresh` | **41** SGR |
| Fresh REPL, `TERM=screen`, `logs` | **23** SGR |
| Fresh REPL, `TERM=screen`, startup banner / `help` / `cd` | **17** / **18** / **22** SGR |
| Fresh REPL, `TERM=dumb`, `endpoints` | **0** SGR, by design |
| Fresh REPL, `show` | **2** SGR, only the prompt: `show` is a key-value listing, not a table |

Resolution: restart the REPL. No source change was required; `go test ./internal/tui/ -run
'Color|Endpoints|List'` passes and `gofmt`/`go vet` are clean.

Prevention: after rebuilding, an already-open REPL must be restarted, because a running process never
picks up a replaced executable. A colour report from an interactive session must be checked against
`/proc/<pid>/exe` before the source is suspected.

Separate observation, not a colour defect: at endpoint scope the REPL rejects `endpoints` with
`unknown command "endpoints"`, because that command is workspace-scoped only. This is a scope rule,
not a missing colour, and is recorded here only so the two reports are not confused.

## Deployment report: the ai-dev container CLI was upgraded to the colour fix

Human report, verbatim:

> ai-dev 这个容器实例的cli你也更新一下

The `ai-dev` container ran the packaged layout under `/opt/agent-cluster/bin/`, installed by
`dpkg` as `agent-cluster-endpoint` and `agent-cluster-node` at `1:1.0.0+2305+g411bc484-1`. That
commit predates the colour fix `6fbad888`, so the container CLI showed the same uncoloured
`endpoints` table as the stale host binary. The container was updated through the supported
packaging path, not by copying a binary over a `dpkg`-managed file.

Build inputs, all verified before the build:

| Input | Value |
|---|---|
| Source | Clean detached worktree at `HEAD` = `e919d417`, which contains `6fbad888` |
| Site config | `.tmp/deb-site/node.endpoint.conf` (`ENDPOINT_ID=ai-dev`, `INSTANCE_ID=ai-dev-1`) |
| Certificate | `.tmp/ai-dev-bundle-v2/certs/node.pem`, `CN=ai-dev`, md5 `c64bb60e…` |
| Private key | `.tmp/ai-dev-bundle-v2/certs/node-key.pem`, public key matches the certificate |
| CA | `.tmp/ai-dev-bundle-v2/certs/ca.pem`, md5 `4efb3b29…` |

All three certificate files matched the container's `/etc/agent-cluster/certs/` byte for byte, so
the upgrade kept the same endpoint identity. The build ran from a clean worktree because the main
working tree carried another agent's unrelated in-progress changes; building from it would have
baked that work into the container.

The endpoint package declares `Depends: agent-cluster-node (= <same version>)`, so both packages
were rebuilt and installed together. Installation used `dpkg -i --force-confold`, because the
container's `/etc/agent-cluster/node.conf` carries an extra `COMMAND_ALLOWLIST_FILE` line that the
site template does not, and that local value had to survive the upgrade.

Verification inside the container:

| Probe | Result |
|---|---|
| `dpkg -l` versions | both packages advanced to `1:1.0.0+2309+ge919d417-1` |
| `/opt/agent-cluster/bin/agent-cluster-cli` | replaced, md5 `a0c42a75…` |
| REPL `endpoints` in a real pty | **460** SGR, bold cyan header, green rows, green `online(3)` |
| Redirected stdout | **0** SGR |
| `--no-color` in a pty | **0** SGR |
| `node.conf` | `COMMAND_ALLOWLIST_FILE` preserved |
| Certificates | md5 unchanged, identity intact |
| CLI env file | `/root/.topsailai/.topsailai_agent_cluster.env` unchanged |

The endpoint daemon (pid 786008) still runs the pre-upgrade image, which `/proc/786008/exe`
reports as `(deleted)`. It was deliberately not restarted: `git log 411bc484..HEAD` shows only
TUI, test and packaging commits, and `git diff --stat` over `internal/endpoint`, `internal/server`,
`internal/adapter`, `internal/storage`, `internal/protocol`, `internal/channel` and both daemon
entry points is empty. The running daemon is therefore functionally identical to the new binary,
and restarting it would drop the endpoint's channel for no behavioural gain. A restart is only
required when a future upgrade actually changes daemon code.

Prevention: a packaged node is upgraded with `dpkg -i` from a package built at a commit that
contains the fix, never by copying a binary into `/opt/agent-cluster/bin/`, because a bare copy
leaves the package metadata claiming the old version. Confirm the new package version is greater
than the installed one before installing, and keep `--force-confold` so local site values survive.
