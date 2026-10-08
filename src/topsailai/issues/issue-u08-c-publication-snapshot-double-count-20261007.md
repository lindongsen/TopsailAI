---
maintainer: AI
author: DawsonLin
status: pending
---

# Interrupted activation double counts candidate and active group

## Third independent review REJECTED - publication snapshot double count

Reviewer: gpt56terra-programmer. All five U08-C changed-file diffs were reviewed individually. The approved revision explicitly requires that STAGED candidates count as candidates until the committed decision and that unfinalized metadata derives counts from that decision, never counting both states.

Confirmed regression: hooks/artifact_leases.py snapshot now reports len(_candidate_groups), while active_groups still comes from primary group states. In hooks/artifact_publication.py:291-293, setting candidate._state to active precedes exact candidate-index removal. A host interruption at line 292 leaves the same exact group active AND indexed. A real-filesystem capture, fixed clock 0.0, issued PublicationCell/Stage and one-shot line interruption reproduced snapshot candidate_groups=1, active_groups=1, publication_stages=1 with exactly one group and cell.current already the replacement image. No registry, lock or authority was replaced. This is a new observability regression introduced by combining the new index-length snapshot with multi-statement publication finalization; it does not establish premature artifact deletion.

The fresh confirmation probe exited 0 after asserting DEFECT_CONFIRMED, then used the issued publication reconciliation API and public close(deadline=1.0). Final snapshot was closed with all group/token/version/slot/stage counts zero and both registries empty; captured directory absence was confirmed. The initial probe also confirmed the defect and closed successfully, but its final check incorrectly accessed lease.directory after release and raised RuntimeError; it is not a passing probe. The corrected run saved the path before release and used an entirely fresh fixture.

The changed retention tests cover terminal removal but do not assert snapshot exclusivity during interrupted activation. Their registration return_handoff case still injects a line event BEFORE evaluating the return expression, not a true function-return event or first receiver instruction; do not claim actual return-handoff coverage from that test.

Stop-on-confirmed-defect applies. Prior-prefix and terminal-removal scenarios were inspected but NOT independently rerun in this round. Remaining U08-B dependency/test-file reviews, ordered gate and both coverage scopes were NOT completed; Developer numbers are not independent evidence. Verdict REJECTED; return to gpt56sol-programmer for a decision-aware snapshot fix preserving candidate-index recovery custody and a real publication-interruption regression. No production or maintained test edits, staging or commits. HEAD 2091b10eb739d651a7c0aabf3ac604cea352e57c; staged empty; git diff --check clean; five changed files have 699/69/84/301/392 lines. Human acceptance remains outstanding.


## Developer repair — decision-aware mutually exclusive snapshot classification

Developer: gpt56sol-programmer. Status: fixed in the uncommitted worktree and awaiting renewed independent review; this issue is not yet accepted or closed.

Root cause: `_candidate_groups` is both a bounded maintenance index and exact recovery custody, while primary group state is transient publication bookkeeping. After the immutable publication decision but before exact index removal, combining index cardinality with state cardinality classified one replacement in both categories.

Repair: snapshot now derives candidate and active counts through the publication protocol. When a charged stage is decided because `PublicationCell.current` is the exact replacement image, the replacement candidate is excluded from candidate count despite retained recovery custody and is counted once as active; exact old roots removed by the replacement are excluded from active count; and a decided no-op candidate counts in neither category. Outside an unfinished decided stage, ordinary candidate-index and lifecycle-state classification remains unchanged. The recovery index, exact-identity deletion, bounded sixteen-position traversal, close convergence and cleanup-pending duties remain intact.

RED was `2 failed, 36 deselected`, reproducing the extra candidate count at the distinguishing interruption windows. GREEN regressions cover before active assignment, between active assignment and candidate-index deletion, and after candidate-index deletion before old-root retirement. Non-trace changed/no-op controls exercise the same classifier. The registration test formerly described as a real `return_handoff` is corrected to `before_return`, because its line trace occurs before return-expression evaluation.

Final Developer evidence: focused retention plus publication `56 passed in 1.10s`; complete ordered artifact gate `365 passed in 7.62s`; seven-module combined coverage `93.55358581788880%` (`879/923` lines and `282/318` branches); expanded eight-module combined coverage `93.35347432024169%` (`935/982` lines and `301/342` branches). Both coverage runs passed `98` tests with `59` trace-dependent instances deselected; all of those instances passed in the uninstrumented gate. Mechanical checks pass, staged count is zero, HEAD is unchanged at `2091b10eb739d651a7c0aabf3ac604cea352e57c`, and no commit was made.

Next action: fourth independent U08-C review by gpt56terra-programmer. Keep this issue pending until that review is approved; Human acceptance remains separate.
