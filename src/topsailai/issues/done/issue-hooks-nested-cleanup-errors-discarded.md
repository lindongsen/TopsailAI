---
maintainer: AI
author: DawsonLin
---
# Nested cleanup aggregation discards later failures

Status: done

## Scope

Strict review of ddd65cc7e223f206cea559fc5642b086058b4fb2. Logical Unit 2 remains rejected; no authorization for Dispatcher or integrations.

## Confirmed defect

In hooks/process_cleanup.py, _retain_cleanup_error extracts the incoming interruption's ordinary cause only when no interruption is already retained, then returns the first interruption. Consequently an earlier process KeyboardInterrupt discards a later channel KeyboardInterrupt and its ordinary error cause. _raise_cleanup_errors also raises only ordinary_errors[0] when no interruption exists, losing additional ordinary failures across nested aggregation.

## Independent reproduction

Invoke production _finish_record with a simulated process owning two real unbuffered pipe streams and a real raw pipe descriptor. Override _terminate_owned to raise KeyboardInterrupt('process interrupt'). Override _after_channel_close to raise RuntimeError('ordinary channel error') after stdin and KeyboardInterrupt('channel interrupt') after stdout. No subprocess is launched and no process signal is sent.

Observed: propagated KeyboardInterrupt('process interrupt'), cause=None, context=None. Both streams and the raw descriptor are closed, all channels are closed, genuine process debt is pending, execution_owner=None and execution_depth=0. The ordinary failure and later interruption are not reachable from the propagated exception.

## Required correction

Preserve errors across nested cleanup aggregation even when an interruption already exists. Keep the primary host interruption behavior while making every retained ordinary failure and additional interruption observable through an explicit chain or suitable aggregation. Continue all independent cleanup, release the exact lease, preserve only genuine debt, and do not relax signal authorization. Add real-channel regressions for process interruption followed by ordinary channel error and channel interruption through both initial finalization and retry; also test multiple ordinary failures without interruption.

## Evidence

Independent full focused colorless suite: 110 passed in 14.31s. Log: .tmp/hooks-ddd65-review/suite.log. All 31 Hooks source and focused-test Python files pass AST parsing and are below 700 lines. Target commit passes git show --check. Previous two mixed-failure regressions pass but do not cover an already-retained interruption receiving a nested aggregate. Review stopped at the confirmed blocker; cumulative protocol, historical-test semantics, full diff and residual-resource acceptance are not claimed complete.

## Resolution

Cleanup aggregation now retains the primary host interruption while exposing every later ordinary error and additional interruption through explicit cause/group structures. Ordinary-only cleanup retains all failures in an `ExceptionGroup`. Initial finalization and retry regressions use real streams and raw pipe descriptors, verify complete independent cleanup, pending genuine debt, exact lease release, and zero unauthorized signals.

Verification: complete colorless focused Hooks suite `114 passed in 14.13s`; compile, diff/whitespace, line-count, and residual-process checks passed. Evidence is stored under `.tmp/hooks-nested-errors/`.
