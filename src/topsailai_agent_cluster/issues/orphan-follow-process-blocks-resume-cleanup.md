---
maintainer: AI
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: AGENT_CLUSTER
programming_language: go
status: resolved
severity: high
---

# Orphan follow process blocks resume cleanup

## Symptom

After `resume` succeeds, an invalid Session can remain in `list` because an old Session stdout file is still considered in use.

## Reproduction

A Generic CLI Adapter invocation starts a Provider CLI. The Provider starts its business CLI in a separate process group. When the outer follow deadline expires, the Adapter kills only the Provider process group. The separate business process group survives, becomes orphaned, and keeps the old stdout file open.

## Actual behavior

The outer invocation returned after its own process group disappeared, while a descendant process group remained alive. Provider-side resume cleanup saw `is_file_in_use=true` and preserved the stale stdout file.

## Expected behavior

Before a timed-out or cancelled Provider invocation returns, every invocation-owned helper process and file descriptor is gone, including descendants that created a separate process group.

## Root cause

The Generic CLI Adapter used the Provider PID as a process-group ownership boundary. A Provider is allowed to create another process group for its business CLI, so the outer boundary did not include every invocation helper. Killing the Provider with `SIGKILL` also prevented Provider cleanup code from running.

## Resolution

On Linux, each Provider invocation now starts in a dedicated process session. Cleanup enumerates `/proc` for every process group that still belongs to that session, sends `SIGKILL` to each exact group, and waits until the session has no members. The common wait path applies the same post-exit check to unary and streaming invocations, including validation, callback, timeout, cancellation and normal Provider-exit paths. Other Unix platforms keep the previous process-group fallback.

## Verification

`TestInvokeStreamTimeoutKillsSeparateDescendantProcessGroup` starts a Provider helper that creates a second process group and opens a Session stdout fixture. The fixed implementation passed three consecutive runs. Replacing the session boundary with the old process-group boundary made the test fail with `detached provider helper <pid> survived invocation cleanup`; restoring the fix made it pass again.
