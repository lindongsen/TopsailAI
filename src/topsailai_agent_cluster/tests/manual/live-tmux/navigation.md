---
maintainer: AI
author: DawsonLin
---

# Navigation and observation

| Case | Input and precondition | Expected output/effect |
| --- | --- | --- |
| NAV-01 | workspace: `list`, `list --clean` | table with the documented columns (NO, SESSION_STATUS, SESSION_NAME, DRIVER, PROJECT_WORKSPACE, ENDPOINT, DATA_STATUS; SESSION_STATUS only when colour is disabled; SESSION_ID hidden in the interactive table and printed by the standalone `list` command); healthy session retained; numbers correspond to latest rendered list |
| NAV-02 | `cd <hostname>/<endpoint>` | endpoint prompt; automatic sibling table; cyan header, whole data row coloured by session state, green prompt; no output snapshot because endpoint scope was entered |
| NAV-03 | endpoint: `list <endpoint>` then `list other-endpoint` | matching filter accepted; other filter rejected without scope/valid row-map change |
| NAV-04 | endpoint: `<row>` or `cd <row>` from current list | selected session prompt contains provider label; one bounded output snapshot is rendered immediately before the prompt; subsequent show identifies correct internal resource/generation |
| NAV-05 | session: `list`, then `1` | sibling list; numeric navigation rejected, selected session unchanged, no additional output snapshot |
| NAV-06 | session: `cd ..`, `cd /`, reselect, bare `cd` | endpoint then workspace; automatic tables preserve colors; no duplicate prompt rows; leaving session scope and re-selecting the same session emit no output snapshot |
| NAV-07 | explicit internal selector, full hostname/endpoint/resource selector, provider session ID obtained from the standalone `list` command | same resource selected; one bounded output snapshot rendered on entry; the provider session ID is accepted as input and resolves to the same internal resource and generation |
| NAV-08 | `cd nonexistent`, `cd 999999`, workspace `cd ..` | useful target/row error or documented root no-op; no accidental action or binding to old row |
| NAV-09 | endpoint: `logs <row>`, `show <row>` using a number from the latest list | the session at that row is selected; `logs` returns a genuine stdout body and `show` names the same internal resource and generation |
| NAV-10 | workspace: `show <provider-session-id>` copied from the standalone `list` command | resolves to the same internal resource and generation as the matching row; no identifier has to be retyped from another source |
| NAV-11 | endpoint and session scope: `quit`, then `q`, then `/q`; workspace scope: `quit` and `q`; any scope: `exit` | outside workspace scope `quit` and its `q` alias are one behaviour: both return to workspace scope and re-render the workspace table with the pinned session selection cleared, exactly like a bare `cd`; in workspace scope both leave the REPL; `exit` is a separate command that leaves the REPL from every scope; `quit <extra>` and `q <extra>` are usage errors and never navigate |
| NAV-12 | endpoint: `history` | history table with the documented columns (NO, PROVIDER_STATUS, SESSION_NAME, PROJECT_WORKSPACE, LIVE, RESUMABLE); SESSION_ID is hidden in the interactive history table exactly as it is in the interactive list, and the standalone `history <endpoint>` command still prints it; row numbers are a separate namespace from list row numbers |
| OBS-01 | endpoint/session `show` | endpoint, collection_status, last_success_at_ms, selected session adapter/generation/state when session, capabilities and command history or no commands |
| OBS-02 | selected test session `logs`, and the snapshot rendered automatically on entering that session | observed_at_ms: integer, truncated: boolean, then genuine stdout text; compare body with provider runtime logs; idle sessions can still have logs; the automatic snapshot is bounded by the REPL defaults and an explicit `logs -n <lines>` re-reads with its own limit |
| OBS-03 | endpoint `logs <internal-resource>` | same body as selected session; endpoint bare logs rejects missing session |
| OBS-04 | new CLI session `status` before submissions | provider state (e.g. input/running); after admission status means last command result, not provider state |
| OBS-05 | `status <command-id>` | CommandID, Status, DeliveryBoundary, EffectCertainty, ErrorCode; compare submitted ID; unknown ID must error |
| OBS-06 | `refresh`, alias `r` in each scope | a fresh Endpoint collection is forced and awaited before rendering; in session scope the current endpoint table is rendered before the prompt, so the operator sees the reloaded rows; scope stays valid or explicit invalidation; a failed forced collection is reported instead of silently rendering cached data |

Selection precedence for `cd`, `logs` and `show`: a bare ASCII row number selects the session at that row of the most recently rendered list; a numeric token that is not a valid row number is retried as a provider session ID; a non-numeric token resolves by resource ID, then provider session ID, then display name. An unresolvable numeric token reports the row range (`row 77 is out of range; valid rows are 1-4`), and a numeric token that reaches the identifier path without a rendered list appends `; run list to select a session by row number`. Row numbers are the operator-facing shorthand, so no long identifier has to be typed.

Entering session scope renders one bounded output snapshot immediately, so the operator sees the session's current output without typing `logs`. The trigger is an actual transition into session scope: a rejected or cancelled `cd`, a `cd` that stays in the same session, and `cd ..`/`cd /` emit no snapshot. The read reuses the generation the transition already validated, so entering a session costs one output read and no repeated inventory discovery. A failed read prints `session selected; automatic logs failed: <cause>` and keeps the validated selection.

List state colors depend on state; do not demand green for input. A data row is coloured as one unit: every cell and the ` │ ` separators share the row's session-state colour, while DATA_STATUS keeps its own red/yellow warning when it reports a collection problem. Because the row colour already carries the state, the SESSION_STATUS column is omitted whenever colour is enabled; it is present only in colour-disabled output such as redirected streams or `NO_COLOR`, where it remains the only textual state signal. ANSI captures must preserve app-owned color and reject external escape injection. Long names and narrow terminals must not destroy prompt navigation. Logs truncation reflects bounded reads; absent body must be investigated against provider output, never accepted on metadata alone.

## Narrow terminal presentation

A small terminal must not silently destroy the values an operator needs. Truncation stays the default because a bounded table keeps a wide fleet readable, and `--no-truncate` is the switch that turns it off. The flag is global: it is parsed before the command word, applies to every table command and to the interactive REPL started by the same invocation, and never changes query semantics or the data returned by the API.

| Case | Input and precondition | Expected output/effect |
| --- | --- | --- |
| NAR-01 | 40-column terminal, `agent-cluster-cli list` | bounded layout: headers clipped with a trailing `...` such as `SES...`, `ENDP...`, `DATA...`; this is the default and must stay the default |
| NAR-02 | 40-column terminal, `agent-cluster-cli --no-truncate list` | every header printed in full (`SESSION_NAME`, `SESSION_ID`, `ENDPOINT`, `DATA_STATUS`) and wrapped across terminal lines instead of clipped; no `...` in any header or cell. The standalone command keeps `SESSION_ID`, so this check still covers it |
| NAR-03 | 40-column terminal, `agent-cluster-cli endpoints` versus `agent-cluster-cli --no-truncate endpoints` | bounded output clips the narrow columns to `.`; full output prints `ENDPOINT_ID`, `HOSTNAME`, `DISPLAY_NAME`, `CONNECTION_STATE`, `OBSERVED_AT`, `CAPABILITY_REVISION` completely |
| NAR-04 | 40-column terminal, `agent-cluster-cli --no-truncate` then `list` and `endpoints` in the REPL | the switch inherited from the launch invocation applies to every REPL-rendered table; the prompt editor still uses the real terminal width and the prompt remains usable |
| NAR-05 | provider data containing terminal control sequences, `--no-truncate` | sanitization still applies: escape sequences are stripped even though width clipping and per-column caps are disabled |

Verified on 2026-11-07 in a 40x30 tmux pane against an isolated fixture endpoint. Bounded headers rendered `SES...`, `SES...`, `ENDP...`, `DATA...`; the same pane with `--no-truncate` rendered `SESSION_NAME`, `SESSION_ID`, `ENDPOINT`, `DATA_STATUS` wrapped over two lines. The standalone `endpoints` command clipped its narrow columns to `.` when bounded and printed every column name in full when unbounded. Evidence is retained under workspace `.tmp/live-tmux-audit/evidence/`.

## Auto-refresh watch presentation

`watch` reprints the list on a timer, so it must present exactly what a manual `list` presents. The table is rendered into an internal buffer before it reaches the terminal, which is a different write path from `list`; a sanitizing seam that drops styling there would silently strip every colour while the manual `list` stayed coloured. The same seam decides the table layout, so a render that reads the buffer's layout instead of the terminal's would never fit the table to the pane.

| Case | Input and precondition | Expected output/effect |
| --- | --- | --- |
| WCH-01 | 180-column terminal, colour enabled, workspace `watch 2s` | every reprinted table carries the same styling as `list`: cyan bold headers, one whole-row colour per session state, coloured summary line; the `SESSION_STATUS` column stays absent because the row colour carries the state |
| WCH-02 | 180-column terminal, `agent-cluster-cli -no-color -i`, workspace `watch 2s` | no escape sequence in any reprinted table, and `SESSION_STATUS` is present as the only textual state signal |
| WCH-03 | 40-column terminal, colour enabled, workspace `watch 2s` | the reprinted table is fitted to the pane: every table line is at most 40 columns and headers are clipped with a trailing `...`, exactly as a bounded `list` does |
| WCH-04 | any keypress during `watch` | the loop stops before the key is applied, `auto-refresh stopped` is printed, and the prompt returns usable |

Verified on 2026-11-07 in 180x40 and 40x30 tmux panes against the live local cluster. WCH-01 reprinted 237 SGR sequences with cyan bold headers and per-state row colours; WCH-02 reprinted 0 SGR sequences with `SESSION_STATUS` present; WCH-03 bounded every table line to 40 columns with `S...`/`PR...`/`EN...`/`DA...` headers; WCH-04 printed `auto-refresh stopped` and returned a usable prompt. The same 40-column pane against the pre-fix binary printed 126-column lines, which is the regression this case guards. Evidence is retained under workspace `.tmp/live-tmux-audit/evidence/`.
