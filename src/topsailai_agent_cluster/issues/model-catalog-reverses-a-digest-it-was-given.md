---
maintainer: AI
author: DawsonLin
status: done
created: 2026-11-19
---

# A model catalog read reverse-resolved an identity the caller already held

## Symptom

The CLI `model` command felt slow. A catalog read for one live session took about 3.3 s, and the
largest single component was a provider call that produced nothing the caller did not already know.

## Root cause

`providers/topsailai/src/query.go` ran `workspace list --json --local` (measured 1.77 s) purely to
reverse-resolve a sha256 digest back into the provider session identifier. `models()` then used only
`resolved.SessionID`; the returned `ProviderRowKey`, `PID` and `IsTask` were discarded.

The identifier was already known by the CLI, which reads it from the committed inventory
(`protocol.Session.ProviderSessionID`, `internal/protocol/resources.go:29`, populated by `mapSession`
at `internal/adapter/genericcli/adapter.go:848`). It was dropped when the target was minted as a
digest, and the provider paid 54% of the read to recover it.

The digest cannot be reversed: `read.go` computes `sha256` + `base64.RawURLEncoding` over
`{"session_id":...}`, and `resource_mapping` stores only that digest. So the only way to recover the
identifier from the digest is to scan every workspace row and recompute each digest.

## Why the PID had to travel too

Session `20261119T165005` owns three workspace rows with PIDs 214141, 230926 and 317471.
`resolve_runtime_target` (`cli/cli_topsailai/runtime_target.py:145-181`) raises `ambiguous_target`
when more than one matching row is alive. A session identifier alone is therefore not an exact
target, so the process identifier travels with it.

## Fix

The provider's own session identifier and process identifier now travel on the read:

| Layer | Change |
|---|---|
| `internal/protocol/model.go` | `ModelCatalogQuery` gained `ProviderSessionID` and `ProviderPID` |
| `internal/providercli/query_types.go` | `ModelCatalogPayload` gained the two fields; a negative PID is refused |
| `internal/adapter/genericcli/adapter.go` | `ModelCatalog` forwards both into the payload |
| `providers/topsailai/src/query.go` | `models()` uses the supplied identity; discovery is the fallback only when it is absent |
| `providers/topsailai/src/model_current.go` | `currentModelName` takes the PID; argv carries `-p` |
| `internal/server/model.go` | route accepts `provider_session_id` and `provider_pid` |
| `internal/client/model.go` | sends both values |
| `internal/tui/session_identity.go` | one inventory read yields identity, generation and label |
| `internal/tui/model_catalog.go` | querier takes `(endpointID, query)` instead of four positional strings |
| `src/main/agent-cluster-cli/main.go` | passes the resolved identity |

The fallback is the previous behaviour rather than a second code path, so a caller with no inventory
row keeps its reachability. No cache, no second spelling, no compatibility branch.

## Verification

| Check | Result |
|---|---|
| `go build ./...` and `go vet ./...` (cluster) | clean |
| `go test ./...` (provider module) | ok |
| `make test-unit-common` | pass |
| `make test-unit-server` | pass |
| `make test-unit-endpoint` | pass |
| `make test-unit-cli` | pass |
| `TestModelCatalogUsesTheSuppliedIdentityWithoutDiscovery` | pass; asserts zero `workspace list` calls and exactly two provider calls |
| `TestModelCatalogFallsBackToDiscoveryWithoutAnIdentity` | pass; the fallback still serves a caller with no identity |
| `TestModelCatalogRejectsANegativePID` | pass; a rejected payload never reaches the provider |

## Measured cost before the fix (same round, load ≈ 4.8)

| Command | Time |
|---|---|
| `workspace list --json --local` | 1.77 s |
| `models list --json` | 0.33 s |
| `agent.llm` | 1.17 s |

The 1.77 s component is the one this fix removes for a caller that supplies the identity.

## Remaining gaps, not part of this fix

- `agent.models` emits neither `protocol` nor `enabled`, so it cannot replace `models list` as the
  availability source. Availability still needs `models list` (0.33 s).
- `agent.models` JSON support is not live in sessions started before `agent.py` was modified
  (`2026-11-19 16:11:56`); those sessions still return plain text for `json=1`.
- `session info` returns an empty `model_name` for a session that has not issued an LLM request yet,
  so it is not a reliable current-model source for a freshly started session.
- `agent.models` reads `FOLDER_ROOT/.models.jsonl` while `models list` reads
  `$TOPSAILAI_HOME/.models.jsonl`; they agree today only because `TOPSAILAI_HOME` is empty.
