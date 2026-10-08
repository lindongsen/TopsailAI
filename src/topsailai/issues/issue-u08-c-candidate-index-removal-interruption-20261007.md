---
maintainer: AI
author: DawsonLin
status: pending
---

# Candidate index orphan after interrupted terminal removal

## Independent second review REJECTED - candidate index removal interruption

Reviewer: gpt56terra-programmer. All five changed-file diffs were inspected individually. Related manager release/reclaim/close/snapshot, mutation settlement, publication finalization, fixture and trace helper paths were inspected. No production or maintained test was changed.

The first-round mixed-prefix reproducer now passes: real captured active root plus fifteen public admissions followed by a captured candidate; at fixed clock 60, reclaim expires that candidate. Trusted admission settlement and public close converge to zero groups, versions, slots and candidate-index entries.

A new defect is independently confirmed in CandidateRegistryMixin._unregister_candidate: primary registry removal precedes candidate-index removal. A one-shot KeyboardInterrupt at the following candidate-index identity check, during public reclaim expiry of a real captured candidate, preserves the exact primary exception but leaves groups=0, candidate_index=1 and the exact group's settle mutation pending. No registry, authority or lock was replaced. Three public pressure reclaims with fresh valid deadline remove the artifact but skip the index orphan because _valid_group requires membership in the now-empty primary registry. Public close also only iterates that primary registry. It returns accepted=True, cleanup_pending=False and snapshot manager_state=closed/candidate_groups=0, while the exact candidate remains indexed with its mutation and captured-object references. Actual final registries: primary groups=0, candidate index=1, versions=0, physical slots=0. This violates dual-registry settlement and honest lifecycle closure. The probe exited 0 after explicitly asserting DEFECT_CONFIRMED, not product correctness.

Root cause: new candidate-index removal was composed after loss of primary discoverability, without making the remaining indexed mutation reachable to maintenance/close or included in pending/closed checks. Existing newly added tests inject registration only, not removal; their first-write line event occurs BEFORE the assignment, so it does not itself prove interruption after the first write. Add exact after-first-write and actual return-handoff controls as well as removal recovery controls. Do not fix by dropping pins, silently clearing unrelated entries or relying on a caller retaining the group and invoking private compensation.

Verdict REJECTED. Return to designated Developer gpt56sol-programmer. Remaining dependency/test-file reviews, broader lifecycle probes, ordered gate and seven/eight-module coverage were NOT completed after product-defect confirmation. Developer's 356-pass gate and coverage percentages are not independent evidence in this round. No Git commit or Human acceptance is claimed. Evidence: current session event tool output includes PREFIX_PASS, INTERRUPTION_OBSERVED, three RECLAIM results, CLOSE, SNAPSHOT, ACTUAL_REGISTRIES and DEFECT_CONFIRMED.


## Developer repair — pending independent verification

Developer: gpt56sol-programmer. Date: 2026-10-07. The issue remains pending until an independent Reviewer approves it; no commit or Human acceptance is claimed.

Root cause: exact terminal settlement removed `_groups[group_id]` before `_candidate_groups[group_id]`, but the remaining candidate-index entry was not treated as recovery custody. An interruption between removals therefore made the armed settle mutation unreachable from public lifecycle operations and invisible to closure reporting.

Repair: `hooks/artifact_retention.py:28-47` preserves the settle journal through primary removal, clears it only at the final exact index removal boundary, and reconciles every bounded indexed object before applying primary-registry validity checks. `hooks/artifact_leases.py:448,492-518,681-691` includes candidate-index custody in close, snapshot, cleanup-pending, and closed-state decisions. `hooks/artifact_lease_transactions.py:55-84` retains exact settlement custody until unregister finishes, and `hooks/artifact_publication.py:288-295` removes only the exact activated candidate. This keeps all interruption remnants publicly recoverable without scanning the mixed registry or discarding unrelated pins.

RED evidence was `1 failed, 4 passed, 9 deselected`, with the rejected implementation retaining one hidden index entry and settle mutation after primary removal. GREEN tests cover interruption before primary removal, between registry removals, after index removal, and a public-reclaim recovery without trace instrumentation. Candidate registration tests now prove an actual after-first-write interruption and the `begin_candidate()` return-handoff boundary. The prior mixed active/admitted-prefix regression and all retention/order/pin controls remain green.

Developer verification: retention `15 passed`; retention plus publication `51 passed`; complete normal-order artifact gate `360 passed in 7.47s`; seven-module combined line-plus-branch coverage `93.34428923582581%`; eight-module combined coverage `93.15384615384616%`. Mechanical checks pass, relevant files remain below 700 lines, staged paths are empty, HEAD is unchanged, and no commit was made. Next action: independent review by gpt56terra-programmer.
