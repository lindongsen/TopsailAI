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
| Input ergonomics | PASS | ERG-01..ERG-08, E6-01..E6-05 in `.tmp/live-tmux-audit/e5/evidence/` and `.tmp/live-tmux-audit/e6/evidence/` |
| Instruction shortcuts | PASS | CTLSHORT-01..CTLSHORT-05 against the isolated stack on API port 35739 |

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

## Input ergonomics case outcomes

Run against revision `f7257e00`; evidence under `.tmp/live-tmux-audit/e5/evidence/` and `.tmp/live-tmux-audit/e6/evidence/`.

| Case | Outcome | Evidence |
| --- | --- | --- |
| ERG-01 `cd 1` | PASS | prompt `session[ai-dev/20261027152208]>`, 0.128s |
| ERG-02 `cd ..` | PASS | prompt `endpoint[ai-dev/live-tmux-endpoint]>` |
| ERG-03 `list` | PASS | five numbered rows, `DATA_STATUS ok` |
| ERG-04 `logs 1` | PASS | `observed_at_ms: 1793885072943` (recorded before the readable-time change; the label is now `observed_at` with a date and clock time), `truncated: true`, genuine stdout body |
| ERG-05 `show 1` | PASS | `session: res_8b4fcbe92110e131e21549aa1fedccc0 ... generation=473390102 state=running` |
| ERG-06 `logs 9` | PASS | `error: row 9 is out of range; valid rows are 1-5`, rejected locally |
| ERG-07 `status` with no prior command | PASS | `error: no command has been submitted in this CLI yet; run an action such as start, then run status without an argument` |
| ERG-08 `start` in workspace | PASS | numbered endpoint list plus `Choose an endpoint number or enter an endpoint ID; empty/cancel cancels.`; a bare `1` advanced to `start.folder>` |
| E6-01 `show <provider-session-id>` | PASS | `session: res_d65da5099709a45885a0e5cf76bb5cad ... generation=473390102 state=running`, `capabilities: 8` |
| E6-02 `logs <provider-session-id>` in session scope | PASS | `observed_at_ms: 1793887855005` (recorded before the readable-time change; the label is now `observed_at` with a date and clock time), `truncated: true`, genuine stdout body |
| E6-03 `show wa-5dcbd9b23d57` | PASS | `session: res_0d661da703fc8449bd250e2326ebd4ee ... generation=483566876 state=running` |
| E6-04 `show 77` | PASS | `error: row 77 is out of range; valid rows are 1-4` |
| E6-05 `cd 1` after the E6 fix | PASS | prompt `session[ai-dev/20261027152208]>` |

`logs` is unavailable in workspace scope, so a provider-ID `logs` case must be run from endpoint or session scope; a workspace-scope run only proves the scope rejection and must not be recorded as an identifier result.

## Instruction shortcut case outcomes

Run against the isolated stack on API port 35739 with the shipped catalog, which loaded 48
actions including the 27 instruction shortcuts. Evidence is the CLI receipt and the provider
document it returned; no case is recorded from expectation.

| Case | Outcome | Evidence |
| --- | --- | --- |
| CTLSHORT-01 disagreeing constant | PASS | `ctl.git.status` with `{"instruction":"ctx.history"}` returned `Status: rejected`, `ErrorCode: control_payload_conflict`, `EffectCertainty: not_applied`, `DeliveryBoundary: not_started`; the provider was never invoked |
| CTLSHORT-02 empty payload | PASS | `ctl.git.status` with `{}` returned `Status: finished`, `ErrorCode: ""`, and genuine `git status` output (`On branch staging ... nothing to commit, working tree clean`); the decoded `intent_json` still carries `"payload":{}`, so the constant is injected at dispatch and not by the client |
| CTLSHORT-03 `ctl.ctx.history` | PASS | `Status: finished`, `ErrorCode: ""`, provider `result` begins with the conversation-history separator line |
| CTLSHORT-04 `ctl.agent.tokens` | PASS | `Status: finished`, `ErrorCode: ""`, provider `result` begins `Model: DeepSeek-V4-Flash-Preview` then `Agent2LLM:` |
| CTLSHORT-05 `ctl.git.branch` | PASS | `Status: finished`, `ErrorCode: ""`, provider `result` is `  main\n* staging\n` |

CTLSHORT-01 is the case that distinguishes the two failure classes. Before the fix it reported
`control_action_unconfigured`, which sends the operator looking for a missing catalog entry when
the entry exists and the payload is wrong. It now reports `control_payload_conflict` with
`not_applied` effect certainty, so the operator knows nothing was sent and the payload is what
must change.

CTLSHORT-02 is the case that proves the mechanism. The client submitted an empty payload, and the
provider still received `git.git_status`, so the catalog entry supplied the instruction. The
receipt's `intent_json` is the client's own intent and still shows `"payload":{}`, which is why the
injection point is the adapter and not the CLI.

A pinned constant narrows what the menu offers, not what a hand-built payload can reach: the
Endpoint does not validate a payload against the advertised schema, so a caller that builds the
payload itself can still name any instruction the provider registers. Closing that gap needs
Endpoint-side schema validation and is not part of this change.

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
| `logs`/`show` required a long session identifier | no row-number selector existed | `343c4b98` |
| `status` demanded a command ID it already retained | guidance text ignored the retained command | `343c4b98` |
| `start` wizard demanded a raw endpoint identifier | no numbered endpoint choice | `36fdcbcb` |
| Actionable errors named only long identifier forms | messages predated the short forms | `29380344` |
| The `SESSION_ID` column showed an identifier the CLI rejected | `FindSession` matched only the internal resource ID | `f7257e00` |
| A payload disagreeing with a pinned constant reported `control_action_unconfigured` | one error code covered both a missing catalog entry and a wrong payload | `c77139d6` |

## Remaining work

- ERR-05 and ERR-08 stay BLOCKED; they are not PASS and must not be reported as such.
- Full regression gate: `go build ./...`, `go vet ./...`, `go test ./... -count=1` (including the
  BDD suite) and `gofmt -l internal/ src/ tests/` are clean at `036339a3`.
- Cleanup of owned processes and tmux sessions is recorded in `failures.md`.
- Input ergonomics is complete: every target-taking command accepts a row number or a guided
  choice, and the identifier displayed in the list is accepted as input.
