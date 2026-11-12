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

The Server now automatically expires an offline Endpoint's latest inventory after `AGENT_CLUSTER_SERVER_ENDPOINT_EXPIRY`, which defaults to five minutes. The cleanup runs immediately on Server startup and then at a bounded interval. It removes Endpoint metadata only when no retained command references the identity; otherwise it preserves the metadata and every command while deleting the stale inventory that produced duplicate list rows.

The state and age predicates are checked in the same transaction as deletion, so a reconnect cannot be removed by a stale cleanup decision. Each deleted inventory and metadata record is logged with its Endpoint identity and cutoff. An explicit authenticated retirement operation remains a useful administrative capability, but it is no longer required to prevent unbounded stale inventory or duplicate list rows.

## Verification evidence

- `agent-cluster-cli --json list`: 20 rows, including eight retained stale rows from four retired identities.
- Rebuilt `agent-cluster-cli --json list --clean`: 12 rows from `ac.ai-dev`, `ac.gd-dev`, `ac.topsail`, and `ac.topsailai-dev` only.
- Duplicate `provider_session_id` values after `--clean`: none.
- A regression test proves a disconnected Endpoint with a readable retained document is omitted by `--clean` while plain `list` still shows it.
- A second regression test proves JSON and table output apply the same `--clean` rule.
- Server storage tests prove expired offline inventory is deleted, fresh and online inventory remains, and command-referenced Endpoint metadata and commands survive.
- Server configuration tests prove the five-minute default, environment override, flag precedence, invalid-value rejection, and Server-only ownership.
- `make test-unit-server`, `make test-unit-common`, `make test-packaging`, and `make vet` pass.
