"""Tests for first-byte response ownership and late cleanup."""

import threading

import pytest

from topsailai.ai_base.llm_control.response_ownership import (
    AttemptResponseOwner,
    ClosingTimedIterator,
    current_response_owner,
    response_ownership_scope,
)


class _Closable:
    """Record direct response closure."""

    def __init__(self):
        """Initialize closure state."""
        self.closed = threading.Event()

    def close(self):
        """Record one underlying-response close."""
        self.closed.set()


def test_scope_is_available_before_response_creation():
    """The owner is armed before provider creation begins."""
    assert current_response_owner() is None
    with response_ownership_scope():
        assert isinstance(current_response_owner(), AttemptResponseOwner)


def test_late_publish_after_abandon_closes_response():
    """A response arriving after timeout is disposed and never claimed."""
    owner = AttemptResponseOwner()
    owner.abandon()
    response = _Closable()

    assert owner.publish_response(response) is False
    assert owner.close_finished_event.wait(1)
    assert response.closed.is_set()
    assert owner.take_outcome() is not response


def test_closing_timed_iterator_routes_to_underlying_owner():
    """Closing the timing wrapper closes the owned response directly."""
    owner = AttemptResponseOwner()
    response = _Closable()
    owner.publish_response(response)
    wrapper = ClosingTimedIterator(iter(()), owner)

    wrapper.close()

    assert owner.close_finished_event.wait(1)
    assert response.closed.is_set()


def test_close_failure_is_recorded_without_retrying():
    """An ambiguous close remains failed rather than being retried."""
    error = RuntimeError("close failed")
    owner = AttemptResponseOwner()
    response = _Closable()
    response.close = lambda: (_ for _ in ()).throw(error)
    owner.publish_response(response)

    owner.dispose(background=False)
    owner.dispose(background=False)

    assert owner.close_error is error


def test_outcome_claim_is_single_use():
    """A phase outcome cannot be claimed twice."""
    owner = AttemptResponseOwner()
    owner.publish_outcome("value")

    first = owner.take_outcome()
    second = owner.take_outcome()

    assert first.kind == "VALUE"
    assert first.value == "value"
    assert second.kind == "NOT_READY"


def test_late_value_discard_does_not_create_cleanup_failure():
    """A stale value is discarded without reporting a cleanup failure."""
    owner = AttemptResponseOwner()
    owner.abandon()

    assert owner.publish_outcome("late") is False
    assert owner.close_error is None


def test_cleanup_logging_failure_preserves_primary_and_attaches_custody(monkeypatch):
    """Diagnostic logging failure cannot replace the primary exception."""
    primary = RuntimeError("primary")
    cleanup = RuntimeError("cleanup")
    response = _Closable()
    owner = AttemptResponseOwner()
    owner.publish_response(response)

    monkeypatch.setattr(
        "topsailai.ai_base.llm_control.response_ownership._LOG.error",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("logger")),
    )
    with pytest.raises(RuntimeError) as caught:
        with response_ownership_scope() as scoped:
            scoped.publish_response(response)
            scoped._record_cleanup_failure(cleanup, primary)
            raise primary

    assert caught.value is primary


def test_nested_scope_restores_previous_owner():
    """Nested execution-local scopes restore their predecessor."""
    with response_ownership_scope() as outer:
        with response_ownership_scope() as inner:
            assert current_response_owner() is inner
        assert current_response_owner() is outer
    assert current_response_owner() is None


def test_owner_cleanup_preserves_primary_exception_identity():
    """Scope cleanup does not replace a provider exception."""
    error = RuntimeError("primary")
    response = _Closable()

    with pytest.raises(RuntimeError) as caught:
        with response_ownership_scope() as owner:
            owner.publish_response(response)
            raise error

    assert caught.value is error
    assert response.closed.is_set()


def test_timeout_owner_closes_late_response_without_claiming_it():
    """A timed-out creation closes a late response in the worker."""
    from topsailai.ai_base.llm_control.first_byte_timeout import FirstByteTimeoutMixin

    from topsailai.ai_base.llm_control.first_byte_deadline import FirstByteBudget

    entered, release = threading.Event(), threading.Event()
    budget = FirstByteBudget(1.0, 1.0, clock=lambda: float(entered.is_set()) * 2)

    class Host(FirstByteTimeoutMixin):
        """Provide a delayed response for the creation timeout test."""

        def _build_first_byte_request_parameters(self, messages, **kwargs):
            """Return provider-neutral parameters."""
            return {}

        def _create_first_byte_response(self, params):
            """Delay creation until the caller has abandoned the attempt."""
            entered.set()
            assert release.wait(1)
            return response

        def _start_first_byte_request(self):
            """Return a timing ticket."""
            return object()

        def _publish_first_byte_request_ticket(self, ticket):
            """Publish no-op timing state."""

        def _finish_first_byte_request(self, ticket):
            """Finish no-op timing state."""

        def _complete_first_byte_request(self, ticket, *, stream):
            """Complete no-op timing state."""

        def _log_first_byte_timeout(self, elapsed, timeout):
            """Avoid logging in this focused test."""

        def _make_first_byte_timeout_error(self, timeout):
            """Return the expected timeout exception."""
            return TimeoutError("timed out")

    response = _Closable()
    with response_ownership_scope() as owner:
        try:
            with pytest.raises(TimeoutError):
                Host()._create_with_first_byte_timeout(
                    [], first_byte_timeout=1, raise_on_timeout=True, budget=budget
                )
            assert entered.is_set()
            assert owner.take_outcome().kind == "ABANDONED"
            assert not response.closed.is_set()
        finally:
            release.set()
            if owner.create_thread is not None:
                owner.create_thread.join(1)
        assert not owner.create_thread.is_alive()
        assert owner.create_finished_event.is_set()
        assert response.closed.is_set()
        assert owner.take_outcome().kind == "ABANDONED"



def test_owner_rejected_eof_and_error_paths_record_late_cleanup(monkeypatch):
    """Late terminal publications are rejected and retained as cleanup evidence."""
    owner = AttemptResponseOwner()
    owner.abandon()
    assert owner.publish_eof() is False
    assert owner.publish_error(RuntimeError("late")) is False
    assert owner.close_error is not None


def test_owner_background_close_schedule_failure_is_settled(monkeypatch):
    """A cleanup thread launch failure is recorded without retrying close."""
    owner = AttemptResponseOwner()
    response = _Closable()
    owner.publish_response(response)
    error = RuntimeError("start")
    monkeypatch.setattr(threading.Thread, "start", lambda self: (_ for _ in ()).throw(error))
    owner.dispose(background=True)
    assert owner.close_error is error
    assert owner.close_finished_event.is_set()


def test_owner_scope_cleanup_failure_preserves_provider_error(monkeypatch):
    """Scope cleanup exceptions are aggregated while the provider error survives."""
    primary = RuntimeError("primary")
    owner = AttemptResponseOwner()
    owner.publish_response(_Closable())
    monkeypatch.setattr(owner, "abandon", lambda error=None: (_ for _ in ()).throw(RuntimeError("cleanup")))
    with pytest.raises(RuntimeError) as caught:
        with response_ownership_scope():
            raise primary
    assert caught.value is primary


def test_closing_iterator_protocol_delegates_and_abandons():
    """The close-aware iterator preserves iterator protocol and ownership cleanup."""
    owner = AttemptResponseOwner()
    response = _Closable()
    owner.publish_response(response)
    wrapper = ClosingTimedIterator(iter(("value",)), owner)
    assert iter(wrapper) is wrapper
    assert next(wrapper) == "value"
    wrapper.close()
    assert response.closed.is_set()
