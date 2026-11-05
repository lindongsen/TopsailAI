---
maintainer: AI
author: DawsonLin
---

# Execution status

Current run: executed against the live isolated stack; two cases are BLOCKED and named below.
Detailed machine-readable case ledger and full terminal captures are stored under workspace
`.tmp/live-tmux-audit/`.

| Module | Status | Evidence |
| --- | --- | --- |
| Environment | PASS | `.tmp/live-tmux-audit/err-07/`, `err-12/`, `err-14/` |
| Help and contracts | PASS | `help.md` cases, live captures in `.tmp/live-tmux-audit/` |
| Navigation and observation | PASS | OBS-01..OBS-03 captures |
| Editing | PASS | EDIT-01..EDIT-12 captures |
| Lifecycle and controls | PASS | LIFE-01..LIFE-09, ERR-11, ERR-13 |
| Failures and cleanup | PARTIAL | ERR-05 BLOCKED, ERR-08 BLOCKED, ERR-09/ERR-12/ERR-14 PASS |

A module is not complete while required cases are failed or blocked. Fixes must name the failing case, root cause, regression checks and live rerun evidence. No blanket guarantee may replace this status table.

## Case outcomes

| Case | Outcome | Evidence |
| --- | --- | --- |
| ERR-01 | PASS | scope rejection before mutation |
| ERR-02 | PASS | session-scope `start` rejected, no agent created |
| ERR-03 | PASS | malformed input diagnostics, CLI continued |
| ERR-04 | PASS | `--json` rejected in interactive mode |
| ERR-05 | BLOCKED | no honest capability-disabled live adapter; automated capability tests cover the refusal |
| ERR-06 | PASS | generation swap during confirmation failed closed, zero forbidden markers |
| ERR-07 | PASS | `.tmp/live-tmux-audit/err-07/` (8 files) |
| ERR-08 | BLOCKED | CLI path unreachable; `internal/adapter/topsailai/output_envelope_test.go` covers 12 envelope classes |
| ERR-09 | PASS | `.tmp/live-tmux-audit/err-09/evidence/err-09-summary.md` |
| ERR-10 | PASS | `quit`/`q`/`exit`/Ctrl-D restored canonical mode |
| ERR-11 | PASS | `.tmp/live-tmux-audit/err-11/evidence/` |
| ERR-12 | PASS | `.tmp/live-tmux-audit/err-12/evidence/err-12-summary.md` |
| ERR-13 | PASS | `.tmp/live-tmux-audit/err-13/evidence/err13-fixed-*.txt` |
| ERR-14 | PASS | `.tmp/live-tmux-audit/err-14/evidence/` |

## Defects found and fixed during this run

| Defect | Root cause | Fix commit |
| --- | --- | --- |
| `logs` printed an empty body | adapter read top-level `lines` instead of `response.lines` | `a04d0b88` |
| TAB exited the CLI | unsupported key path returned a fatal error | `36ef9adc` |
| Scope prompt and `cd` colour loss | fixed prompt string, untrusted table rendering | `0a90fdb8` |
| Disconnected endpoint still reported `ok` | no authoritative disconnect callback | `6a094e69`, `f915a047` |
| Confirmation prompt timed out and exited the CLI | confirmation read inherited the command deadline | `a24b09eb` |
| Command stuck in `executing` forever | no convergence path past the deadline | `8e9e712c`, `23e0fe6c`, `41df6fc5` |
| `stop` left a stale session scope | no post-receipt scope reconciliation | `4368c16f`, `16f0549b` |
| Wizard control words reached the launch query | `launchAnswer` only recognised empty/`cancel` | `2c5e0f0f` |
| BDD stop scenario flaked on a premature receipt | `isTerminalCommandStatus` treated pre-execution states as terminal | `036339a3` |

## Remaining work

- ERR-05 and ERR-08 stay BLOCKED; they are not PASS and must not be reported as such.
- Full regression gate: `go build ./...`, `go vet ./...`, `go test ./... -count=1` (including the
  BDD suite) and `gofmt -l internal/ src/ tests/` are clean at `036339a3`.
- Cleanup of owned processes and tmux sessions is recorded in `failures.md`.
