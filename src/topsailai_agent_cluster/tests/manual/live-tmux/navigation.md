---
maintainer: AI
author: DawsonLin
---

# Navigation and observation

| Case | Input and precondition | Expected output/effect |
| --- | --- | --- |
| NAV-01 | workspace: `list`, `list --clean` | table with all eight documented columns; healthy session retained; numbers correspond to latest rendered list |
| NAV-02 | `cd <hostname>/<endpoint>` | endpoint prompt; automatic sibling table; cyan header, colored statuses, green prompt |
| NAV-03 | endpoint: `list <endpoint>` then `list other-endpoint` | matching filter accepted; other filter rejected without scope/valid row-map change |
| NAV-04 | endpoint: `<row>` or `cd <row>` from current list | selected session prompt contains provider label; subsequent show identifies correct internal resource/generation |
| NAV-05 | session: `list`, then `1` | sibling list; numeric navigation rejected, selected session unchanged |
| NAV-06 | session: `cd ..`, `cd /`, reselect, bare `cd` | endpoint then workspace; automatic tables preserve colors; no duplicate prompt rows |
| NAV-07 | explicit internal selector, full hostname/endpoint/resource selector | same resource selected; provider display ID is not assumed to be an internal ID |
| NAV-08 | `cd nonexistent`, `cd 999999`, workspace `cd ..` | useful target/row error or documented root no-op; no accidental action or binding to old row |
| OBS-01 | endpoint/session `show` | endpoint, collection_status, last_success_at_ms, selected session adapter/generation/state when session, capabilities and command history or no commands |
| OBS-02 | selected test session `logs` | observed_at_ms: integer, truncated: boolean, then genuine stdout text; compare body with provider runtime logs; idle sessions can still have logs |
| OBS-03 | endpoint `logs <internal-resource>` | same body as selected session; endpoint bare logs rejects missing session |
| OBS-04 | new CLI session `status` before submissions | provider state (e.g. input/running); after admission status means last command result, not provider state |
| OBS-05 | `status <command-id>` | CommandID, Status, DeliveryBoundary, EffectCertainty, ErrorCode; compare submitted ID; unknown ID must error |
| OBS-06 | `refresh`, alias `r` in each scope | inventory refreshed/revalidated; scope stays valid or explicit invalidation; no false claim of forced provider polling |

List state colors depend on state; do not demand green for input. ANSI captures must preserve app-owned color and reject external escape injection. Long names and narrow terminals must not destroy prompt navigation. Logs truncation reflects bounded reads; absent body must be investigated against provider output, never accepted on metadata alone.
