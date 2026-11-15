---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI/src
ProjectCode: topsailai_agent_cluster
programming_language: go
---

# `resume -s <session_id>` cannot work by removing the client check alone

## Trigger

Directed by the human on 2026-11-14, wording normalized, meaning preserved:

> After `cd endpoint`, `resume -s {session_id}` should be allowed. I can name the session ID to
> resume. Do not judge whether the session ID exists.

## Observed behaviour

Two independent gates reject the request today.

1. Parsing. `internal/tui/interactive_history.go:229` calls `rejectInteractiveOption("resume", rest)`,
   and `internal/tui/interactive.go:1023-1030` rejects any token beginning with `-`. The operator sees
   `option "-s" is available only in non-interactive mode`. No `-s` or `--session` flag exists in
   `internal/tui` or `src/main/agent-cluster-cli`.
2. Existence. `resolveResumeSelection` (`internal/tui/interactive_history.go:278-314`) sends a
   non-numeric token in endpoint scope to `resumeSelectionBySessionID` (`:324-351`), which requires an
   online endpoint, a complete report and `findSessionInEndpoint` (`internal/tui/navigation.go:650-684`).
   An unknown name fails with `session %q was not found on endpoint %q`.

## Root cause

The client-side lookup is not the only obstacle, and removing it alone produces a request the Endpoint
rejects.

- `internal/endpoint/executor.go:331-345` (`adapterForIntent`) resolves the target only through
  `LookupResourceID(intent.Target.ResourceID)`. A miss is a coded `target_not_found` rejection.
- `internal/adapter/topsailai/provider_target.go:63-79` decodes that mapping with
  `decodeProviderSessionKey`, which requires the `session-row:` prefix minted by
  `providerSessionKey` (`:29-35`).
- `internal/protocol/command.go:34-38` defines `CommandTarget` with only `Kind`, `ResourceID` and
  `ProviderGeneration`. There is no field that can carry a provider session handle.

So the wire contract can express only an opaque cluster resource ID. A provider session identifier has
no path to the provider unless a durable mapping already exists, and mappings are minted only by
`Discover` (`internal/adapter/topsailai/adapter.go:341-345`) or `History`
(`internal/adapter/topsailai/history.go:79`).

The provider itself needs only the session identifier: `internal/adapter/topsailai/adapter.go:513-514`
builds `workspace resume -s <providerKey> --background --json`. The mapping requirement is a cluster
routing constraint, not a provider constraint.

## Latent defect found while tracing

`internal/adapter/topsailai/history.go:79` mints its mapping through `a.resourceID(ctx, entry.SessionID)`
(`internal/adapter/topsailai/adapter.go:370-379`), which stores the **bare** provider session ID as
`ProviderKey`. `decodeProviderSessionKey` rejects that value with
`resource mapping is not a TopsailAI session row`, and `matchesWorkspaceItem`
(`provider_target.go:83-85`) can never match it because the target carries no row key, PID or task flag.

The defect is masked whenever the same session was already discovered, because
`GetOrCreateResourceID` returns the existing `session-row:` mapping. It surfaces for a history-only
session that discovery never listed: `Inspect` fails, and resume is rejected with
`target_observation_failed` instead of reaching the provider.

## Why this is not a client-only fix

The human's requirement is that the client must not judge existence. That is satisfiable. But the
Endpoint must then be the party that resolves the named session, because it owns the durable mapping
and the provider seam. Without that resolution the operator's explicit target is rejected as
`target_not_found`, which is the same refusal the requirement asks to remove, only reported later and
with a less useful message.

## Decision taken

Approved by the human on 2026-11-14, wording normalized, meaning preserved:

> Option A now, and also fix the history mapping defect in the same unit.

The cluster defines the abstraction first, so a provider flag spelling never became the wire contract.
The implemented shape is the first option above:

- `CommandTarget` gained a cluster-level `provider_session_handle` field. Exactly one of `resource_id`
  and `provider_session_handle` is set; carrying both is `target_ambiguous`.
- The Endpoint resolves the handle through the owning adapter **before** `Inspect`, and before it takes
  the per-target lock, because the lock key is the resolved resource ID. Resolution rewrites the target
  to the resolved opaque resource ID and clears the handle, so every later stage sees one identity and
  the existing liveness gate still runs.
- Resolution is local bookkeeping and never queries the provider, so it never becomes an existence
  check. The client performs no existence check either: `resume -s` forwards the name untouched.
- The provider remains the only party that answers existence, when the operation reaches it. A live
  target is still rejected with `target_still_active`.
- The history mapping defect was fixed in the same unit: history now mints the session-scoped key
  instead of the bare provider session identifier, so a history row and an operator-typed handle
  resolve to one identity.

The provider spelling `-s` stays inside the adapter and the CLI parser; it never appears in the
protocol, a Server route or a stored document.

## Related

- `issues/resume-cannot-address-unknown-list-session.md`
- `issues/done/resume-unreachable-after-stop.md`
- `docs/cli-command-surface-rules.md:293` stated interactive `agent.resume` was not applicable, which
  contradicted the implemented interactive resume surface; corrected in the same unit.
