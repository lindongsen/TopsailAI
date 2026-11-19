---
maintainer: AI
author: DawsonLin
status: done
created: 2026-11-19
---

# Mutations use a global workspace list to recover a known exact target

## Symptom

A session action starts with an inventory row that already contains the provider session ID and PID,
but the immutable command target drops both values. The TopsailAI Provider must run an unfiltered
`workspace list --json --local` for every row-scoped mutation to recover the target before applying
its authority checks.

## Evidence

- `internal/tui/command_actions.go:14-39` receives `ProviderSessionID` but labels it presentation-only;
  it has no provider PID field.
- `PrepareAction` at `command_actions.go:99` writes only Cluster resource ID, generation and an
  optional session handle into `protocol.CommandTarget`.
- `internal/protocol/command.go:44-49` has no ordinary provider session ID or PID fields.
- Generic CLI target construction resolves the Cluster resource ID to an opaque Provider key.
- `providers/topsailai/src/mutation_authority.go:54-97` runs
  `workspace list --json --local`, scans every item, recomputes keys and then obtains the session ID,
  PID and current process generation.
- The TopsailAI business CLI has an exact `runtime info -s SESSION -p PID` read that can validate the
  selected row without listing unrelated rows.

## Root cause

Command target design retained only the opaque Cluster identity and generation. Provider selectors
were treated as presentation data even though the Provider needs them in the same execution path to
perform exact authority revalidation.

## Required direction

Carry provider session ID and PID in the immutable target when the selected inventory row provides
them. Keep every existing safety property: host-local authority, exact session/PID intersection,
record existence, generation comparison, ambiguity refusal and same-path revalidation immediately
before the mutation. Use an exact Provider read such as `runtime info -s SESSION -p PID` for a
row-scoped target rather than a global workspace listing.

Session-handle resume and callers without an inventory row retain their existing registry/discovery
paths; the direct path is not permission to remove a necessary fallback.

## Resolution

Implemented with one deliberate deviation from the suggested mechanism. `runtime info -s SESSION -p PID`
was evaluated and rejected as the authority read because its document carries no `process_generation`
(`providers/topsailai/src/read.go:54-59`); generation exists only in the workspace row
(`read.go:31`). Replacing the workspace read with `runtime info` would therefore have removed the
generation comparison that this issue explicitly requires to remain.

The implemented shape decodes the opaque slot and scopes the authoritative read with
`workspace list --json --local -s <session>` (`mutation_authority.go:54-78`). It still matches the
durable Provider resource key, still rejects ambiguity and a missing row, and still compares the
requested generation before any mutation. The unrelated-row scan is removed; the safety check is not.

## Why this matters

The full workspace read is currently necessary only because exact selectors were discarded. Replacing
it with no revalidation would be unsafe; passing identity into an exact revalidation preserves safety
while removing unrelated work and reducing the chance that an unrelated malformed row blocks the
selected operation.
