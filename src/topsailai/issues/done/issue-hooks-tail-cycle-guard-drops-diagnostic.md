---
maintainer: AI
author: DawsonLin
---
# Tail cycle guard drops an independent cleanup diagnostic

Status: resolved

## Scope

Strict review of fb32ec373bde525bc0ea257471e68adf08193e08, Logical Unit 2 only.

## Confirmed defect

In hooks/process_cleanup.py, _append_cleanup_diagnostics returns when additional reaches the existing cause-chain tail. Rejecting that particular edge avoids a cycle, but silently loses an independent diagnostic instead of retaining it through another inspectable aggregation structure. A valid acyclic input graph can have primary interruption -> channel ordinary error and process ordinary error -> the same channel ordinary error. Appending channel error -> process error would cycle; this does not justify dropping the process error.

## Independent reproduction

For both production _finish_record and retry_cleanup, use a simulated process, two real pipe streams and one raw result pipe descriptor. Precreate channel ValueError, process RuntimeError whose explicit cause is that ValueError, and channel KeyboardInterrupt. Termination raises the process error; post-close stdin raises the channel error; post-close stdout raises the interruption. Invoke inside an outer LookupError handler. Traverse cause, context and exception-group edges by object identity and detect cycles with an active recursion path.

Both paths report primary_identity=True, process_retained=False, channel_retained=True, cycles=False. Both streams and raw descriptor close, exact lease becomes (None, 0), and genuine process debt remains pending. No subprocess or process-group signal is used.

## Required correction

Preserve every original independent diagnostic when a chosen tail link would cycle; use another inspectable aggregation arrangement instead of silently returning. Preserve primary interruption identity and existing diagnostic reachability. Add initial and retry regressions for shared explicit causes, with identity-based retention and graph-cycle assertions; retain the shared outer-context tests and previous ordering tests. Do not change resource ownership, debt or signal authorization.

## Verification boundary

Independent complete focused colorless suite: 118 passed in 14.83s. Log: .tmp/hooks-fb32-review/suite.log. Target git show --check passed. Latest cleanup diff, implementation, backend/state, exception tests, checklist and prior issue inspected. Confirmed blocker stops cumulative acceptance; protocol/deadline, all historical tests, compilation/line counts and residual-resource final acceptance are not claimed. No downstream implementation is authorized.

## Resolution

When the existing cause-chain tail cannot safely point to a new diagnostic, cleanup now preserves the original cause and the independent diagnostic as siblings in an acyclic `BaseExceptionGroup` attached to the primary interruption. Initial-finalization and retry regressions assert every original exception by identity, no recursion-path cycle, all channels closed, genuine debt retained, exact lease released, and no signal sent. The complete focused Hooks suite passed with 120 tests.
