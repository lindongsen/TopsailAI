---
maintainer: AI
author: DawsonLin
---

# Navigation and observation

| Case | Input and precondition | Expected output/effect |
| --- | --- | --- |
| NAV-01 | workspace: `list`, `list --clean` | table with the documented columns (NO, SESSION_NAME, SESSION_ID, ENDPOINT, DATA_STATUS; SESSION_STATUS only when colour is disabled); healthy session retained; numbers correspond to latest rendered list |
| NAV-02 | `cd <hostname>/<endpoint>` | endpoint prompt; automatic sibling table; cyan header, whole data row coloured by session state, green prompt; no output snapshot because endpoint scope was entered |
| NAV-03 | endpoint: `list <endpoint>` then `list other-endpoint` | matching filter accepted; other filter rejected without scope/valid row-map change |
| NAV-04 | endpoint: `<row>` or `cd <row>` from current list | selected session prompt contains provider label; one bounded output snapshot is rendered immediately before the prompt; subsequent show identifies correct internal resource/generation |
| NAV-05 | session: `list`, then `1` | sibling list; numeric navigation rejected, selected session unchanged, no additional output snapshot |
| NAV-06 | session: `cd ..`, `cd /`, reselect, bare `cd` | endpoint then workspace; automatic tables preserve colors; no duplicate prompt rows; leaving session scope and re-selecting the same session emit no output snapshot |
| NAV-07 | explicit internal selector, full hostname/endpoint/resource selector, provider session ID from the `SESSION_ID` column | same resource selected; one bounded output snapshot rendered on entry; the displayed provider session ID is accepted as input and resolves to the same internal resource and generation |
| NAV-08 | `cd nonexistent`, `cd 999999`, workspace `cd ..` | useful target/row error or documented root no-op; no accidental action or binding to old row |
| NAV-09 | endpoint: `logs <row>`, `show <row>` using a number from the latest list | the session at that row is selected; `logs` returns a genuine stdout body and `show` names the same internal resource and generation |
| NAV-10 | workspace: `show <provider-session-id>` copied from the `SESSION_ID` column | resolves to the same internal resource and generation as the matching row; no identifier has to be retyped from another source |
| OBS-01 | endpoint/session `show` | endpoint, collection_status, last_success_at_ms, selected session adapter/generation/state when session, capabilities and command history or no commands |
| OBS-02 | selected test session `logs`, and the snapshot rendered automatically on entering that session | observed_at_ms: integer, truncated: boolean, then genuine stdout text; compare body with provider runtime logs; idle sessions can still have logs; the automatic snapshot is bounded by the REPL defaults and an explicit `logs -n <lines>` re-reads with its own limit |
| OBS-03 | endpoint `logs <internal-resource>` | same body as selected session; endpoint bare logs rejects missing session |
| OBS-04 | new CLI session `status` before submissions | provider state (e.g. input/running); after admission status means last command result, not provider state |
| OBS-05 | `status <command-id>` | CommandID, Status, DeliveryBoundary, EffectCertainty, ErrorCode; compare submitted ID; unknown ID must error |
| OBS-06 | `refresh`, alias `r` in each scope | inventory refreshed/revalidated; in session scope the current endpoint table is rendered before the prompt, so the operator sees the reloaded rows; scope stays valid or explicit invalidation; no false claim of forced provider polling |

Selection precedence for `cd`, `logs` and `show`: a bare ASCII row number selects the session at that row of the most recently rendered list; a numeric token that is not a valid row number is retried as a provider session ID; a non-numeric token resolves by resource ID, then provider session ID, then display name. An unresolvable numeric token reports the row range (`row 77 is out of range; valid rows are 1-4`), and a numeric token that reaches the identifier path without a rendered list appends `; run list to select a session by row number`. Row numbers are the operator-facing shorthand, so no long identifier has to be typed.

Entering session scope renders one bounded output snapshot immediately, so the operator sees the session's current output without typing `logs`. The trigger is an actual transition into session scope: a rejected or cancelled `cd`, a `cd` that stays in the same session, and `cd ..`/`cd /` emit no snapshot. The read reuses the generation the transition already validated, so entering a session costs one output read and no repeated inventory discovery. A failed read prints `session selected; automatic logs failed: <cause>` and keeps the validated selection.

List state colors depend on state; do not demand green for input. A data row is coloured as one unit: every cell and the ` │ ` separators share the row's session-state colour, while DATA_STATUS keeps its own red/yellow warning when it reports a collection problem. Because the row colour already carries the state, the SESSION_STATUS column is omitted whenever colour is enabled; it is present only in colour-disabled output such as redirected streams or `NO_COLOR`, where it remains the only textual state signal. ANSI captures must preserve app-owned color and reject external escape injection. Long names and narrow terminals must not destroy prompt navigation. Logs truncation reflects bounded reads; absent body must be investigated against provider output, never accepted on metadata alone.
