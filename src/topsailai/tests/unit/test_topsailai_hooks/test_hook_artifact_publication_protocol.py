"""Publication-decision tests for U08 artifact lease metadata."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from tests.unit.test_topsailai_hooks.artifact_lease_helpers import (
    activate,
    captured_candidate,
    lease_fixture,
)
from tests.unit.test_topsailai_hooks.artifact_trace_helpers import composed_line_interruption
from topsailai.hooks.artifact_publication import (
    ArtifactPublicationMixin,
    PublicationCell,
    PublicationImage,
)


def test_stage_abort_restores_candidate_and_changed_commit_retires_old_root(
    tmp_path: Path,
) -> None:
    """Keep old authority before decision and switch roots with one image swap."""
    manager, requests, policy = lease_fixture(tmp_path)
    first, _ = captured_candidate(manager, requests, policy)
    first_cell = activate(manager, first)
    second, _ = captured_candidate(manager, requests, policy)
    replacement = PublicationImage(2, object(), (second,))
    staged = manager._stage_publication(
        first_cell, second, expected=first_cell.current,
        replacement=replacement, old_groups=(first,), changed=True,
    )
    assert staged.accepted and staged.stage is not None
    assert second.state == "staged" and first.state == "active"
    assert manager._abort_publication(staged.stage).accepted
    assert second.state == "candidate" and first_cell.current.lease_roots == (first,)
    staged = manager._stage_publication(
        first_cell, second, expected=first_cell.current,
        replacement=replacement, old_groups=(first,), changed=True,
    )
    assert staged.accepted and staged.stage is not None
    assert manager._commit_publication(staged.stage).accepted
    assert first_cell.current is replacement and second.state == "active"
    assert first.state == "retired"


def test_noop_publication_consumes_candidate_without_generation_change(
    tmp_path: Path,
) -> None:
    """Use a distinct image identity as the no-op candidate consumption decision."""
    manager, _, _ = lease_fixture(tmp_path)
    candidate = manager.begin_candidate().group
    assert candidate is not None
    expected = PublicationImage(7, ("same",), ())
    cell = PublicationCell(expected)
    replacement = PublicationImage(7, ("same",), ())
    staged = manager._stage_publication(
        cell, candidate, expected=expected, replacement=replacement,
        old_groups=(), changed=False,
    )
    assert staged.accepted and staged.stage is not None
    assert manager._commit_publication(staged.stage).accepted
    assert cell.current is replacement and candidate.state == "settled"


def test_foreign_and_stale_publication_inputs_cannot_change_cell(tmp_path: Path) -> None:
    """Reject foreign images and duplicate post-abort decisions without mutation."""
    manager, _, _ = lease_fixture(tmp_path)
    candidate = manager.begin_candidate().group
    assert candidate is not None
    expected = PublicationImage(1, object(), ())
    cell = PublicationCell(expected)
    wrong = PublicationImage(1, object(), ())
    replacement = PublicationImage(2, object(), (candidate,))
    rejected = manager._stage_publication(
        cell, candidate, expected=wrong, replacement=replacement,
        old_groups=(), changed=True,
    )
    assert not rejected.accepted and cell.current is expected
    staged = manager._stage_publication(
        cell, candidate, expected=expected, replacement=replacement,
        old_groups=(), changed=True,
    )
    assert staged.accepted and staged.stage is not None
    assert manager._abort_publication(staged.stage).accepted
    assert manager._commit_publication(staged.stage).errors == ("invalid_publication_stage",)
    assert cell.current is expected


def test_publication_terminal_calls_are_exact_and_idempotent(tmp_path: Path) -> None:
    """Keep exact terminal stage semantics without retaining a public history."""
    manager, _, _ = lease_fixture(tmp_path)
    candidate = manager.begin_candidate().group
    assert candidate is not None
    expected = PublicationImage(1, object(), ())
    replacement = PublicationImage(2, object(), (candidate,))
    cell = PublicationCell(expected)
    staged = manager._stage_publication(
        cell, candidate, expected=expected, replacement=replacement,
        old_groups=(), changed=True,
    )
    assert staged.accepted and staged.stage is not None
    stage = staged.stage
    assert manager.snapshot().publication_stages == 1
    assert manager._commit_publication(stage).accepted
    duplicate = manager._commit_publication(stage)
    assert duplicate.accepted and duplicate.already_settled
    assert manager._abort_publication(stage).errors == ("publication_already_committed",)
    reconciled = manager._reconcile_publication(stage)
    assert reconciled.accepted and reconciled.already_settled
    assert manager.snapshot().publication_stages == 0

    candidate2 = manager.begin_candidate().group
    assert candidate2 is not None
    expected2 = cell.current
    replacement2 = PublicationImage(3, object(), (candidate2,))
    staged2 = manager._stage_publication(
        cell, candidate2, expected=expected2, replacement=replacement2,
        old_groups=(candidate,), changed=True,
    )
    assert staged2.accepted and staged2.stage is not None
    stage2 = staged2.stage
    assert manager._abort_publication(stage2).accepted
    duplicate_abort = manager._abort_publication(stage2)
    assert duplicate_abort.accepted and duplicate_abort.already_settled
    assert manager._commit_publication(stage2).errors == ("invalid_publication_stage",)
    reconciled_abort = manager._reconcile_publication(stage2)
    assert reconciled_abort.accepted and reconciled_abort.already_settled


def test_reconcile_uses_cell_identity_and_stage_blocks_close_and_admission(
    tmp_path: Path,
) -> None:
    """Resolve a decided image forward while rejecting partial lifecycle entry."""
    manager, requests, policy = lease_fixture(tmp_path)
    old, _ = captured_candidate(manager, requests, policy)
    cell = activate(manager, old)
    candidate, _ = captured_candidate(manager, requests, policy)
    replacement = PublicationImage(2, object(), (candidate,))
    staged = manager._stage_publication(
        cell, candidate, expected=cell.current, replacement=replacement,
        old_groups=(old,), changed=True,
    )
    assert staged.accepted and staged.stage is not None
    assert manager.close(deadline=manager._clock() + 1.0).errors == ("artifact_lease_busy",)
    assert manager.admit((candidate,)).errors == ("artifact_lease_busy",)
    cell.current = replacement
    result = manager._reconcile_publication(staged.stage)
    assert result.accepted and candidate.state == "active" and old.state == "retired"


def test_publication_rejects_malformed_roots_generation_and_expired_commit(
    tmp_path: Path,
) -> None:
    """Reject malformed plans and abort an expired candidate without a swap."""
    clock = [0.0]
    manager, _, _ = lease_fixture(tmp_path, clock=lambda: clock[0])
    candidate = manager.begin_candidate().group
    assert candidate is not None
    malformed = PublicationImage(0, object(), (object(),))
    malformed_cell = PublicationCell(malformed)
    malformed_result = manager._stage_publication(
        malformed_cell, candidate, expected=malformed,
        replacement=PublicationImage(1, object(), (candidate,)),
        old_groups=(), changed=True,
    )
    assert malformed_result.errors == ("invalid_publication_stage",)
    assert malformed_cell.current is malformed and candidate.state == "candidate"
    assert manager.snapshot().publication_stages == 0

    expected = PublicationImage(4, object(), ())
    cell = PublicationCell(expected)
    wrong_roots = PublicationImage(5, object(), ())
    assert manager._stage_publication(
        cell, candidate, expected=expected, replacement=wrong_roots,
        old_groups=(), changed=True,
    ).errors == ("invalid_publication_stage",)
    wrong_generation = PublicationImage(8, object(), (candidate,))
    assert manager._stage_publication(
        cell, candidate, expected=expected, replacement=wrong_generation,
        old_groups=(), changed=True,
    ).errors == ("invalid_publication_stage",)
    replacement = PublicationImage(5, object(), (candidate,))
    staged = manager._stage_publication(
        cell, candidate, expected=expected, replacement=replacement,
        old_groups=(), changed=True,
    )
    assert staged.accepted and staged.stage is not None
    clock[0] = 60.0
    rejected = manager._commit_publication(staged.stage)
    assert rejected.errors == ("artifact_candidate_expired",)
    assert cell.current is expected and candidate.state == "candidate"


@pytest.mark.parametrize(
    ("expected_generation", "replacement_generation"),
    (("0", 1), (False, 1), (0.5, 1), (0, "1"), (0, True), (0, 1.0)),
)
def test_publication_rejects_non_integer_generation_without_mutation(
    tmp_path: Path, expected_generation: object, replacement_generation: object,
) -> None:
    """Reject non-exact integer generations before arithmetic or stage mutation."""
    manager, _, _ = lease_fixture(tmp_path)
    candidate = manager.begin_candidate().group
    assert candidate is not None
    expected = PublicationImage(expected_generation, object(), ())
    cell = PublicationCell(expected)
    result = manager._stage_publication(
        cell, candidate, expected=expected,
        replacement=PublicationImage(replacement_generation, object(), (candidate,)),
        old_groups=(), changed=True,
    )
    assert result.errors == ("invalid_publication_stage",)
    assert cell.current is expected and candidate.state == "candidate"
    assert manager.snapshot().publication_stages == 0


def _line_for(method, fragment: str, occurrence: int = 0) -> int:
    """Resolve one deterministic source line without hard-coded line numbers."""
    source, first_line = inspect.getsourcelines(method)
    matches = [index for index, line in enumerate(source) if fragment in line]
    return first_line + matches[occurrence]


@pytest.mark.parametrize(
    ("fragment", "decision_made"),
    (("stage._cell.current = stage._replacement", False),
     ('stage._state = "decided"', True)),
)
def test_commit_interruption_reconciles_exactly_one_cell_decision(
    tmp_path: Path, fragment: str, decision_made: bool,
) -> None:
    """Abort before the image swap and finish forward after the image swap."""
    manager, requests, policy = lease_fixture(tmp_path)
    old, _ = captured_candidate(manager, requests, policy)
    cell = activate(manager, old)
    candidate, _ = captured_candidate(manager, requests, policy)
    expected = cell.current
    replacement = PublicationImage(2, object(), (candidate,))
    staged = manager._stage_publication(
        cell, candidate, expected=expected, replacement=replacement,
        old_groups=(old,), changed=True,
    )
    assert staged.accepted and staged.stage is not None
    stage = staged.stage
    interruption = KeyboardInterrupt(fragment)
    target = _line_for(ArtifactPublicationMixin._commit_publication, fragment)
    with pytest.raises(KeyboardInterrupt) as caught:
        with composed_line_interruption(
            ArtifactPublicationMixin._commit_publication.__code__, target, interruption,
        ):
            manager._commit_publication(stage)
    assert caught.value is interruption
    assert cell.current is (replacement if decision_made else expected)
    assert old.state == "active" and candidate.state == "staged"
    assert manager.snapshot().publication_stages == 1
    assert manager.admit((old,)).errors == ("artifact_lease_busy",)

    reconciled = manager._reconcile_publication(stage)
    assert reconciled.accepted
    assert manager.snapshot().publication_stages == 0
    if decision_made:
        assert cell.current is replacement
        assert candidate.state == "active" and old.state == "retired"
    else:
        assert cell.current is expected
        assert candidate.state == "candidate" and old.state == "active"


@pytest.mark.parametrize(
    ("fragment", "occurrence"),
    (("self._release_token(lease)", 0), ("group._state = state", 0),
     ("group._terminal = True", 0), ("group._mutation = None", 2),
     ("self._remove_group_if_settled(group)", 1)),
)
def test_changed_reconciliation_interruption_never_exposes_partial_authority(
    tmp_path: Path, fragment: str, occurrence: int,
) -> None:
    """Keep the stage charged across every changed-publication settlement mutation."""
    from topsailai.hooks.artifact_lease_transactions import ArtifactLeaseTransactionMixin

    manager, requests, policy = lease_fixture(tmp_path)
    old, _ = captured_candidate(manager, requests, policy)
    cell = activate(manager, old)
    candidate, _ = captured_candidate(manager, requests, policy)
    replacement = PublicationImage(2, object(), (candidate,))
    staged = manager._stage_publication(
        cell, candidate, expected=cell.current, replacement=replacement,
        old_groups=(old,), changed=True,
    )
    assert staged.accepted and staged.stage is not None
    stage = staged.stage
    cell.current = replacement
    interruption = KeyboardInterrupt(fragment)
    method = ArtifactLeaseTransactionMixin._reconcile_group_mutation
    target = _line_for(method, fragment, occurrence)
    with pytest.raises(KeyboardInterrupt) as caught:
        with composed_line_interruption(method.__code__, target, interruption):
            manager._reconcile_publication(stage)
    assert caught.value is interruption
    assert cell.current is replacement
    assert manager.snapshot().publication_stages == 1
    assert manager.admit((old,)).errors == ("artifact_lease_busy",)
    assert manager.admit((candidate,)).errors == ("artifact_lease_busy",)

    assert manager._reconcile_publication(stage).accepted
    assert candidate.state == "active" and old.state == "retired"
    assert manager.snapshot().publication_stages == 0
    assert manager.admit((old,)).errors == ("invalid_lease_group",)
    admitted = manager.admit((candidate,))
    assert admitted.accepted and admitted.group is not None


@pytest.mark.parametrize(
    ("fragment", "occurrence"),
    (("self._release_token(lease)", 0), ("group._state = state", 0),
     ("group._terminal = True", 0), ("group._mutation = None", 2),
     ("self._remove_group_if_settled(group)", 1)),
)
def test_noop_reconciliation_interruption_consumes_candidate_once(
    tmp_path: Path, fragment: str, occurrence: int,
) -> None:
    """Retain one charged no-op stage until candidate settlement is reconciled."""
    from topsailai.hooks.artifact_lease_transactions import ArtifactLeaseTransactionMixin

    manager, requests, policy = lease_fixture(tmp_path)
    candidate, lease = captured_candidate(manager, requests, policy)
    expected = PublicationImage(9, ("same",), ())
    replacement = PublicationImage(9, ("same",), ())
    cell = PublicationCell(expected)
    staged = manager._stage_publication(
        cell, candidate, expected=expected, replacement=replacement,
        old_groups=(), changed=False,
    )
    assert staged.accepted and staged.stage is not None
    stage = staged.stage
    tokens_before = manager.snapshot().live_tokens
    cell.current = replacement
    interruption = KeyboardInterrupt(fragment)
    method = ArtifactLeaseTransactionMixin._reconcile_group_mutation
    target = _line_for(method, fragment, occurrence)
    with pytest.raises(KeyboardInterrupt) as caught:
        with composed_line_interruption(method.__code__, target, interruption):
            manager._reconcile_publication(stage)
    assert caught.value is interruption
    assert cell.current is replacement and cell.current.generation == 9
    assert manager.snapshot().publication_stages == 1
    assert manager.admit((candidate,)).errors == ("artifact_lease_busy",)

    assert manager._reconcile_publication(stage).accepted
    snapshot = manager.snapshot()
    assert snapshot.publication_stages == 0 and snapshot.candidate_groups == 0
    assert snapshot.live_tokens <= tokens_before
    assert lease.released and candidate.state == "settled"
    duplicate = manager._reconcile_publication(stage)
    assert duplicate.accepted and duplicate.already_settled


def test_stage_charges_only_one_decision_and_preserves_existing_capacity(
    tmp_path: Path,
) -> None:
    """Count one bounded stage without allocating artifact bytes or lease tokens."""
    manager, requests, policy = lease_fixture(tmp_path)
    old, _ = captured_candidate(manager, requests, policy)
    cell = activate(manager, old)
    candidate, _ = captured_candidate(manager, requests, policy)
    waiting, _ = captured_candidate(manager, requests, policy)
    before = manager.snapshot()
    replacement = PublicationImage(2, object(), (candidate,))
    staged = manager._stage_publication(
        cell, candidate, expected=cell.current, replacement=replacement,
        old_groups=(old,), changed=True,
    )
    assert staged.accepted and staged.stage is not None
    during = manager.snapshot()
    assert during.publication_stages == 1
    assert during.live_tokens == before.live_tokens
    assert during.stored_versions == before.stored_versions
    assert during.stored_bytes == before.stored_bytes
    assert during.candidate_groups == before.candidate_groups
    blocked = manager._stage_publication(
        cell, waiting, expected=cell.current,
        replacement=PublicationImage(2, object(), (waiting,)),
        old_groups=(old,), changed=True,
    )
    assert blocked.errors == ("artifact_lease_busy",)
    assert manager._abort_publication(staged.stage).accepted
    assert manager.snapshot().publication_stages == 0


def test_committed_stage_retry_clears_interrupted_exact_slot(tmp_path: Path) -> None:
    """Retain the replacement decision while retry clears its exact stage slot."""
    manager, requests, policy = lease_fixture(tmp_path)
    old, _ = captured_candidate(manager, requests, policy)
    cell = activate(manager, old)
    candidate, _ = captured_candidate(manager, requests, policy)
    replacement = PublicationImage(2, object(), (candidate,))
    staged = manager._stage_publication(
        cell, candidate, expected=cell.current, replacement=replacement,
        old_groups=(old,), changed=True,
    )
    assert staged.accepted and staged.stage is not None
    stage = staged.stage
    target = _line_for(ArtifactPublicationMixin._clear_publication_stage, "if self._publication_stage")
    interruption = KeyboardInterrupt("committed stage cleanup")
    with pytest.raises(KeyboardInterrupt) as caught:
        with composed_line_interruption(
            ArtifactPublicationMixin._clear_publication_stage.__code__, target, interruption,
        ):
            manager._commit_publication(stage)
    assert caught.value is interruption
    assert cell.current is replacement and stage._state == "committed"
    assert manager.snapshot().publication_stages == 1

    retried = manager._reconcile_publication(stage)
    assert retried.accepted and retried.already_settled
    assert manager.snapshot().publication_stages == 0
    assert manager._publication_stage is None and cell.current is replacement
    admitted = manager.admit((candidate,))
    assert admitted.accepted and admitted.group is not None
    assert manager._execution_port().settle(admitted.group).accepted
    assert manager.retire(candidate).accepted
    assert manager.reclaim(deadline=manager._clock() + 1.0, pressure=True).removed == 2
    assert manager.close(deadline=manager._clock() + 1.0).accepted
    assert manager.snapshot().manager_state == "closed"


def test_aborted_stage_retry_clears_interrupted_exact_slot(tmp_path: Path) -> None:
    """Keep the old image while duplicate abort clears its exact stage slot."""
    manager, requests, policy = lease_fixture(tmp_path)
    old, _ = captured_candidate(manager, requests, policy)
    cell = activate(manager, old)
    candidate, _ = captured_candidate(manager, requests, policy)
    expected = cell.current
    replacement = PublicationImage(2, object(), (candidate,))
    staged = manager._stage_publication(
        cell, candidate, expected=expected, replacement=replacement,
        old_groups=(old,), changed=True,
    )
    assert staged.accepted and staged.stage is not None
    stage = staged.stage
    target = _line_for(ArtifactPublicationMixin._clear_publication_stage, "if self._publication_stage")
    interruption = KeyboardInterrupt("aborted stage cleanup")
    with pytest.raises(KeyboardInterrupt) as caught:
        with composed_line_interruption(
            ArtifactPublicationMixin._clear_publication_stage.__code__, target, interruption,
        ):
            manager._abort_publication(stage)
    assert caught.value is interruption
    assert cell.current is expected and stage._state == "aborted"
    assert candidate.state == "candidate" and manager.snapshot().publication_stages == 1

    retried = manager._abort_publication(stage)
    assert retried.accepted and retried.already_settled
    assert manager.snapshot().publication_stages == 0
    assert manager._publication_stage is None and cell.current is expected
    next_candidate = manager.begin_candidate()
    assert next_candidate.accepted and next_candidate.group is not None
    assert manager.release_group(next_candidate.group).accepted
    assert manager.release_group(candidate).accepted
    assert manager.retire(old).accepted
    assert manager.reclaim(deadline=manager._clock() + 1.0, pressure=True).removed == 2
    assert manager.close(deadline=manager._clock() + 1.0).accepted
    assert manager.snapshot().manager_state == "closed"


@pytest.mark.parametrize(
    "fragment",
    (
        "self._publication_cell = cell",
        "self._publication_stage = stage",
        'candidate._state = "staged"',
        "return PublicationStageResult(True, stage)",
    ),
)
def test_stage_establishment_interruption_rolls_back_exact_custody(
    tmp_path: Path, fragment: str,
) -> None:
    """Roll back an interrupted stage establishment without orphaning its candidate."""
    manager, requests, policy = lease_fixture(tmp_path)
    old, _ = captured_candidate(manager, requests, policy)
    cell = activate(manager, old)
    candidate, _ = captured_candidate(manager, requests, policy)
    expected = cell.current
    replacement = PublicationImage(2, object(), (candidate,))
    interruption = KeyboardInterrupt(fragment)
    target = _line_for(ArtifactPublicationMixin._stage_publication, fragment)

    with pytest.raises(KeyboardInterrupt) as caught:
        with composed_line_interruption(
            ArtifactPublicationMixin._stage_publication.__code__, target, interruption,
        ):
            manager._stage_publication(
                cell, candidate, expected=expected, replacement=replacement,
                old_groups=(old,), changed=True,
            )
    assert caught.value is interruption
    snapshot = manager.snapshot()
    assert candidate.state == "candidate"
    assert snapshot.publication_stages == 0
    assert manager._publication_stage is None

    retried = manager._stage_publication(
        cell, candidate, expected=expected, replacement=replacement,
        old_groups=(old,), changed=True,
    )
    assert retried.accepted and retried.stage is not None
    assert manager._abort_publication(retried.stage).accepted
    admitted = manager.admit((old,))
    assert admitted.accepted and admitted.group is not None
    assert manager._execution_port().settle(admitted.group).accepted
    assert manager.release_group(candidate).accepted
    assert manager.retire(old).accepted
    assert manager.reclaim(deadline=manager._clock() + 1.0, pressure=True).removed == 2
    assert manager.close(deadline=manager._clock() + 1.0).accepted
    closed = manager.snapshot()
    assert closed.manager_state == "closed"
    assert closed.stored_versions == 0
    assert manager._groups == {}



def test_lost_stage_return_recovers_exact_pending_stage(tmp_path: Path) -> None:
    """Recover the exact charged stage when its successful return was lost."""
    manager, requests, policy = lease_fixture(tmp_path)
    old, _ = captured_candidate(manager, requests, policy)
    cell = activate(manager, old)
    candidate, _ = captured_candidate(manager, requests, policy)
    expected = cell.current
    replacement = PublicationImage(2, object(), (candidate,))

    lost = manager._stage_publication(
        cell, candidate, expected=expected, replacement=replacement,
        old_groups=(old,), changed=True,
    )
    assert lost.accepted and lost.stage is not None
    recovered = manager._stage_publication(
        cell, candidate, expected=expected, replacement=replacement,
        old_groups=(old,), changed=True,
    )
    assert recovered.accepted and recovered.stage is lost.stage
    assert manager.snapshot().publication_stages == 1
    wrong = manager._stage_publication(
        cell, candidate, expected=expected,
        replacement=PublicationImage(2, object(), (candidate,)),
        old_groups=(old,), changed=True,
    )
    assert wrong.errors == ("artifact_lease_busy",)

    assert manager._commit_publication(recovered.stage).accepted
    assert cell.current is replacement
    assert manager.snapshot().publication_stages == 0
    admitted = manager.admit((candidate,))
    assert admitted.accepted and admitted.group is not None
    assert manager._execution_port().settle(admitted.group).accepted
    assert manager.retire(candidate).accepted
    assert manager.reclaim(deadline=manager._clock() + 1.0, pressure=True).removed == 2
    assert manager.close(deadline=manager._clock() + 1.0).accepted
    closed = manager.snapshot()
    assert closed.manager_state == "closed"
    assert closed.stored_versions == 0
    assert manager._groups == {}


@pytest.mark.parametrize("decision", ("abort", "commit"))
def test_pending_stage_pins_complete_image_until_decision(
    tmp_path: Path, decision: str,
) -> None:
    """Pin replaced and unchanged roots until an undecided stage finishes."""
    manager, requests, policy = lease_fixture(tmp_path)
    replaced, replaced_lease = captured_candidate(manager, requests, policy)
    cell = activate(manager, replaced)
    unchanged, unchanged_lease = captured_candidate(manager, requests, policy)
    expanded = PublicationImage(2, object(), (replaced, unchanged))
    expanded_stage = manager._stage_publication(
        cell, unchanged, expected=cell.current, replacement=expanded,
        old_groups=(), changed=True,
    )
    assert expanded_stage.accepted and expanded_stage.stage is not None
    assert manager._commit_publication(expanded_stage.stage).accepted

    candidate, _ = captured_candidate(manager, requests, policy)
    expected = cell.current
    replacement = PublicationImage(3, object(), (unchanged, candidate))
    staged = manager._stage_publication(
        cell, candidate, expected=expected, replacement=replacement,
        old_groups=(replaced,), changed=True,
    )
    assert staged.accepted and staged.stage is not None

    assert manager.retire(replaced).errors == ("artifact_lease_busy",)
    assert manager.retire(unchanged).errors == ("artifact_lease_busy",)
    assert not replaced_lease.released and not unchanged_lease.released
    assert replaced.state == "active" and unchanged.state == "active"
    assert manager.reclaim(
        deadline=manager._clock() + 1.0, pressure=True,
    ).removed == 0
    assert cell.current is expected

    if decision == "abort":
        assert manager._abort_publication(staged.stage).accepted
        final_roots = (replaced, unchanged)
        assert cell.current is expected and candidate.state == "candidate"
    else:
        assert manager._commit_publication(staged.stage).accepted
        final_roots = (unchanged, candidate)
        assert cell.current is replacement and replaced.state == "retired"

    admitted = manager.admit(final_roots)
    assert admitted.accepted and admitted.group is not None
    assert manager._execution_port().settle(admitted.group).accepted
    if decision == "abort":
        assert manager.release_group(candidate).accepted
        assert manager.retire(replaced).accepted
    assert manager.retire(unchanged).accepted
    if decision == "commit":
        assert manager.retire(candidate).accepted
    assert manager.reclaim(
        deadline=manager._clock() + 1.0, pressure=True,
    ).removed == 3
    assert manager.close(deadline=manager._clock() + 1.0).accepted
    closed = manager.snapshot()
    assert closed.manager_state == "closed"
    assert closed.stored_versions == 0
    assert manager._groups == {}


@pytest.mark.parametrize("interrupted_root", ("replaced", "unchanged"))
def test_stage_rejects_image_root_with_pending_retirement(
    tmp_path: Path, interrupted_root: str,
) -> None:
    """Resolve retirement before committing a repaired image on the same cell."""
    from topsailai.hooks.artifact_lease_transactions import ArtifactLeaseTransactionMixin

    manager, requests, policy = lease_fixture(tmp_path)
    replaced, _ = captured_candidate(manager, requests, policy)
    cell = activate(manager, replaced)
    unchanged, _ = captured_candidate(manager, requests, policy)
    expanded = PublicationImage(2, object(), (replaced, unchanged))
    expanded_stage = manager._stage_publication(
        cell, unchanged, expected=cell.current, replacement=expanded,
        old_groups=(), changed=True,
    )
    assert expanded_stage.accepted and expanded_stage.stage is not None
    assert manager._commit_publication(expanded_stage.stage).accepted

    candidate, _ = captured_candidate(manager, requests, policy)
    expected = cell.current
    root = replaced if interrupted_root == "replaced" else unchanged
    survivor = unchanged if root is replaced else replaced
    replacement = PublicationImage(3, object(), (survivor, candidate))
    method = ArtifactLeaseTransactionMixin._reconcile_group_mutation
    target = _line_for(method, "self._release_token(lease)")
    interruption = KeyboardInterrupt(interrupted_root)
    with pytest.raises(KeyboardInterrupt) as caught:
        with composed_line_interruption(method.__code__, target, interruption):
            manager.retire(root)
    assert caught.value is interruption
    assert root.state == "active" and root._mutation is not None
    assert not next(
        manager._tokens[token_id] for token_id in root._tokens
    ).released

    rejected = manager._stage_publication(
        cell, candidate, expected=expected, replacement=replacement,
        old_groups=(root,), changed=True,
    )
    assert rejected.errors == ("artifact_lease_busy",)
    assert manager._publication_stage is None
    assert candidate.state == "candidate" and cell.current is expected

    assert manager.retire(root).accepted
    assert root.state == "retired" and root._mutation is None
    recovered = manager._stage_publication(
        cell, candidate, expected=expected, replacement=replacement,
        old_groups=(root,), changed=True,
    )
    assert recovered.accepted and recovered.stage is not None
    assert manager._commit_publication(recovered.stage).accepted
    assert cell.current is replacement
    assert candidate.state == "active" and survivor.state == "active"

    admitted = manager.admit(replacement.lease_roots)
    assert admitted.accepted and admitted.group is not None
    assert manager._execution_port().settle(admitted.group).accepted
    assert manager.retire(survivor).accepted
    assert manager.retire(candidate).accepted
    assert manager.reclaim(
        deadline=manager._clock() + 1.0, pressure=True,
    ).removed == 3
    assert manager.close(deadline=manager._clock() + 1.0).accepted
    closed = manager.snapshot()
    assert closed.manager_state == "closed"
    assert closed.stored_versions == 0
    assert manager._groups == {}
