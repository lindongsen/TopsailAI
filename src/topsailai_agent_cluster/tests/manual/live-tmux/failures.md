---
maintainer: AI
author: DawsonLin
---

# Exceptions, availability and cleanup

| Case | Procedure | Expected result | Outcome |
| --- | --- | --- | --- |
| ERR-01 | workspace/endpoint send, resume, stop, inject, interrupt | unavailable-in-scope error before mutation; available command list accurate | PASS |
| ERR-02 | session start | scope rejection; no new agent | PASS |
| ERR-03 | malformed JSON/quotes, unsupported option, unknown command | useful error, usage and next help guidance where supported; CLI continues | PASS |
| ERR-04 | `logs --json`, `list --json`, action --json in REPL | explicit non-interactive-only/rejected-option message, no mutation | PASS |
| ERR-05 | unsupported capability | explicit refusal before confirmation/admission; no invented success | BLOCKED |
| ERR-06 | selected generation changed while a bare `send` confirmation is open | fail closed; replacement worker never operated upon | PASS |
| ERR-07 | stop owned endpoint transport, list/refresh | disconnected/failed/stale data visibly distinct from successful empty inventory; restore service before dependent cases | PASS |
| ERR-08 | logs empty actual stdout, malformed provider response | genuine empty array allowed; provider error/missing lines fails explicitly; never silently reinterpret as success | BLOCKED |
| ERR-09 | ambiguous command admission or local timeout | preserve command ID, query status, no blind retry, distinguish local wait from actual outcome | PASS |
| ERR-10 | workspace scope: quit/q/exit and terminal interrupts in separate windows; endpoint and session scope: exit | expected exit, terminal echo/canonical mode restored, no provider shutdown; `quit` and its `q` alias outside workspace scope navigate back instead of exiting, so they are covered by NAV-11 rather than here | PASS |
| ERR-11 | leave the stop confirmation prompt unanswered past the command deadline, then answer | the CLI must not time out or exit; answering afterwards admits exactly one command | PASS |
| ERR-12 | stop, then wait past `deadline_at_ms` with delivery sent and exit unconfirmed | converge to `unconfirmed`/`unknown` with the same command ID; never stay `executing` forever | PASS |
| ERR-13 | stop an owned session, then inspect scope and run `refresh` | leave the removed session scope with an explicit notice; `refresh` must not report `was not found` | PASS |
| ERR-14 | `help`, `?`, `q`, `r` inside the project-launch prompts | print scoped help or leave the draft; never reach the launch query or admission | PASS |

## ERR-05 disposition

BLOCKED. The only live adapter on this host advertises all eight capabilities, so an honest
capability-disabled endpoint cannot be constructed without fabricating provider state. Automated
coverage of the refusal path lives in `internal/tui/` capability tests and
`internal/protocol/capabilities_test.go`. BLOCKED is not PASS.

## ERR-08 disposition

BLOCKED for the live CLI path, with the reason below, and replaced by automated envelope coverage.

- `interactiveLogs` resolves the selection with `findSessionInEndpoint` before any provider call.
  A stopped session is no longer reported by the endpoint inventory, so the command fails with
  `error: session "..." was not found on endpoint "..."` and never invokes the adapter.
- A live session always has a readable stdout file, so a genuine empty stdout cannot be produced
  without fabricating provider state. `/root/.topsailai/workspace/task/*.session.stdout` holds
  seven files and none of them is 0 bytes, so no honest empty-stdout fixture exists on this host.
- Automated coverage: `internal/adapter/topsailai/output_envelope_test.go` exercises twelve
  envelope classes — body present, empty array, Chinese text, truncated, scan limit, flat legacy
  shape, missing `lines`, `null` lines, `ok:false` with `error_code`, wrong `error_code` type,
  malformed JSON, and a failed subprocess.
- The live normal path was verified separately: `logs` returned `observed_at_ms: 1793859570861`,
  `truncated: true`, and a body containing `LIVE_TMUX_ERR08_READY` in 2.574 s.

BLOCKED is not PASS. Both facts must stay visible.

## ERR-11 evidence

`.tmp/live-tmux-audit/err-11/evidence/` — the prompt stayed at `answer>` for 15 s without a
timeout or exit, and answering `y` produced `cli-1793862532921735973` with
`Status: executing`, `DeliveryBoundary: signal_sent`, `EffectCertainty: acknowledged`.

## ERR-12 evidence

`.tmp/live-tmux-audit/err-12/evidence/err-12-summary.md` — before the deadline the command read
`executing`; after the deadline the same command ID read `Status: unconfirmed`,
`EffectCertainty: unknown`, `ExitConfirmed: false`; a second query was identical.

## ERR-13 evidence

`.tmp/live-tmux-audit/err-13/evidence/err13-fixed-stop-result.txt` and
`err13-fixed-refresh.txt` — the notice
`session res_d4780250cdec36190ef54c3e697ea4e8 is no longer reported by endpoint live-tmux-endpoint; returned to endpoint scope`
appeared, the prompt became `endpoint[ai-dev/live-tmux-endpoint]>`, and `refresh` listed the
inventory without a `was not found` error.

## ERR-14 evidence

`.tmp/live-tmux-audit/err-14/evidence/` — `help start` at `start.endpoint>` printed the scoped
`start` help and re-asked the same field with no 503; `help` at `start.folder>` and at
`start.task>` printed help and re-asked; `q` at `start.endpoint>` and at `start.folder>` left the
REPL; `cancel` at `start.task>` printed `start cancelled`; the following `list` showed no new
session.

Fault injection requiring process termination uses exact owned PIDs only. For cases infeasible through honest live setup, report BLOCKED and reference automated coverage separately. Do not fake provider failures and label them real-provider acceptance.

## Cleanup

Stop each ledger-owned test agent using the product command and verify process exit, child exit and no unrelated changes. Retain the final demo window on request; document retained service PIDs and later cleanup instructions. Stop only owned service supervisors, ensure their exact children exit, then close owned tmux windows. Delete only explicitly identified temporary artifacts, logging every deletion. Maintained test documents/scripts stay; evidence follows task retention. Never clean the shared provider home or user session files.
