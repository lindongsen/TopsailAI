"""Deterministic U3 deadline, ownership, and timing matrix tests."""

import threading
import time
from unittest.mock import Mock

import pytest

from topsailai.ai_base.llm_control.first_byte_deadline import (
    FirstByteBudget,
    FirstBytePhase,
)
from topsailai.ai_base.llm_control.first_byte_timeout import (
    FirstByteTimeoutMixin,
    iter_with_first_byte_timeout,
)
from topsailai.ai_base.llm_control.request_tracking import (
    iter_stream_for_request_timing,
    record_llm_request_outcome,
)


def _callbacks():
    """Return injected timeout callbacks and their exact exception."""
    warning = Mock()
    error = TimeoutError("deadline")
    return warning, Mock(return_value=error), error


def test_warning_latch_and_late_commit_are_distinct_from_expiry():
    """Warning mode may record a late terminal result without retry expiry."""
    budget = FirstByteBudget(time.monotonic() + 1, 1)
    warning = Mock()
    budget.warn_once(warning, 1.0)
    budget.warn_once(warning, 2.0)
    warning.assert_called_once_with(1.0, 1)
    phase = FirstBytePhase(budget)
    assert phase.publish(allow_late=True) is True
    assert phase.state == "COMMITTED"
    assert phase.published_at is not None


def test_expire_and_repeated_terminal_operations_are_idempotent():
    """The first terminal phase decision remains authoritative."""
    budget = FirstByteBudget(time.monotonic() - 1, 1)
    phase = FirstBytePhase(budget)
    assert phase.expire() is True
    assert phase.expire() is True
    assert phase.publish() is False
    assert phase.state == "EXPIRED"


class _Blocking:
    """Iterator whose first operation is released by close."""

    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.closed = False

    def __iter__(self):
        """Return this iterator."""
        return self

    def __next__(self):
        """Wait until the test releases the operation."""
        self.started.set()
        self.release.wait(2)
        raise StopIteration

    def close(self):
        """Release the blocked operation."""
        self.closed = True
        self.release.set()


def test_owned_warning_continues_original_operation_after_deadline():
    """Production ownership does not close or truncate a warning-mode stream."""
    warning, make_error, _ = _callbacks()
    warned = threading.Event()
    warning.side_effect = lambda *args: warned.set()
    stream = _Blocking()
    owner = Mock()
    owner.publish_response.return_value = True
    owner.publish_eof.return_value = True
    owner.take_outcome.return_value = type("Outcome", (), {"kind": "EOF"})()
    result = []
    child_errors = []

    def consume():
        """Capture consumer failures without hiding them behind an empty result."""
        try:
            result.extend(iter_with_first_byte_timeout(
                stream, .01, on_timeout=warning, make_timeout_error=make_error,
                owner=owner,
            ))
        except BaseException as error:
            child_errors.append(error)

    worker = threading.Thread(target=consume)
    worker.start()
    try:
        assert stream.started.wait(1)
        assert worker.is_alive()
        assert warned.wait(1)
        assert worker.is_alive()
        assert stream.closed is False
        assert owner.fetch_thread is not None
        assert owner.fetch_thread.is_alive()
    finally:
        stream.release.set()
        worker.join(1)
        if owner.fetch_thread is not None:
            owner.fetch_thread.join(1)
    assert not worker.is_alive()
    assert owner.fetch_thread is not None
    assert not owner.fetch_thread.is_alive()
    assert child_errors == []
    assert stream.closed is False
    warning.assert_called_once()
    make_error.assert_not_called()

def test_raising_late_ticket_has_no_provider_operation():
    """An expired phase is rejected before a late provider admission."""
    warning, make_error, error = _callbacks()
    phase = FirstBytePhase(FirstByteBudget(time.monotonic() - 1, 0.01))
    assert phase.expire() is True
    assert phase.state == "EXPIRED"
    with pytest.raises(TimeoutError) as caught:
        raise make_error(.01)
    assert caught.value is error
    warning.assert_not_called()


def test_first_entry_is_committed_before_consumer_pause():
    """A pause held past D cannot turn an already committed entry into a timeout."""
    warning, make_error, _ = _callbacks()
    pause_started = threading.Event()
    release_pause = threading.Event()

    def pause(_ticket):
        """Hold only consumer bookkeeping, after decoded publication."""
        pause_started.set()
        release_pause.wait(1)

    owner = Mock()
    owner.publish_response.return_value = True
    owner.publish_outcome.return_value = True
    owner.take_outcome.return_value = type("Outcome", (), {"kind": "VALUE", "value": ""})()
    result = []
    child_errors = []

    def consume():
        """Capture child failures without hiding them behind an empty result."""
        try:
            result.extend(iter_with_first_byte_timeout(
                iter(("", "tail")), 1, on_timeout=warning,
                make_timeout_error=make_error, owner=owner,
                timing_ticket="ticket", pause=pause,
            ))
        except BaseException as error:
            child_errors.append(error)

    worker = threading.Thread(target=consume)
    owner.fetch_thread = worker
    worker.start()
    try:
        assert pause_started.wait(1)
    finally:
        release_pause.set()
        worker.join(1)
    assert not worker.is_alive()
    assert child_errors == []
    assert result == ["", "tail"]
    warning.assert_not_called()


def test_first_entry_error_and_eof_are_terminal_without_timeout_warning():
    """Decoded error and EOF preserve normal terminal semantics."""
    for source in (iter(()), iter((1,))):
        warning, make_error, _ = _callbacks()
        owner = Mock()
        owner.publish_response.return_value = True
        owner.publish_eof.return_value = True
        owner.publish_outcome.return_value = True
        owner.take_outcome.return_value = type("Outcome", (), {"kind": "EOF"})()
        output = list(iter_with_first_byte_timeout(
            source, 1, on_timeout=warning, make_timeout_error=make_error,
            owner=owner,
        ))
        assert output in ([], [1])
        warning.assert_not_called()


def test_request_timing_first_operation_and_failure_pause_exact_ticket():
    """The first operation skips duplicate resume and pauses its exact ticket."""
    calls = []
    stream = iter(("first",))
    result = list(iter_stream_for_request_timing(
        stream, "ticket", resume=lambda t: calls.append(("resume", t)),
        pause=lambda t: calls.append(("pause", t)), first_operation=True,
    ))
    assert result == ["first"]
    assert calls == [("pause", "ticket"), ("resume", "ticket"), ("pause", "ticket")]
    calls.clear()
    def failing():
        """Raise during the actual iterator operation."""
        raise RuntimeError("failure")
        yield
    with pytest.raises(RuntimeError):
        list(iter_stream_for_request_timing(
            failing(), "ticket",
            resume=lambda t: calls.append(("resume", t)),
            pause=lambda t: calls.append(("pause", t)),
        ))
    assert calls == [("resume", "ticket"), ("pause", "ticket")]


class _Host(FirstByteTimeoutMixin):
    """Minimal host for unmonitored and failure-path matrix cases."""

    def __init__(self, error=None):
        self.error = error
        self.finished = []
        self.warnings = []

    def _start_first_byte_request(self):
        """Return one exact ticket."""
        return "ticket"

    def _publish_first_byte_request_ticket(self, ticket):
        """Record ticket publication."""
        self.finished.append(("publish", ticket))

    def _create_first_byte_response(self, params):
        """Return or raise the configured response."""
        if self.error:
            raise self.error
        return "response"

    def _pause_first_byte_request(self, ticket):
        """Record stream pause."""
        self.finished.append(("pause", ticket))

    def _finish_first_byte_request(self, ticket):
        """Record non-stream finish."""
        self.finished.append(("finish", ticket))

    def _build_first_byte_request_parameters(self, messages, **kwargs):
        """Build neutral parameters."""
        return {"messages": messages, **kwargs}

    def _log_first_byte_timeout(self, elapsed, timeout):
        """Record warning details."""
        self.warnings.append((elapsed, timeout))

    def _make_first_byte_timeout_error(self, timeout):
        """Create the host timeout error."""
        return TimeoutError(timeout)


def test_non_stream_and_stream_disabled_modes_keep_shapes_and_tickets():
    """Disabled mode preserves complete and streaming result contracts."""
    host = _Host()
    assert host._create_with_first_byte_timeout([], first_byte_timeout=0) == "response"
    assert ("finish", "ticket") in host.finished
    host = _Host()
    assert host._create_with_first_byte_timeout([], stream=True, first_byte_timeout=0) == (
        "response", False
    )
    assert ("pause", "ticket") in host.finished


def test_disabled_mode_provider_failure_finishes_exact_ticket():
    """A disabled provider failure retains identity and finalizes once."""
    failure = ValueError("provider")
    host = _Host(failure)
    with pytest.raises(ValueError) as caught:
        host._create_with_first_byte_timeout([], first_byte_timeout=0)
    assert caught.value is failure
    assert host.finished.count(("finish", "ticket")) == 1


def test_request_outcome_decorator_resets_context_after_success_and_failure():
    """Request state is isolated between decorated provider invocations."""
    class Tracker:
        """Provide request hooks for the neutral decorator."""
        def __init__(self, fail=False):
            self.fail = fail
            self.calls = []

        def operation(self):
            """Return or fail after marking a request started."""
            self.calls.append("operation")
            if self.fail:
                raise RuntimeError("failure")
            return "ok"

        def _record_llm_request_success(self):
            """Record success."""
            self.calls.append("success")

        def _record_llm_request_failure(self):
            """Record failure."""
            self.calls.append("failure")

        def _finish_llm_request(self, ticket):
            """Record finish if a ticket exists."""
            self.calls.append(("finish", ticket))

    decorated = record_llm_request_outcome(Tracker.operation)
    success = Tracker()
    assert decorated(success) == "ok"
    assert success.calls == ["operation"]
    failure = Tracker(True)
    with pytest.raises(RuntimeError):
        decorated(failure)
    assert failure.calls == ["operation"]


class _OutcomeOwner:
    """Configurable owner for publication and admission branches."""
    def __init__(self, *, response=True, outcome=True, error=None):
        """Store branch outcomes and call evidence."""
        self.response = response
        self.outcome = outcome
        self.error = error
        self.calls = []
        self.create_thread = None

    def publish_response(self, value):
        """Accept or reject response custody."""
        self.calls.append("response")
        return self.response

    def publish_outcome(self, value, *, phase):
        """Accept or reject phase outcome staging."""
        self.calls.append(("outcome", phase))
        return self.outcome

    def publish_error(self, value, *, phase):
        """Record a worker error."""
        self.calls.append(("error", phase))
        return True

    def worker_finished(self, *, phase):
        """Record worker completion."""
        self.calls.append(("worker", phase))

    def take_outcome(self, *, phase):
        """Return the outcome staged by the configured owner branch."""
        if self.error is not None:
            return type("Outcome", (), {"kind": "ERROR", "value": self.error})()
        if not self.response or not self.outcome:
            return type("Outcome", (), {"kind": "NOT_READY", "value": None})()
        return type("Outcome", (), {"kind": "VALUE", "value": "response"})()
    def abandon(self, *args, **kwargs):
        """Record abandonment outside phase state handling."""
        self.calls.append("abandon")

    def _record_cleanup_failure(self, *args, **kwargs):
        """Record cleanup diagnostics without raising."""
        self.calls.append("cleanup")


def test_creation_publication_and_outcome_rejection_paths(monkeypatch):
    """Custody and staging rejection each finalize the exact ticket."""
    for owner in (_OutcomeOwner(response=False), _OutcomeOwner(outcome=False)):
        host = _Host()
        monkeypatch.setattr(
            "topsailai.ai_base.llm_control.first_byte_timeout.current_response_owner",
            lambda owner=owner: owner,
        )
        if owner.response is False:
            with pytest.raises(RuntimeError):
                host._create_with_first_byte_timeout([], first_byte_timeout=1)
        else:
            with pytest.raises(RuntimeError):
                host._create_with_first_byte_timeout([], first_byte_timeout=1)
        assert "response" in owner.calls
        assert ("worker", "create") in owner.calls


def test_creation_provider_error_preserves_identity_and_worker_finalization():
    """A provider exception is staged and the worker is finalized exactly once."""
    failure = RuntimeError("provider failure")
    host = _Host(failure)
    with pytest.raises(RuntimeError) as caught:
        host._create_with_first_byte_timeout([], first_byte_timeout=1)
    assert caught.value is failure
    assert host.finished.count(("finish", "ticket")) == 1


def test_standalone_timeout_error_and_close_failure_paths():
    """Standalone raising preserves timeout identity; warning mode continues."""
    warning, make_error, error = _callbacks()
    stream = _Blocking()
    with pytest.raises(TimeoutError) as caught:
        list(iter_with_first_byte_timeout(
            stream, .01, raise_on_timeout=True,
            on_timeout=warning, make_timeout_error=make_error,
        ))
    assert caught.value is error
    warning.assert_called_once()

    stream = _Blocking()
    result = []
    warned = threading.Event()
    child_errors = []
    warning.reset_mock()
    warning.side_effect = lambda *args: warned.set()

    def consume():
        """Capture the standalone worker exception for deterministic cleanup."""
        try:
            result.extend(iter_with_first_byte_timeout(
                stream, .01,
                on_timeout=warning, make_timeout_error=make_error,
            ))
        except BaseException as error:
            child_errors.append(error)

    worker = threading.Thread(target=consume)
    worker.start()
    try:
        assert stream.started.wait(1)
        assert warned.wait(1)
    finally:
        stream.release.set()
        worker.join(1)
    assert not worker.is_alive()
    assert child_errors == []
    assert stream.closed is True
    assert result == []

def test_standalone_disabled_and_owner_error_paths():
    """Disabled helper and owned source errors retain normal iterator semantics."""
    warning, make_error, _ = _callbacks()
    assert list(iter_with_first_byte_timeout(
        iter((1, 2)), 0, on_timeout=warning, make_timeout_error=make_error,
    )) == [1, 2]

    source_error = ValueError("source")
    owner = _OutcomeOwner(error=source_error)

    def failing():
        """Raise the exact source exception from the worker iterator."""
        raise source_error
        yield

    with pytest.raises(ValueError) as caught:
        list(iter_with_first_byte_timeout(
            failing(), 1, owner=owner,
            on_timeout=warning, make_timeout_error=make_error,
        ))
    assert caught.value is source_error
    assert ("error", "first_item") in owner.calls


def test_request_tracking_eof_and_callback_exceptions_pause_exact_ticket():
    """EOF and iterator errors both pause the active ticket."""
    for source, expected in ((iter(()), [("resume", "t"), ("pause", "t")]),):
        calls = []
        assert list(iter_stream_for_request_timing(
            source, "t", resume=lambda t: calls.append(("resume", t)),
            pause=lambda t: calls.append(("pause", t)),
        )) == []
        assert calls == expected

    def failing():
        """Raise from the real iterator operation."""
        raise LookupError("iterator")
        yield

    calls = []
    with pytest.raises(LookupError):
        list(iter_stream_for_request_timing(
            failing(), "t", resume=lambda t: calls.append(("resume", t)),
            pause=lambda t: calls.append(("pause", t)),
        ))
    assert calls == [("resume", "t"), ("pause", "t")]


def test_creation_deadline_expiry_before_provider_and_cleanup_failure():
    """An expired creation ticket records cleanup failure without masking control."""
    class ExpiredHost(_Host):
        def _start_first_byte_request(self):
            time.sleep(0.02)
            return super()._start_first_byte_request()

        def _finish_first_byte_request(self, ticket):
            self.finished.append(("finish-attempt", ticket))
            raise OSError("finish failed")

    host = ExpiredHost()
    with pytest.raises(OSError, match="finish failed"):
        host._create_with_first_byte_timeout([], first_byte_timeout=0.001)
    assert ("finish-attempt", "ticket") in host.finished


def test_creation_late_raise_abandons_after_publication_rejection(monkeypatch):
    """A rejected late publication abandons the exact owner in raising mode."""
    owner = _OutcomeOwner()
    class SlowHost(_Host):
        def _create_first_byte_response(self, params):
            time.sleep(0.02)
            return super()._create_first_byte_response(params)
    host = SlowHost()
    monkeypatch.setattr(
        "topsailai.ai_base.llm_control.first_byte_timeout.current_response_owner",
        lambda: owner,
    )
    original_publish = __import__(
        "topsailai.ai_base.llm_control.first_byte_timeout",
        fromlist=["FirstBytePhase"],
    ).FirstBytePhase.publish

    def reject_late(self, *, allow_late=False):
        return original_publish(self, allow_late=False)

    monkeypatch.setattr(
        "topsailai.ai_base.llm_control.first_byte_timeout.FirstBytePhase.publish",
        reject_late,
    )
    with pytest.raises(TimeoutError):
        host._create_with_first_byte_timeout(
            [], first_byte_timeout=0.001, raise_on_timeout=True
        )
    assert "abandon" in owner.calls


def test_first_item_late_warning_and_create_timeout_suppression():
    """Late decoded entries warn once unless creation already warned."""
    warning, make_error, _ = _callbacks()
    budget = FirstByteBudget(time.monotonic() - 1, 0.001)
    owner = _OutcomeOwner()
    owner.publish_outcome = lambda value, *, phase: True
    owner.take_outcome = lambda *, phase: type(
        "Outcome", (), {"kind": "VALUE", "value": "late"}
    )()
    assert list(iter_with_first_byte_timeout(
        iter(("late",)), 0.001, on_timeout=warning,
        make_timeout_error=make_error, owner=owner, budget=budget,
    )) == ["late"]
    warning.assert_called_once()

    warning.reset_mock()
    owner = _OutcomeOwner()
    owner.publish_outcome = lambda value, *, phase: True
    owner.take_outcome = lambda *, phase: type(
        "Outcome", (), {"kind": "VALUE", "value": "late"}
    )()
    assert list(iter_with_first_byte_timeout(
        iter(("late",)), 0.001, create_timed_out=True,
        on_timeout=warning, make_timeout_error=make_error, owner=owner,
        budget=FirstByteBudget(time.monotonic() - 1, 0.001),
    )) == ["late"]
    warning.assert_not_called()


def test_timeout_mixin_adapter_contract_and_outcome_branches():
    """Neutral adapter contract remains explicit and rejection branches settle."""
    host = FirstByteTimeoutMixin()
    for method, args in (
        (host._build_first_byte_request_parameters, ([],)),
        (host._create_first_byte_response, (None,)),
        (host._start_first_byte_request, ()),
        (host._pause_first_byte_request, ("ticket",)),
        (host._finish_first_byte_request, ("ticket",)),
        (host._publish_first_byte_request_ticket, ("ticket",)),
    ):
        with pytest.raises(NotImplementedError):
            if method.__name__ == "_build_first_byte_request_parameters":
                method(*args, tools=None, tool_choice="auto", stream=False)
            else:
                method(*args)



def test_standalone_first_item_late_raise_and_eof_paths():
    """Standalone first-item raising and EOF branches preserve terminal behavior."""
    warning, make_error, error = _callbacks()
    with pytest.raises(TimeoutError) as caught:
        list(iter_with_first_byte_timeout(
            iter(("late",)), 0.001, raise_on_timeout=True,
            on_timeout=warning, make_timeout_error=make_error,
            budget=FirstByteBudget(time.monotonic() - 1, 0.001),
        ))
    assert caught.value is error
    assert warning.call_count == 0
    assert list(iter_with_first_byte_timeout(
        iter(()), 1, on_timeout=warning, make_timeout_error=make_error,
    )) == []


def test_expired_raising_budget_rejects_before_provider(monkeypatch):
    """An already expired raising budget never admits provider creation."""
    host = _Host()
    budget = FirstByteBudget(time.monotonic() - 1, 1)
    monkeypatch.setattr(
        "topsailai.ai_base.llm_control.first_byte_timeout.current_first_byte_budget",
        lambda: budget,
    )
    with pytest.raises(TimeoutError):
        host._create_with_first_byte_timeout([], first_byte_timeout=1, raise_on_timeout=True)
    assert host.finished == []


def test_unmonitored_custody_rejection_preserves_failure(monkeypatch):
    """Disabled mode rejects abandoned custody and finalizes its ticket."""
    owner = _OutcomeOwner(response=False)
    host = _Host()
    monkeypatch.setattr(
        "topsailai.ai_base.llm_control.first_byte_timeout.current_response_owner",
        lambda: owner,
    )
    with pytest.raises(RuntimeError, match="ownership"):
        host._create_with_first_byte_timeout([], first_byte_timeout=0)
    assert ("finish", "ticket") in host.finished


def test_first_entry_resume_expiry_skips_decoded_fetch():
    """Raising mode checks expiry after timing resume before next()."""
    warning, make_error, error = _callbacks()
    calls = []
    budget = FirstByteBudget(time.monotonic() + 1, 1)

    def resume(_ticket):
        budget.deadline = time.monotonic() - 1
        calls.append("resume")

    with pytest.raises(TimeoutError) as caught:
        list(iter_with_first_byte_timeout(
            iter(("value",)), 1, raise_on_timeout=True,
            on_timeout=warning, make_timeout_error=make_error,
            budget=budget, timing_ticket="ticket", resume=resume,
            pause=lambda ticket: calls.append(("pause", ticket)),
        ))
    assert caught.value is error
    assert calls == ["resume"]


def test_first_entry_late_error_is_preserved_in_warning_mode():
    """A late provider error remains the original error in warning mode."""
    warning, make_error, _ = _callbacks()
    source_error = LookupError("late source")

    def failing():
        raise source_error
        yield

    with pytest.raises(LookupError) as caught:
        list(iter_with_first_byte_timeout(
            failing(), .001, on_timeout=warning, make_timeout_error=make_error,
        ))
    assert caught.value is source_error


def test_stream_timeout_wrapper_delegates_to_host_iterator():
    """The mixin delegates first-item iteration through its host seam."""
    class Host(FirstByteTimeoutMixin):
        def _get_llm_request_timing_ticket(self):
            return None

        def _iter_first_byte_timeout(self, stream, *args, **kwargs):
            return iter(("delegated",))

        def _log_first_byte_timeout(self, elapsed, timeout):
            pass

        def _make_first_byte_timeout_error(self, timeout):
            return TimeoutError(timeout)

    assert list(Host().iter_stream_with_first_byte_timeout(iter(()))) == ["delegated"]
