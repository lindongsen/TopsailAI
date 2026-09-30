---
maintainer: AI
author: DawsonLin
---
# Cleanup exception aggregation masks host interruption

Status: resolved

## Review scope

Strict acceptance review of commit 4072a7f88cd74e3a40796f581d62d3a56d8e754f and cumulative Hooks Logical Unit 2. The previous independent retry-channel cleanup defect is fixed; this is a separate cumulative acceptance blocker.

## Confirmed finding

In hooks/process_cleanup.py lines 185–198, _close_record_channels retains only the first exception. An ordinary exception from an earlier channel therefore masks a later KeyboardInterrupt from another channel. retry_cleanup then receives only the ordinary exception, discards it, and can return True if termination and channels are confirmed. The host interruption is never propagated. The same first-exception selection pattern in _finish_record lines 101–129 must also be checked for ordinary process failure followed by channel interruption.

## Deterministic independent reproduction

Invoke real retry_cleanup with a LaunchRecord containing two real unbuffered pipe streams and one real raw pipe descriptor. Mark process termination confirmed so no process or signal operation is needed. Override the existing _after_channel_close seam: raise RuntimeError after stdin closes and KeyboardInterrupt after stdout closes. Both streams and the result descriptor pass through the production channel-close implementation.

Observed: retry_result=True; host_interruption_propagated=False; streams_closed=[True, True]; all four channel states=closed; debts=(); execution_owner=None; execution_depth=0. All probe descriptors were closed; no subprocess was launched and no signal was sent.

## Required correction

Preserve host interruption independently from ordinary cleanup errors across channel aggregation and outer cleanup finalization. Continue attempting every independent resource, release the exact lease, preserve any genuinely unsettled debt, and then propagate the host interruption rather than replacing it with an earlier ordinary error. Do not fabricate debt for resources already confirmed settled or weaken process-group signal authorization.

Add deterministic mixed-failure regressions using real channels: earlier ordinary channel error plus later KeyboardInterrupt, and ordinary process/termination failure plus channel KeyboardInterrupt through initial finalization. Assert actual resource closure, correct debt outcome, exact lease release, and interruption propagation.

## Verification and acceptance

Independent full focused colorless suite: 108 passed in 14.41s. Log: .tmp/hooks-4072-review/suite.log. All 31 Hooks source and focused-test Python files pass AST parsing and are below 700 lines. Target commit passes git show --check. Existing tests do not cover mixed exception priority. Acceptance is REJECTED; Dispatcher/Runtime/lifecycle remains unauthorized. Broader semantic review stopped at the confirmed blocker; no claim of complete cumulative acceptance is made.

## Resolution

Ordinary cleanup failures and non-`Exception` host interruptions are now retained independently in channel aggregation, initial finalization, and debt retry. Every independent cleanup attempt runs before the host interruption is raised; ordinary failures remain observable through explicit exception chaining, with multiple ordinary failures grouped. Real-pipe regressions prove channel closure, exact lease release, correct resolved-versus-pending debt state, and zero unauthorized signals for both reported mixed-failure orders.

Verification: final focused mixed-failure file `5 passed in 0.23s`; final complete colorless Hooks suite `110 passed in 13.39s`; compilation, whitespace, line-count, diff, and residual-process checks passed. Evidence is under `.tmp/hooks-interruption-priority/`.
