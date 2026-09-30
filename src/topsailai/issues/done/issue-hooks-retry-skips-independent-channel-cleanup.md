---
maintainer: AI
author: DawsonLin
---
# Cleanup debt retry skips independent channel closure

Status: resolved; fixed and verified in the follow-up Logical Unit 2 change.

## Finding

In `hooks/process_backend.py:138-145`, `retry_cleanup()` returns immediately when `process.poll()` raises OSError. Channel closure at line 149 is skipped. An exception from termination can likewise bypass channel closure because that operation is not protected by an independent finally block. Debt-state restoration does not close retained resources.

## Independent reproduction

Register a LaunchRecord with a real owned pipe read descriptor and a fake process whose poll raises OSError. Invoke the real retry_cleanup with killpg mocked. The result is False, debt remains pending, result channel remains open, and os.fstat on the owned descriptor succeeds. No subprocess or actual signal is used. The probe explicitly closes its resources afterward.

Evidence: `.tmp/hooks-241346-review/probe.txt`. Complete focused colorless suite: 105 passed in 13.45s; the existing suite does not cover this combination. Thirty Python files pass syntax, line-count and trailing-whitespace checks; target commit passes git show --check; no worker/fake-worker module processes found after the run.

## Required correction

While holding the exact cleanup lease, attempt channel closure independently of process inspection or termination failure. Preserve uncertain process debt and restore its pending claim; never signal solely from historical PGID. Preserve host-interruption propagation after independent cleanup. Add real descriptor and stream assertions for poll OSError and termination exception/interruption cases, not only pending-debt assertions.

## Resolution

Resolved by making process settlement and channel closure independent operations under the same exact cleanup lease. Ordinary process failures retain pending debt and return `False`; host interruptions propagate only after channel cleanup; signal authorization is unchanged. Deterministic regressions verify real stream and raw-fd closure for poll errors, ordinary termination exceptions, and interruptions, together with retained debt, released lease state, and no signals.

Verification: complete focused colorless suite `108 passed in 14.81s`; compilation, whitespace, line-count, and residual-process checks passed. Evidence is under `.tmp/hooks-retry-independent/`.

## Review boundary

Initial and escalation signal checks now precede killpg, and the obsolete independent acquisition-return path is absent. This review stops at the confirmed retry resource-cleanup blocker and does not grant full semantic acceptance or authorize Dispatcher/Runtime/lifecycle.
