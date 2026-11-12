---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectCode: AGENT_CLUSTER
programming_language: go
status: resolved
---

# Retired Endpoints Retain Inventory and Duplicate List Rows

## Symptom

After renaming four Endpoint identities to the `ac.{hostname}` convention, `agent-cluster-cli endpoints` showed four current online identities and four retired offline identities. `agent-cluster-cli list` returned both groups, so the same provider session appeared once under the current Endpoint and again under each retired Endpoint that had reported it before the rename.

The measured production data on gd-dev contained eight rows in `endpoints` and eight rows in `endpoint_session_state`. The retired identities were offline but still had committed inventory documents. For example, `wa-02c4ea84ac82` appeared under the online `ac.topsail` identity and under the retired `ai-dev`, `local-endpoint`, and `topsailai-dev` identities. The current online rows were not duplicated.

## Root cause

`internal/tui/model.go` intentionally projects retained inventory for disconnected Endpoints and labels those rows stale. A successful GET of an offline Endpoint's retained inventory is not a fetch error. The previous `--clean` implementation in `internal/tui/commands.go` omitted only rows whose inventory GET failed, so an offline Endpoint with a readable retained document survived `--clean` even though the help says the flag omits Endpoints that failed to report.

The Server has no implemented unregister or retirement operation. Storage exposes only Endpoint upsert, offline marking, listing, and lookup. The HTTP Endpoint resource supports GET/PUT inventory, GET capabilities, and POST refresh, but no DELETE. The architecture describes unregister semantics, but the operational surface does not implement them. Retired Endpoint metadata and latest inventory therefore remain indefinitely unless an operator edits SQLite directly, which is not an acceptable supported workflow.

## Current mitigation

`list --clean` now omits rows from Endpoints whose connection state is not `online`, on both table and JSON output. Plain `list` still shows retained stale inventory deliberately, so an operator can inspect what was last known.

This removes retired rows from the current operational view, but it does not remove the retired Endpoint records or their stored inventory.

## Resolution

The Server now automatically expires an offline Endpoint's latest inventory after `AGENT_CLUSTER_SERVER_ENDPOINT_EXPIRY`, which defaults to 24 hours. The cleanup runs immediately on Server startup and then at a bounded interval. It removes Endpoint metadata only when no retained command references the identity; otherwise it preserves the metadata and every command while deleting the stale inventory that produced duplicate list rows.

The retention window is measured from a dedicated `offline_since_at_ms` column, not from generic metadata `update_at_ms`, so a Server restart cannot reset the age of an Endpoint that was already offline. A restart marks a previously online Endpoint offline with a fresh offline start time, which is why a restart no longer deletes an entire fleet's inventory at once.

The 24-hour default supersedes the earlier five-minute default. The five-minute value expired inventory so aggressively that a routine Server restart could remove every Endpoint's inventory before the Endpoints reconnected, which made the fleet look empty rather than stale.

The state and age predicates are checked in the same transaction as deletion, so a reconnect cannot be removed by a stale cleanup decision. Each deleted inventory and metadata record is logged with its Endpoint identity and cutoff. An explicit authenticated retirement operation remains a useful administrative capability, but it is no longer required to prevent unbounded stale inventory or duplicate list rows.

## Verification evidence

- `agent-cluster-cli --json list`: 20 rows, including eight retained stale rows from four retired identities.
- Rebuilt `agent-cluster-cli --json list --clean`: 12 rows from `ac.ai-dev`, `ac.gd-dev`, `ac.topsail`, and `ac.topsailai-dev` only.
- Duplicate `provider_session_id` values after `--clean`: none.
- A regression test proves a disconnected Endpoint with a readable retained document is omitted by `--clean` while plain `list` still shows it.
- A second regression test proves JSON and table output apply the same `--clean` rule.
- Server storage tests prove expired offline inventory is deleted, fresh and online inventory remains, and command-referenced Endpoint metadata and commands survive.
- Server configuration tests prove the 24-hour default, environment override, flag precedence, invalid-value rejection, and Server-only ownership.
- Channel tests prove a silent half-open peer is swept, that only the exact authoritative peer is closed, and that an old generation cannot remove a replacement connection.
- Storage tests prove restart recovery marks a previously online Endpoint offline with a fresh offline start time while preserving the original offline start time of an Endpoint that was already offline.
- `make test-unit-server`, `make test-unit-common`, `make test-unit-endpoint`, `make test-integration`, `make test-packaging`, and `make vet` pass.
- Deployed on 2026-11-12 as `1:1.0.0+2967+ga2e53f17-1`; the live Server runs `--endpoint-expiry 24h`, and the migrated database contains `endpoints.offline_since_at_ms` and `idx_endpoints_offline_since`.

## Default list behaviour and the remaining display defect

The default `list` no longer shows a retired Endpoint at all. It is not queried, so it
produces neither a placeholder row nor an `endpoint <id> unavailable` diagnostic, and
one line states the count instead:

```text
offline endpoints hidden: 4 (use --all to include)
```

`-a`/`--all` restores the previous view, including the per-Endpoint diagnostics.
`--clean` keeps a narrower meaning: it also hides an online Endpoint whose fetch
failed, which the default still shows.

The decision moved from the render to the load. `--clean` previously filtered rows
after the fetch, so it hid the rows while still issuing four requests and printing
four 404 diagnostics. The loader now skips the request, and the renderer drops the
row that request would have produced.

Two display problems remain, and both are visible only under `--all`:

- The `ENDPOINT` column renders the Endpoint hostname rather than the unique
  `endpoint_id`. Three retired identities (`ai-dev`, `local-endpoint`,
  `topsailai-dev`) all have hostname `topsail`, so three different Endpoints appear
  as repeated `topsail` rows.
- The `SESSION_STATUS` cell reads `no sessions`, which sounds like a confirmed empty
  inventory. The real meaning is that no inventory document exists, so Session
  presence cannot be determined.

A more accurate placeholder would name the real `endpoint_id` and state
`inventory unavailable` instead of `no sessions`. This is a presentation change only;
the retention and command-reference behaviour above is correct and must not be
weakened to remove the rows.

## Verification evidence for the default list change

- `agent-cluster-cli list` on the live fleet: 7 rows from the four online `ac.*`
  Endpoints, empty stderr, and one `offline endpoints hidden: 4 (use --all to
  include)` line.
- `agent-cluster-cli list --all`: 11 rows including the four retired placeholders,
  with the four `endpoint <id> unavailable` diagnostics restored.
- `agent-cluster-cli list --clean`: the same 7 rows and the same summary line, with
  empty stderr.
- `agent-cluster-cli --endpoint ai-dev list`: renders the named retired Endpoint and
  reports its failure, proving an explicit filter wins over the skip.
- `agent-cluster-cli list --json`: 7 rows across the four online Endpoints, and no
  summary line inside the document.
- A regression test asserts the disconnected Endpoint is never queried by the
  default, and a second asserts `--all` restores the request, so the flag changes the
  load rather than only the rendering.
- Breaking the skip condition made five tests fail, and breaking the `--all`
  exemption made four more fail, which proves the new tests guard the behaviour
  rather than passing by construction.
- `make test-unit-cli`, `make test-unit-common`, `make vet` and `git diff --check`
  pass.

## Watch and refresh follow the same selection rule

`watch` and `refresh` now apply the same online-only default before issuing any
request. Projection watch does not read known-offline Endpoint inventories, forced
watch does not launch repeated collection attempts for them, and refresh does not
force them during a fleet refresh. `-a`/`--all` restores the complete Endpoint set.
An explicitly named Endpoint still wins over the default and is attempted even when
it is offline, so an operator asking for one machine receives its real failure.

This closes the remaining repeated-noise path: filtering only during rendering would
still issue one failed request per offline Endpoint on every watch tick. The shared
selection now runs before both inventory reads and forced collections. This section
records the code change only; package deployment evidence belongs in a later rollout
record.
