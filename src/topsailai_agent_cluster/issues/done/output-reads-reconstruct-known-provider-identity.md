---
maintainer: AI
author: DawsonLin
status: done
created: 2026-11-19
---

# Output reads reconstruct provider session identity the caller already holds

## Symptom

Every output snapshot and follow request for a normal inventory row discards the row's provider
session ID and PID. The TopsailAI Provider then scans its task directory and recomputes every row
digest to recover those same selectors before invoking `runtime logs`.

## Evidence

- Inventory sessions already carry `ProviderSessionID` and `ProviderPID` in
  `internal/protocol/resources.go`; TUI session rows preserve both values.
- `adapter.OutputRequest` and `protocol.OutputFollowRequest` carry only the Cluster resource ID and
  generation.
- `internal/adapter/genericcli/adapter.go:341-350` maps a snapshot target to an opaque Provider key;
  `adapter.go:364-385` does the same for follow.
- `providers/topsailai/src/resolve_digest.go:80-104` calls `os.ReadDir` and examines every output
  filename in `resolveRowTargetByDigest`.
- `resolveReadTargetByKey` at `resolve_digest.go:184-188` falls back to a full workspace discovery
  when the directory proof cannot recover the row.
- Only after this reconstruction do `output.go` and `follow.go` build `runtime logs -s SESSION -p PID`.

## Root cause

The Cluster resource mapping intentionally owns routing, but the request boundary treats that opaque
mapping key as the only Provider target fact. Exact selectors already present in the selected
inventory row are not forwarded as supplementary Provider evidence, so the Provider must reverse-map
the digest.

## Required direction

Carry the provider session ID and PID with snapshot and follow requests when the selected inventory
row supplies them. The Provider must still validate the exact target through the TopsailAI business
CLI and must retain the digest/discovery fallback for callers that genuinely lack these selectors.
It must not scan every task-directory row merely to recover values the caller supplied.

## Why this matters

The current fast path is O(number of output files) for every output read and follow start. It also
creates a filesystem-layout dependency before the business CLI is reached. Passing the known identity
removes reconstruction without weakening the Provider's exact-target refusal.
