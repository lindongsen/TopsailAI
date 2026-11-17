---
maintainer: AI
author: DawsonLin
status: resolved
---

# U08-C expired candidates starve behind live groups
 gpt56terra-programmer. Product defect confirmed; stop-on-defect applies. This is not Human acceptance.

The changed manager and retention-test diffs were inspected. At artifact_leases.py:666, tuple(self._groups.values())[:_MAX_CANDIDATES] always selects the same registry prefix, which includes active and admitted groups. It also materializes the complete registry before slicing, so the snapshot construction is not limited to sixteen positions (the separate global group cap is 4096).

An independently executed real-filesystem probe created one captured active root through the existing publication protocol, fifteen groups through public admit((active,)), then a second captured candidate. No registry, authority, or lock was replaced. With an injected clock advanced from 0 to 60, three public reclaim(deadline=61, pressure=False) calls all returned accepted with removed=0. After each call the expired candidate remained candidate and its lease remained unreleased. Final snapshot: candidate_groups=1, active_groups=1, admitted_groups=15, live_tokens=17, capture_slots=2, stored_versions=2, retired_versions=0, pending_captures=0, publication_stages=0. Active bytes remained present. This proves permanent prefix starvation while those admitted groups remain live; the candidate cannot start its last-release retention clock through maintenance.

The added sixteen-position test only creates sixteen candidates. Its _valid_group call counter neither observes full tuple materialization nor exercises non-candidate prefix starvation. Add mixed-state registry regressions and bounded-progress evidence. Repair must maintain the approved candidate-position scan bound without evicting pins or weakening exact custody; do not merely scan all 4096 groups as a substitute.

Verdict: REJECTED. Return to gpt56sol-programmer. Remaining per-file dependency/test review, broader independent lifecycle controls, ordered gate, and seven/eight-module coverage were NOT completed after defect confirmation; Developer figures are not independent evidence from this review. Public close convergence was not asserted by this reproducer. No production or maintained test files were changed, staged, or committed.


## Developer repair — 2026-10-07

The fixed mixed-registry prefix has been replaced by a separately bounded exact-identity candidate index. Candidate creation, activation, and terminal settlement maintain the index under the manager lock, while expiry maintenance reads at most its sixteen positions and never traverses active/admitted registry entries. A real capture/public-admission regression with one active group, fifteen admitted groups, and one later expired candidate now examines and settles exactly that candidate. Dual-registry interruption rollback is covered at partial publication and successful-return boundaries. Focused tests, the 356-case ordered gate, and both coverage scopes pass. The repair is uncommitted and awaits renewed independent review; the issue is not yet closed or Human-accepted.

## Closure verification (2026-11-17)

Resolved in HEAD. The repair described above as "uncommitted" is committed.

- `d2ec3e22 feat: bound artifact retention maintenance` (2026-10-07) is an ancestor of HEAD `5da6bb49f651a501b041486590a0c87e5acd85c6`.
- `hooks/artifact_retention.py:20-54` now holds `CandidateRegistryMixin` with a separate
  `_candidate_groups` index. `_register_candidate()` maintains it on creation and activation;
  `_unregister_candidate()` removes it at terminal settlement.
- Expiry maintenance reads at most the sixteen candidate positions and never traverses
  active or admitted registry entries, so a live admitted prefix can no longer starve an
  expired candidate.
- `tests/unit/test_topsailai_hooks/test_hook_artifact_retention.py` and
  `test_hook_artifact_publication_protocol.py` pass through the project runner:
  `Total=2, Passed=2, Failed=0`, 56 cases.

Note on running these tests: pytest's default basetemp lives under `/tmp`, which is mode
`0777`. `hooks/artifact_validation.py::_validate_directory_status` rejects any ancestry
directory carrying group or other write bits, so a direct `pytest` invocation reports
`trust_rejected` failures that are harness artifacts, not product defects. The project
runner uses `.tmp/unit-runner` (mode `0755`) and passes. Run these files through
`tests/run_tests.py`, or point `TMPDIR` at a `0700` directory.
