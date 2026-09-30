---
maintainer: AI
author: DawsonLin
---
# Cleanup aggregation overwrites an existing interruption cause

Status: resolved

## Scope

Strict acceptance of commit 8f90827661be1520c490e4cc2d492de247954e0b, Logical Unit 2. No authorization for Dispatcher or integrations.

## Confirmed defect

In hooks/process_cleanup.py, _raise_cleanup_errors raises the primary interruption from newly collected diagnostics without preserving its existing cause. When process cleanup raises an ordinary error and channel cleanup aggregates an ordinary channel error followed by KeyboardInterrupt, the outer aggregator replaces the channel interruption cause with the process error. The channel error is no longer reachable through cause, context, or exception groups. Both _finish_record and retry_cleanup reproduce this.

## Independent evidence

Full focused colorless suite: 114 passed in 13.81s; log: .tmp/hooks-8f908-review/suite.log.

A production-entry probe used two real pipe streams and one raw pipe descriptor with a simulated process. Termination raised RuntimeError("process ordinary"); post-close stdin raised ValueError("channel ordinary"); post-close stdout raised KeyboardInterrupt("channel interrupt"). For both initial and retry cleanup, reachable errors were only ["channel interrupt", "process ordinary"]. All streams and the raw descriptor closed; exact lease became (None, 0); genuine process debt remained pending. No subprocess was started or signal sent.

## Required correction

Preserve the complete existing diagnostic graph when adding outer-layer errors, without overwriting causes, introducing cycles, or losing the primary interruption identity. Add deterministic initial and retry regressions for ordinary process error followed by ordinary channel error and channel interruption, checking every original exception remains inspectable. Retain the opposite ordering and multiple-ordinary regressions. Do not change signal authorization or cleanup ownership.

## Review boundary

Blocking root cause confirmed; broader cumulative acceptance stopped. The passing suite does not establish full acceptance of historical guarantees.

## Resolution

The cleanup aggregator now appends disjoint outer diagnostics to the existing explicit cause chain instead of replacing it, after checking the complete cause, context, and exception-group graph for overlap to avoid cycles. Deterministic initial-finalization and retry regressions preserve the channel interruption identity and expose both ordinary process and channel failures while confirming real channel closure, exact lease release, genuine pending debt, and zero signals. The complete focused colorless Hooks suite passed with 116 tests; verification evidence is stored under `.tmp/hooks-existing-cause/`.
