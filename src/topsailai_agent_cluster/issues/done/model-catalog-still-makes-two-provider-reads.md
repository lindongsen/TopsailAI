---
maintainer: AI
author: DawsonLin
status: done
created: 2026-11-19
---

# Model catalog still makes two Provider reads after exact identity reaches it

## Symptom

An online session's `model` catalog still starts two TopsailAI business CLI calls even though the
`agent.models` instruction now returns the supported model list and the current model together.
Passing `provider_session_id` and `provider_pid` removed the earlier `workspace list` identity scan,
but the read has not yet reached the requested one-step shape.

## Evidence

- `providers/topsailai/src/query.go:334` invokes `models list --json`.
- `providers/topsailai/src/query.go:345` then calls `currentModelName`.
- `providers/topsailai/src/model_current.go` implements that second read through the `agent.llm`
  instruction.
- The current `agent.models` JSON payload in the TopsailAI project returns `models[]`, each row's
  `current` flag, and top-level `current_model` in one control call.
- `TestModelCatalogUsesTheSuppliedIdentityWithoutDiscovery` currently expects two Provider calls, so
  it proves identity discovery was removed but also pins the remaining duplicate read.

## Root cause

The model catalog was originally assembled from two separate sources: a registry document for the
list and a live instruction for the current selection. After `agent.models` gained structured output,
the Provider integration kept the old composition instead of adopting the new single-call surface.

## Required direction

For an online session, call `agent.models` once with the exact provider session ID and PID and build
both the list and current flags from that response. Per the human-directed contract, entries returned
by this instruction are available by default; do not issue `models list` merely to reconstruct the
same catalog.

The offline path remains separate: use `topsailai models list` for the supported list and
`topsailai session info --json <session_id>` for the current model.

## Why this matters

The standing project requirement is “one step to the answer”: when one authoritative operation
returns the complete fact needed by the caller, a second read is unnecessary work and adds latency,
extra failure modes and another source that can disagree.
