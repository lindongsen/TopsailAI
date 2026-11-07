---
maintainer: AI
author: DawsonLin
---

# Disconnected endpoint kept reporting successful inventory

## Trigger

ERR-07 in the live tmux manual test stopped the owned endpoint transport while the server stayed alive, then ran `list` and `refresh` in the CLI.

## Observed behavior

The endpoint process had exited, but the CLI still rendered the retained inventory with `DATA_STATUS: ok` and no offline or stale marker. The operator could not distinguish a live endpoint from a dead one, and session-scoped commands still resolved against the historical snapshot.

## Root cause

`internal/channel/server.go` removed a closed peer from the in-memory active map only. No authoritative disconnect notification reached storage, so `endpoints.connection_state` stayed `online`. The TUI derived `DATA_STATUS` purely from inventory collection and freshness fields, so a retained snapshot from a dead endpoint was projected as current.

## Resolution

- `channel.Server` exposes `OnDisconnect`, invoked only when the removed peer is still the authoritative peer for that endpoint, with the observation timestamp captured under the channel lock and the callback executed outside it.
- `storage/server.Store.MarkEndpointOffline` writes `connection_state = 'offline'` only while the stored `instance_id` still matches and no newer observation has been persisted.
- The server wires the callback and logs both failures and fenced no-op disconnects.
- `tui.ListRows` marks every row of a non-online endpoint stale, and `findSelected` refuses to authorize session actions against a non-online endpoint.

## Prevention

Regression tests cover authoritative-only notification, fenced old connections, callback execution outside the channel lock, instance and observation fencing in storage, identity validation, stale projection for endpoints with and without sessions, and rejection of session actions on a disconnected endpoint. ERR-07 must additionally verify the offline projection and the reconnect recovery through real tmux.

## Follow-up defect: offline endpoint still admitted session scope

### Trigger

The first ERR-07 live run after the projection fix. The endpoint was already `offline`, `list` correctly rendered `DATA_STATUS: ok/stale`, but `cd 1` still entered `session[ai-dev/20261027152208]>`. Every command inside that scope then failed with `endpoint "live-tmux-endpoint" is not online: connection_state=offline`.

### Root cause

`enterValidatedSession` in `internal/tui/navigation.go` validated only session and adapter freshness. The endpoint connection state was checked later, inside `findSelected`, which runs after the scope transition already happened. A stale retained inventory therefore authorized a scope change and only rejected the action afterwards, leaving the operator stranded in an unusable scope.

### Resolution

- `internal/tui/navigation.go` adds `validateEndpointOnline(endpoint protocol.Endpoint) error` and calls it in `enterValidatedSession` before the freshness check, so a disconnected endpoint can never authorize a scope transition.
- `internal/tui/interactive.go` reuses the same helper in `findSelected`, removing the duplicated inline check so both entry paths share one rule.

### Prevention

`internal/tui/offline_projection_test.go` adds `TestCDRowNumberRejectsDisconnectedEndpoint` and `TestResolveSessionInEndpointRejectsDisconnectedEndpoint`. Both assert the offline diagnostic and that the scope, endpoint and session identifiers are unchanged after rejection, so a future refactor cannot silently move the check back behind the transition.

### Live verification

Real tmux run in an isolated environment (`cluster-err07b`, rebuilt binaries, CLI launched with `env -u AGENT_CLUSTER_SERVER_URL -u AGENT_CLUSTER_TOKEN` so no inherited endpoint could be used):

- Baseline: endpoint `online`, `list` showed `DATA_STATUS: ok`.
- After stopping the owned endpoint PID: API reported `connection_state: offline`, `list` showed `ok/stale`, `show live-tmux-endpoint` printed `endpoint: live-tmux-endpoint (offline)` with the retained `collection_status: succeeded` and 8 capabilities.
- `cd 1` in workspace scope was rejected with `error: endpoint "live-tmux-endpoint" is not online: connection_state=offline` and the prompt stayed `workspace>`.
- `cd live-tmux-endpoint` still entered the endpoint scope, which is intended because the endpoint scope is read-only, and `cd 1` there was rejected with the same diagnostic while the prompt stayed `endpoint[ai-dev/live-tmux-endpoint]>`.
- After restarting the endpoint: API returned `online`, `list` returned to `DATA_STATUS: ok` with a refreshed `LAST_SUCCESS`, and `cd 1` entered `session[ai-dev/20261027152208]>`.
- Evidence: `.tmp/live-tmux-audit/err-07b/evidence/01-baseline-list.txt` through `08-reconnect-cd-ok.txt`.
