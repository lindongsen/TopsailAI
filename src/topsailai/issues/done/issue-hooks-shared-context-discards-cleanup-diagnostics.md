---
maintainer: AI
author: DawsonLin
---
# Shared exception context discards cleanup diagnostics

Status: resolved

## Scope

Strict review of ffde9caf791fe65988fc318c56cc19ade664406e, Hooks Logical Unit 2. No downstream authorization.

## Confirmed cause

hooks/process_cleanup.py:246-248 returns without attaching any additional diagnostic when the primary and additional exception graphs share any node. Shared ancestry is not a cycle: cleanup invoked while handling an outer exception naturally gives independently raised cleanup errors the same __context__. The guard therefore discards a distinct ordinary process error even though it is not already reachable from the primary interruption.

## Independent reproduction

Invoke production _finish_record or retry_cleanup inside an except LookupError block. Use a simulated process, two real pipe streams and one real raw pipe descriptor. Termination raises RuntimeError('process ordinary'); the post-close stdin seam raises ValueError('channel ordinary'); the post-close stdout seam raises the exact KeyboardInterrupt('channel interrupt') instance. Both entry paths propagate that exact interruption and retain the channel error plus active outer failure, but lose the process RuntimeError across cause, context and exception-group traversal. Both streams and raw fd close, lease is (None, 0), and genuine process debt remains pending. No subprocess or signal is used.

Observed for both initial and retry: primary_identity=True, process_error_retained=False, channel_error_retained=True, cycles=[].

## Test gap and correction

The new tests execute without an active outer exception. Their helper visits only causes and groups, not contexts; uniqueness of message strings does not establish identity preservation or absence of graph cycles. Add initial/retry active-exception regressions and identity-based graph traversal with a recursion-stack cycle check. Preserve all unique diagnostics when graphs share ancestors; distinguish shared DAG nodes from back edges rather than returning on any intersection. Also review the no-existing-cause branch, which bypasses the overlap check. Do not alter resource ownership, debt or signal authorization.

## Verification and review boundary

Independent full focused colorless suite: 116 passed in 14.19s. Log: .tmp/hooks-ffde-review/suite.log. Target commit git show --check passed. Latest production/test diff, resolved prior issue and local checklist inspected. Confirmed blocker stops broader cumulative acceptance; no claim of final verification of all prior process guarantees or residual resources.

## Resolution

Replaced whole-graph intersection suppression with directional identity reachability checks. Both absent-cause and existing-cause paths now use one safe attachment routine that appends at the explicit-cause tail only when the candidate cannot reach that tail; legal shared context ancestors remain intact. Initial and retry regressions run cleanup inside an active outer exception and assert primary interruption identity, identity-level retention of every original exception, no recursive-path cycle, real channel closure, pending genuine debt, exact lease release, and zero signals.

Verification: complete focused colorless Hooks suite `118 passed in 15.41s`; all 31 Hooks source and focused-test files compiled into `.tmp`, all files remain below 700 lines, diff/whitespace checks passed, and no focused worker residue was observed. Evidence: `.tmp/hooks-shared-context/`.
