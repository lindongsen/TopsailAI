---
maintainer: AI
author: DawsonLin
---

# Agent lifecycle and control

Use **only** the owned disposable test agent. Before every mutation assert provider ID, PID and generation match the ownership ledger. Keep another unrelated session running and verify it stays unchanged.

## LIFE-01 Wizard cancellation and launch

From endpoint type `start`. Expect project choice or `Choose a project number or enter a folder; empty/cancel cancels.` and `start.folder>`. Empty/cancel must print start cancelled and create no process. Repeat with the dedicated test project absolute path; at `start.task>` enter `Reply exactly LIVE_TMUX_READY and wait for further input. Do not use tools or modify files.` Expect one `command submitted: <id>; use status <id> to query`, then CommandID, Status, DeliveryBoundary, EffectCertainty, ErrorCode. Poll status without resubmitting. Verify exactly one newly created provider session, real stdout contains LIVE_TMUX_READY, agent waits for input. Record its identity before later actions. Profile fallback may require endpoint/resource/profile/revision prompts; record which branch was used.

## LIFE-02 Send cancel and delivery

Select owned session. Enter `send Reply exactly LIVE_TMUX_SEND.`. An explicit text submits directly: expect no `send.confirm[y/N]>` prompt, one admitted command, terminal command result, then one automatic live tail announced as `follow: <session-id> (any key stops)` without typing `logs`, reading the 10 most recent lines as `logs -n 10 -f` does, then one forced collection for that endpoint. The tail opens on the next prompt and streams new records; press any key and expect it to stop. Then verify the one form that still asks: enter a bare `send`, type `Reply exactly LIVE_TMUX_SEND.`, finish with a standalone `EOF` line, and expect the block echoed verbatim followed by `send.confirm[y/N]>`. Answer n; expect send cancelled, no command admitted, no LIVE_TMUX_SEND reply, and no automatic follow or forced collection. Repeat the bare form and answer y; expect the same automatic follow and forced collection as the explicit form. Query explicit status. Independently poll logs for the actual assistant reply LIVE_TMUX_SEND. Delivery acknowledged alone does not prove consumption. Use a fresh observation baseline to avoid matching the user request echo as a reply. If the automatic follow or the forced collection fails, expect a `send completed; automatic follow failed:` or `send completed; automatic refresh failed:` diagnostic and a still-usable session prompt; the accepted send must not be reported as failed. If the client cannot stream or the input mode cannot observe a keypress, expect one bounded snapshot plus a `send completed; automatic follow unavailable:` diagnostic instead of a silent snapshot. After the automatic refresh, run `list` and confirm the rendered rows come from the newly committed document rather than the pre-send projection.

## LIFE-03 Injection and aliases

Enter `btw For the next reply include LIVE_TMUX_CONTEXT.`; an explicit text submits directly, so expect no `Confirm inject? [y/N]` prompt, one admitted command and an acknowledged/accurately classified result, then the automatic live tail announced as `follow: <session-id> (any key stops)`, reading the 10 most recent lines as `logs -n 10 -f` does. Verify the bare multi-line form also submits without a question: enter a bare `btw`, type a distinct marker line, finish with a standalone `EOF` line, and expect the block to be admitted with no confirmation prompt. Send a new prompt requesting a short reply and verify assistant consumes context. `send {}`, arrays, invalid JSON and empty message must not be reported as successful delivery.

## LIFE-04 Interrupt and control

Enter `interrupt soft LIVE_TMUX_INTERRUPT` following advertised help, n first then y on the owned session. Separately verify `interrupt hard` only when the owned agent is actively doing disposable work. Also verify the guided form: a bare `interrupt` prompts for the action, an empty answer selects soft, and a following optional message is accepted. Record the exact provider result. Expected: supported interrupt reaches a real handler, not merely an admitted failed command. If the plain grammar is rejected or the provider requires a missing action name, record FAIL, repair adapter/help/tests, rebuild endpoint, rerun this case. Verify interruption state through provider observation; use an owned active request if idle interruption cannot prove effect. Alias `control` must route equivalently. Do not terminate any user process as a workaround.

## LIFE-05 Stop

Enter stop, n: `stop cancelled`, process remains. Enter stop, y: pinned-generation stop command admitted, inspect status, verify exact owned process exits and inventory eventually reports terminal/absent state. No other agent exits. A stale-generation request must fail closed. Capture provider state as well as CLI receipts.

## LIFE-06 Resume

For the owned resumable historical session, remain in the session scope retained immediately after its exact generation was stopped; the opaque resource mapping must remain durable even though complete fresh inventory no longer lists a live generation. Enter resume, n: cancelled, no process. Enter resume, y: before and after confirmation the CLI must prove the selected resource is absent from that adapter’s complete fresh inventory; a still-live target, a target that reappears, incomplete inventory or observation error must fail closed. Expect the command to be admitted only after that proof. Verify exactly one resumed worker with the same provider session ID, a new generation, and live input/output. Revalidate selection after generation changes rather than sending to stale state. Finish by stopping only the owned resumed worker and verify exit. If the provider rejects a genuinely persisted test fixture, record BLOCKED with cause, not PASS.

## LIFE-07 Confirmation prompt timing boundary

Select the owned disposable session and enter `stop`. Leave the `answer>` prompt unanswered for
longer than the command deadline (the interactive command budget is 10 s; wait at least 15 s).
Expected: the CLI neither prints `context deadline exceeded` nor returns to the shell; the prompt
stays at `answer>`. Then answer `y`. Expected: exactly one command is admitted, the receipt block
prints `CommandID`, `Status`, `DeliveryBoundary`, `EffectCertainty`, `ErrorCode`, and the CLI stays
alive. A timeout or an exit here is a FAIL: the human answer must never be bounded by the command
deadline.

Evidence: `.tmp/live-tmux-audit/err-11/evidence/` (waited 15 s, then `y` produced
`cli-1793862532921735973`).

## LIFE-08 Stop scope recovery

After an acknowledged `stop` on the owned session, the CLI must leave the removed session scope.
Expected: a notice of the form
`session <resource-id> is no longer reported by endpoint <endpoint-id>; returned to endpoint scope`,
the prompt becomes `endpoint[<hostname>/<endpoint-id>]>`, and `refresh` lists the endpoint
inventory without any `was not found` error. If the endpoint inventory is unavailable or
incomplete, the CLI must keep the scope and print
`scope unchanged: endpoint inventory unavailable; use cd .. to leave the session scope` instead of
guessing. A stale session scope that only `cd ..` can clear is a FAIL.

Evidence: `.tmp/live-tmux-audit/err-13/evidence/err13-fixed-stop-result.txt`,
`err13-fixed-refresh.txt`.

## LIFE-09 Wizard control words

At each project-launch prompt (`start.endpoint>`, `start.adapter>`, `start.folder>`,
`start.task>`) verify the control words before entering real values:

- `help`, `?`, `help start` → print the scoped `start` help and re-ask the same field. No launch
  query, no admission, no 503.
- `q`, `quit`, `exit` → abandon the draft and leave the REPL.
- `r`, `refresh` → abandon the draft, print `start cancelled`, refresh the current scope.
- A quoted control word (`'q'`, `"help"`) stays a literal value.
- A known canonical command name → `command unavailable during start input; cancel before running
  another command`, then re-ask.
- Empty input and `cancel` → `start cancelled`, nothing created.

After the sequence, `list` must show no newly created session.

Evidence: `.tmp/live-tmux-audit/err-14/evidence/`.
