---
maintainer: AI
author: DawsonLin
status: open
---

# `logs` advertises `-n` but the standalone surface registers only `--lines`

## Symptom

`agent-cluster-cli help logs` prints the parameter as `-n, --lines`, and the REPL accepts `logs -n 3`.
The standalone surface does not register `-n`, so the documented short form cannot run.

## Evidence

| Probe | Result |
|---|---|
| `agent-cluster-cli -n 3 logs ac.ai-dev res_50da...` | `flag provided but not defined: -n` |
| `agent-cluster-cli logs ac.ai-dev res_50da... -n 3` | `usage: logs <endpoint-id> <session-id>` (the `-n` is read as a positional) |
| `agent-cluster-cli --lines 3 logs ac.ai-dev res_50da...` | works |
| `agent-cluster-cli help logs` | advertises `-n, --lines` |

Source: `src/main/agent-cluster-cli/main.go:114` registers `flags.Int("lines", ...)` only. The
`-n` spelling exists in the REPL path (`internal/tui/interactive_ops.go`), and
`internal/tui/help.go:87` advertises the short form in the shared help catalog.

## Impact

A documented flag that cannot run. The failure is also asymmetric in a way that hides it: the
misplaced form is read as a positional and reports a usage error that names the positionals, so the
operator concludes the arguments were wrong rather than the flag being absent. The REPL accepts the
same spelling, so a command copied from an interactive session fails in a script.

## Why it survived review

The help catalog is shared by both surfaces, so the advertisement is correct for the REPL and wrong
for the standalone parser. A test that asserts the help text passes, and a test that asserts
`--lines` passes, so neither covers the short form on the surface that lacks it.

## Suggested repair

Register `n` as an alias of `lines` in `src/main/agent-cluster-cli/main.go`, reconciling the two
spellings the way `-c`/`--max-chars` already are, and add a test that drives the real binary with
`-n` rather than asserting the help text.
