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
