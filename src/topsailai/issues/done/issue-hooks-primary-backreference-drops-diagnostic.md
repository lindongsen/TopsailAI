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

The aggregation contract now preserves every original exception object while representing contradictory topology explicitly. Before attaching the diagnostic beneath the primary, it detaches only direct cause or context edges that point back to that primary and adds a note to the affected original exception describing the detached edge. The diagnostic is then attached using the existing cause or BaseExceptionGroup aggregation path. This preserves primary identity and all original exception identities in an acyclic inspectable graph without pretending that both contradictory directed edges can coexist.

Initial-finalization and retry regressions assert the process, channel, and outer exception identities remain reachable, the primary identity is unchanged, the contradictory cause edge is detached with an explanatory note, and the complete cause/context/group graph has no recursion-path cycle. They also retain the established resource, debt, exact lease, and no-signal assertions.

## Verification

Focused primary-backreference regressions: 2 passed. Complete colorless focused Hooks suite: 122 passed in 16.14s. Compilation, whitespace, line-count, residual-process, and final diff checks are recorded in the Logical Unit 2 execution checklist.
