"""Deterministic tests for first-byte deadline and publication arbitration."""

import threading

from topsailai.ai_base.llm_control import first_byte_deadline as deadline_module
from topsailai.ai_base.llm_control.first_byte_deadline import (
    FirstByteBudget,
    FirstBytePhase,
    first_byte_budget_scope,
    current_first_byte_budget,
)


def test_budget_uses_one_absolute_deadline_and_nonnegative_remaining(monkeypatch):
    """Budget arithmetic never extends or returns a negative wait."""
    clock = iter((10.0, 10.25, 11.0))
    monkeypatch.setattr(deadline_module.time, "monotonic", lambda: next(clock))
    budget = FirstByteBudget.create(1.0)
    assert budget.deadline == 11.0
    assert budget.remaining() == 0.75
    assert budget.expired() is True


def test_budget_scope_restores_nested_context():
    """Nested attempt budgets do not leak into their caller."""
    outer = FirstByteBudget.create(2.0)
    inner = FirstByteBudget.create(1.0)
    assert current_first_byte_budget() is None
    with first_byte_budget_scope(outer):
        assert current_first_byte_budget() is outer
        with first_byte_budget_scope(inner):
            assert current_first_byte_budget() is inner
        assert current_first_byte_budget() is outer
    assert current_first_byte_budget() is None


def test_publication_before_deadline_survives_delayed_consumer(monkeypatch):
    """A committed result remains valid when notification is delayed."""
    monkeypatch.setattr(deadline_module.time, "monotonic", lambda: 4.0)
    phase = FirstBytePhase(FirstByteBudget(5.0, 1.0))
    phase.completed()
    assert phase.publish() is True
    monkeypatch.setattr(deadline_module.time, "monotonic", lambda: 6.0)
    assert phase.committed() is True


def test_completion_before_deadline_but_publication_after_is_rejected(monkeypatch):
    """Completion time cannot substitute for a late publication time."""
    times = iter((4.0, 6.0))
    monkeypatch.setattr(deadline_module.time, "monotonic", lambda: next(times))
    phase = FirstBytePhase(FirstByteBudget(5.0, 1.0))
    assert phase.completed() == 4.0
    assert phase.publish() is False
    assert phase.state == "EXPIRED"


def test_publication_equal_to_deadline_is_rejected(monkeypatch):
    """Deadline equality is late rather than on time."""
    monkeypatch.setattr(deadline_module.time, "monotonic", lambda: 5.0)
    phase = FirstBytePhase(FirstByteBudget(5.0, 1.0))
    assert phase.publish() is False
    assert phase.state == "EXPIRED"


def test_expiry_and_publication_race_has_one_terminal_decision(monkeypatch):
    """Concurrent expiry and publication cannot produce two terminal states."""
    monkeypatch.setattr(deadline_module.time, "monotonic", lambda: 4.0)
    phase = FirstBytePhase(FirstByteBudget(5.0, 1.0))
    barrier = threading.Barrier(2)
    results = []

    def publish():
        barrier.wait()
        results.append(phase.publish())

    def expire():
        barrier.wait()
        results.append(phase.expire())

    first = threading.Thread(target=publish)
    second = threading.Thread(target=expire)
    first.start()
    second.start()
    first.join()
    second.join()
    assert phase.state in {"COMMITTED", "EXPIRED"}
    assert sum(result is True for result in results) == 1


def test_phase_records_completion_and_publication_timestamps(monkeypatch):
    """A committed phase retains distinct completion and publication facts."""
    times = iter((1.0, 1.5))
    monkeypatch.setattr(deadline_module.time, "monotonic", lambda: next(times))
    phase = FirstBytePhase(FirstByteBudget(3.0, 2.0))
    assert phase.completed() == 1.0
    assert phase.publish() is True
    assert phase.completed_at == 1.0
    assert phase.published_at == 1.5


def test_expiry_is_permanent_after_publication_race(monkeypatch):
    """An expiry decision cannot be reversed by a later producer publication."""
    monkeypatch.setattr(deadline_module.time, "monotonic", lambda: 1.0)
    phase = FirstBytePhase(FirstByteBudget(2.0, 1.0))
    assert phase.expire() is True
    assert phase.publish() is False
    assert phase.state == "EXPIRED"


def test_phase_publication_uses_callback_free_lock_boundary(monkeypatch):
    """Publication state is decided before the caller observes the result."""
    monkeypatch.setattr(deadline_module.time, "monotonic", lambda: 1.0)
    phase = FirstBytePhase(FirstByteBudget(2.0, 1.0))
    assert phase.publish() is True
    assert phase.committed()
    assert phase.published_at == 1.0


def test_nested_budget_threads_are_isolated():
    """A child thread does not inherit the parent attempt budget implicitly."""
    budget = FirstByteBudget.create(1.0)
    observed = []
    with first_byte_budget_scope(budget):
        thread = threading.Thread(target=lambda: observed.append(current_first_byte_budget()))
        thread.start()
        thread.join()
    assert observed == [None]
