---
maintainer: AI
author: DawsonLin
---

# Live manual test via tmux

This is an operator acceptance procedure, not a claim that unit tests prove live behavior. Execute modules in order. Inspect the actual terminal after each command. A driver may send reproducible keystrokes and capture evidence; visual checks and effect verification remain explicit.

## Run order

- [Environment and ownership](environment.md)
- [Help and command contracts](help.md)
- [Navigation and observation](navigation.md)
- [Terminal editing](editing.md)
- [Lifecycle and control](lifecycle.md)
- [Failures and cleanup](failures.md)
- [Execution status](results.md)

Use PASS only with fresh command output and the required effect. FAIL stops dependent checks until repaired and rerun. BLOCKED is not PASS. Capability absence is UNSUPPORTED only when accurately advertised; advertised-but-broken is FAIL. Never equate queued delivery, command completion and agent consumption.

Every case records case ID, input including keys, precondition, output, expected state, actual state, elapsed time and evidence. Full help and command transcripts live under workspace `.tmp/live-tmux-audit/`; no credentials in persisted documentation. Dynamic values `<endpoint>`, `<resource>`, `<generation>`, `<command-id>`, `<session-id>` and `<time>` come from the current run, never copied from old runs.

The documented interactive command set is list, endpoints, cd, show, start, resume, stop, inject, interrupt, logs, send, status, refresh, help, quit. Aliases: ?=help, exit=quit, q=quit, r=refresh, btw=inject, control=interrupt. Standalone CLI flags are not implicitly supported in the REPL, with one exception: the global presentation flags `--no-color` and `--no-truncate` are parsed before the command word and therefore apply to every table the REPL renders. See [Narrow terminal presentation](navigation.md#narrow-terminal-presentation).

The standalone `agent-cluster-cli` advertises `btw` and also accepts `inject` as an alias of it, so `inject <endpoint> <resource> [text] [generation]` and `help inject` behave exactly like `btw`; `help` still lists only the advertised spelling.
