---
maintainer: AI
author: DawsonLin
---
# Cleanup diagnostic pointing to primary is discarded

Status: resolved

## Scope

Strict review of commit 6bac87b3de5dff9fc0a5820c1b5447eea3016ddc, Logical Unit 2.

## Confirmed finding

In hooks/process_cleanup.py, _append_cleanup_diagnostics returned when additional reached primary. This silently discarded an independent original diagnostic. The aggregate fallback fixed a shared cause-chain tail but not this branch.

## Independent reproduction

For both _finish_record and retry_cleanup, a process RuntimeError had an explicit cause pointing to a precreated primary KeyboardInterrupt. Termination raised the process error, stdin post-close raised a separate ValueError, and stdout post-close raised that same KeyboardInterrupt inside an outer LookupError handler.

Both paths retained resource safety but made the process error unreachable from the propagated interruption.

## Resolution

The aggregation contract preserves every original exception object while representing contradictory topology explicitly. Before attaching a diagnostic beneath the primary, it detaches a mutable cause or context edge whenever that edge's complete cause/context/group graph reaches the primary. A PEP 678 note records the detached edge type. When the detached target is not the primary itself, the exact original target is retained by identity in the affected exception's `__cleanup_detached_diagnostics__` sidecar, which is intentionally outside the directed cause/context/group graph because making a group that contains the primary reachable from the primary would necessarily create a cycle.

If the diagnostic root is itself a direct or nested `BaseExceptionGroup` containing the primary, no mutable edge can remove the immutable group-member backreference. The complete graph is therefore rechecked after mutable-edge detachment; a still-contradictory root diagnostic is retained by identity in the primary's same outside-graph sidecar, and a PEP 678 note records that representation. This prevents the previous `existing is None` path from silently discarding the group or its independent members.

This covers direct backreferences, indirect backreferences through immutable group membership, and diagnostic groups whose own direct or nested members contain the primary. The process, channel, outer, group, independent group members, and primary objects remain inspectable by identity; primary propagation remains unchanged; and the standard cause/context/group graph is acyclic.

Initial-finalization and retry regressions cover every backreference form. They assert original exception identities, explicit notes and sidecar representation, complete cause/context/group recursion-path safety, resource closure, genuine debt retention, exact lease release, and absence of unauthorized signals.

## Verification

Focused primary-backreference regressions: 8 passed. Complete colorless focused Hooks suite: 128 passed in 14.34s. All 32 Hooks source and focused-test Python files compiled successfully; whitespace, line-count, residual-process, and final diff checks are recorded in the Logical Unit 2 execution checklist.
