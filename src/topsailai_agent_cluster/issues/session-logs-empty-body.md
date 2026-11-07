---
maintainer: AI
author: DawsonLin
---

# Session-scoped logs return an empty body while provider output exists

## Trigger

Observed during live tmux verification of the adapter-owned project launch unit. A real hello task was
submitted, the provider consumed it and produced a model response, but a session-scoped output snapshot
returned an empty body.

## Observed behavior

- Provider stdout/events contain the model response for the session.
- The cluster's session-scoped logs read returns an empty body for the same session.

## Impact

An operator reading session output through the cluster sees nothing even though the agent produced a
response. This is the primary observation surface for a running agent, so an empty body is
indistinguishable from "the agent produced no output".

## Constraint

Do not infer absence of output from an empty snapshot. The provider is authoritative for whether output
exists; an empty cluster read is an observation gap until proven otherwise.

## Open question

Whether the defect is on the cluster side (wrong source selection, wrong cursor/tail semantics, wrong
session-to-file mapping) or on the provider side (the session-scoped read genuinely has no content for
this session) is not yet determined. Resolve that boundary before changing either side.

## Evidence

Live tmux evidence remains under the task temporary live directory.

## Status

Open. Deferred by human decision: the boundary between cluster-side and provider-side behaviour must be
confirmed before any change. Extracted from `adapter-project-launch.md` when that issue was archived, so
the observation is not lost with the resolved parent issue.
