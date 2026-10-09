"""Focused aggregate ownership and cleanup-debt contract tests."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from topsailai.hooks.configured_preparation import PrivatePreparationImage
from topsailai.hooks.configured_preparation_ownership import (
    AggregateCleanupDebt,
    CaptureShard,
    PreparationOwnership,
)


class _U03Owner:
    def __init__(self, debt_id="u03-debt", result=True):
        self.debt_id = debt_id
        self.result = result
        self.calls = []

    def cleanup_debts(self):
        return (SimpleNamespace(debt_id=self.debt_id),) if self.result else ()

    def retry_cleanup(self, debt_id):
        self.calls.append(debt_id)
        if self.result:
            self.result = False
        return True


class _U07Manager:
    def __init__(self, debt):
        self.debt = debt
        self.calls = []

    def snapshot(self):
        return SimpleNamespace(cleanup_debts=(self.debt,))

    def retry_cleanup(self, debt, *, deadline):
        self.calls.append((debt, deadline))
        self.debt = None
        return SimpleNamespace(accepted=True, cleanup_pending=False)


class _Root:
    def __init__(self, close_result=True):
        self.close_result = close_result
        self.calls = 0
        self._root_fd = -1 if close_result else 42
        self._failed_slots = set() if close_result else {42}
        self._closed = close_result

    def close(self):
        self.calls += 1
        if self.close_result:
            self._closed = True
            self._root_fd = -1
        return self.close_result

    def revalidate(self):
        return None


def _aggregate(root=None):
    return PreparationOwnership(root, 123.5)


def test_state_transitions_open_transferred_closed_and_idempotent_image_close():
    aggregate = _aggregate(_Root())
    aggregate.transfer_to_image()
    assert aggregate.state == "transferred"
    image = PrivatePreparationImage(7, aggregate, ())
    assert image._ownership is aggregate
    assert image.close().accepted
    assert aggregate.state == "closed"
    assert image.close().accepted
    assert aggregate.state == "closed"


def test_transfer_rejects_when_any_debt_remains():
    aggregate = _aggregate(_Root())
    aggregate.module_owners.append(_U03Owner())
    aggregate.mark_pending()
    with pytest.raises(RuntimeError, match="cleanup_pending"):
        aggregate.transfer_to_image()


def test_duplicate_owner_is_identity_based_not_value_based():
    aggregate = _aggregate()
    first = _U03Owner()
    second = _U03Owner()
    aggregate.register_module_owner(first)
    aggregate.register_module_owner(second)
    assert aggregate.module_owners == [first, second]


def test_stable_tiered_debt_ids_and_exact_u03_retry():
    aggregate = _aggregate()
    owner = _U03Owner("underlying")
    aggregate.register_module_owner(owner, "hook")
    debts = aggregate.cleanup_debts()
    assert debts[0].debt_id == "u03:hook:underlying"
    assert aggregate.retry_cleanup(debts[0].debt_id)
    assert owner.calls == ["underlying"]


def test_exact_u07_manager_debt_object_and_deadline_are_routed():
    exact = SimpleNamespace(debt_id="lease-debt", category="artifact_cleanup_pending")
    manager = _U07Manager(exact)
    aggregate = _aggregate()
    aggregate.register_shard(CaptureShard(4, manager, object()))
    debt = aggregate.cleanup_debts()[0]
    assert debt.debt_id == "u07:4:lease-debt"
    assert aggregate.retry_cleanup(debt.debt_id)
    passed, deadline = manager.calls[0]
    assert passed is exact
    assert deadline == 123.5


def test_unknown_debt_is_false_without_mutation():
    aggregate = _aggregate()
    owner = _U03Owner()
    aggregate.register_module_owner(owner)
    before = aggregate.cleanup_debts()
    assert aggregate.retry_cleanup("unknown") is False
    assert aggregate.cleanup_debts() == before
    assert owner.calls == []


def test_pending_u03_blocks_u07_and_root_settlement():
    root = _Root()
    u03 = _U03Owner(result=True)
    manager = _U07Manager(SimpleNamespace(debt_id="u07-debt"))
    aggregate = _aggregate(root)
    aggregate.register_module_owner(u03)
    aggregate.register_shard(CaptureShard(0, manager, object()))
    assert aggregate.settle() is False
    assert aggregate.state == "cleanup_pending"
    assert manager.calls == []
    assert root.calls == 0


def test_root_close_failure_exposes_exact_slot_debt_and_retries_only_slot():
    root = _Root(close_result=False)
    aggregate = _aggregate(root)
    aggregate.mark_pending()
    debts = aggregate.cleanup_debts()
    assert [item.debt_id for item in debts if item.category == "root"] == ["root:42"]
    assert aggregate.retry_cleanup("root:42") is False
    assert root.calls == 1
