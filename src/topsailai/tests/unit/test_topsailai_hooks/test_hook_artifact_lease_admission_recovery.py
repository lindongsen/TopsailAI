"""Admission regressions for interrupted artifact root retirement."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from tests.unit.test_topsailai_hooks.artifact_lease_helpers import (
    activate,
    captured_candidate,
    lease_fixture,
)
from tests.unit.test_topsailai_hooks.artifact_trace_helpers import (
    composed_line_interruption,
)
from topsailai.hooks.artifact_lease_transactions import ArtifactLeaseTransactionMixin
from topsailai.hooks.artifact_publication import PublicationImage


@pytest.mark.parametrize(
    ("method_name", "fragment", "occurrence"),
    (
        ("_release_token", "lease._group._tokens.discard", 0),
        ("_reconcile_group_mutation", "group._state = state", 0),
    ),
)
def test_admit_rejects_roots_with_interrupted_retirement(
    tmp_path: Path, method_name: str, fragment: str, occurrence: int,
) -> None:
    """Reject the complete root union while retirement metadata is unfinished."""
    manager, requests, policy = lease_fixture(tmp_path)
    root, source = captured_candidate(manager, requests, policy)
    cell = activate(manager, root)
    healthy, healthy_source = captured_candidate(manager, requests, policy)
    replacement = PublicationImage(2, object(), (root, healthy))
    staged = manager._stage_publication(
        cell, healthy, expected=cell.current, replacement=replacement,
        old_groups=(), changed=True,
    )
    assert staged.accepted and manager._commit_publication(staged.stage).accepted
    method = getattr(ArtifactLeaseTransactionMixin, method_name)
    lines, first = inspect.getsourcelines(method)
    matches = [index for index, line in enumerate(lines) if fragment in line]
    interruption = KeyboardInterrupt(fragment)
    with pytest.raises(KeyboardInterrupt) as caught:
        with composed_line_interruption(
            method.__code__, first + matches[occurrence], interruption
        ):
            manager.retire(root)
    assert caught.value is interruption
    before = (
        tuple(manager._groups.values()), tuple(manager._tokens.values()), root._mutation
    )
    group_count = len(manager._groups)
    rejected = manager.admit((healthy, root))
    assert not rejected.accepted and rejected.group is None
    assert rejected.errors == ("artifact_lease_busy",)
    assert len(manager._groups) == group_count
    assert (
        tuple(manager._groups.values()), tuple(manager._tokens.values()), root._mutation
    ) == before
    assert manager.retire(root).accepted and manager.retire(healthy).accepted
    assert source.released and healthy_source.released
    closed = manager.close(deadline=manager._clock() + 1.0)
    assert closed.accepted and manager.snapshot().manager_state == "closed"


@pytest.mark.parametrize("fragment", ("recovery.append(group)", "return group"))
def test_group_scope_cleans_interrupted_admission_handoff(
    tmp_path: Path, fragment: str,
) -> None:
    """Leave no admission when interrupted around exact recovery handoff."""
    manager, requests, policy = lease_fixture(tmp_path)
    root, source = captured_candidate(manager, requests, policy)
    activate(manager, root)
    existing = manager.admit((root,))
    assert existing.accepted and existing.group is not None
    before_groups = tuple(manager._groups.values())
    before_tokens = tuple(manager._tokens.values())
    before_existing_tokens = tuple(existing.group._tokens)
    lines, first = inspect.getsourcelines(manager._new_group)
    line = next(index for index, text in enumerate(lines) if fragment in text)
    interruption = KeyboardInterrupt(fragment)
    entered = False
    with pytest.raises(KeyboardInterrupt) as caught:
        with composed_line_interruption(
            manager._new_group.__code__, first + line, interruption
        ):
            with manager._group_scope((root,)):
                entered = True
    assert caught.value is interruption
    assert not entered
    assert tuple(manager._groups.values()) == before_groups
    assert tuple(manager._tokens.values()) == before_tokens
    assert existing.group.state == "admitted"
    assert tuple(existing.group._tokens) == before_existing_tokens
    snapshot = manager.snapshot()
    assert snapshot.admitted_groups == 1
    assert manager._execution_port().settle(existing.group).accepted
    assert manager.retire(root).accepted and source.released
    closed = manager.close(deadline=manager._clock() + 1.0)
    assert closed.accepted and not closed.cleanup_pending
    final = manager.snapshot()
    assert final.manager_state == "closed"
    assert final.stored_versions == 0
    assert not manager._groups
