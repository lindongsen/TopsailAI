"""Focused branch coverage for the repaired first-byte timeout paths."""

import threading
import time
from unittest.mock import Mock

import pytest

from topsailai.ai_base.llm_control.first_byte_deadline import FirstByteBudget
from topsailai.ai_base.llm_control.response_ownership import AttemptResponseOwner
from topsailai.ai_base.llm_control.first_byte_timeout import (
    FirstByteTimeoutMixin,
    iter_with_first_byte_timeout,
)


class _Host(FirstByteTimeoutMixin):
    """Small provider adapter used to exercise orchestration branches."""

    def __init__(self, *, build_error=None, start_error=None, create_error=None):
        """Store controlled failures and bookkeeping observations."""
        self.build_error = build_error
        self.start_error = start_error
        self.create_error = create_error
        self.events = []
        self.warning = Mock()
        self.timeout_error = TimeoutError("deadline")

    def _build_first_byte_request_parameters(self, messages, **kwargs):
        """Build neutral parameters or raise the configured preparation error."""
        if self.build_error is not None:
            raise self.build_error
        return {"messages": messages, **kwargs}

    def _start_first_byte_request(self):
        """Start one timing ticket or raise the configured start error."""
        if self.start_error is not None:
            raise self.start_error
        self.events.append("start")
        return "ticket"

    def _create_first_byte_response(self, params):
        """Create one response or raise the configured provider error."""
        if self.create_error is not None:
            raise self.create_error
        self.events.append("create")
        return "response"

    def _publish_first_byte_request_ticket(self, ticket):
        """Record ticket publication."""
        self.events.append(("publish", ticket))

    def _complete_first_byte_request(self, ticket, *, stream):
        """Record successful ticket completion."""
        self.events.append(("complete", ticket, stream))

    def _pause_first_byte_request(self, ticket):
        """Record a stream pause."""
        self.events.append(("pause", ticket))

    def _finish_first_byte_request(self, ticket):
        """Record a complete-call finish."""
        self.events.append(("finish", ticket))

    def _log_first_byte_timeout(self, elapsed, timeout):
        """Record timeout warnings."""
        self.warning(elapsed, timeout)

    def _make_first_byte_timeout_error(self, timeout):
        """Return the stable timeout exception."""
        return self.timeout_error


def _callbacks():
    """Return warning and timeout-error callbacks."""
    warning = Mock()
    error = TimeoutError("first item")
    return warning, Mock(return_value=error), error


def test_creation_preparation_and_prelaunch_rejection_preserve_no_provider_call():
    """Preparation failures and expired admission do not start providers."""
    preparation_error = ValueError("prepare")
    host = _Host(build_error=preparation_error)
    with pytest.raises(ValueError) as caught:
        host._create_with_first_byte_timeout([], first_byte_timeout=1, raise_on_timeout=True)
    assert caught.value is preparation_error
    assert host.events == []

    host = _Host()
    budget = FirstByteBudget(time.monotonic() - 1, 1)
    with pytest.raises(TimeoutError):
        host._create_with_first_byte_timeout(
            [], first_byte_timeout=1, raise_on_timeout=True, budget=budget
        )
    assert host.events == []


def test_creation_start_failure_is_terminal_in_warning_and_raise_modes():
    """A ticket-start failure wakes the caller without an indefinite wait."""
    failure = RuntimeError("start")
    warning_host = _Host(start_error=failure)
    with pytest.raises(RuntimeError) as caught:
        warning_host._create_with_first_byte_timeout([], first_byte_timeout=1)
    assert caught.value is failure

    raising_host = _Host(start_error=failure)
    with pytest.raises(RuntimeError) as caught:
        raising_host._create_with_first_byte_timeout(
            [], first_byte_timeout=1, raise_on_timeout=True
        )
    assert caught.value is failure


def test_creation_provider_failure_and_legacy_timeout_paths():
    """Provider failure remains primary and bound callbacks use legacy semantics."""
    failure = RuntimeError("provider")
    host = _Host(create_error=failure)
    with pytest.raises(RuntimeError) as caught:
        host._create_with_first_byte_timeout([], first_byte_timeout=1)
    assert caught.value is failure

    class Callback:
        """Bound callback exposing the legacy compatibility seam."""
        def __init__(self):
            self.calls = []

        def on_timeout(self, elapsed, timeout):
            """Record legacy warning invocation."""
            self.calls.append((elapsed, timeout))

    class Blocking:
        """Iterator released by close for the legacy branch."""
        def __init__(self):
            self.release = threading.Event()
            self.closed = False

        def __iter__(self):
            """Return the iterator."""
            return self

        def __next__(self):
            """Block until legacy cleanup closes the iterator."""
            self.release.wait(1)
            raise StopIteration

        def close(self):
            """Release and record legacy cleanup."""
            self.closed = True
            self.release.set()

    callback = Callback()
    stream = Blocking()
    assert list(iter_with_first_byte_timeout(
        stream, .001, on_timeout=callback.on_timeout,
        make_timeout_error=lambda timeout: TimeoutError(timeout),
    )) == []
    assert callback.calls and stream.closed


def test_monitored_decision_record_covers_value_eof_error_and_rejection():
    """Worker-local decisions distinguish all terminal first-item outcomes."""
    for source, expected in ((iter(("value",)), ["value"]), (iter(()), [])):
        warning, make_error, _ = _callbacks()
        owner = Mock()
        owner.publish_outcome.return_value = True
        owner.publish_eof.return_value = True
        owner.take_outcome.return_value = type(
            "Outcome", (), {"kind": "VALUE" if expected else "EOF", "value": "value"}
        )()
        assert list(iter_with_first_byte_timeout(
            source, 1, owner=owner, on_timeout=warning, make_timeout_error=make_error,
        )) == expected

    warning, make_error, error = _callbacks()
    owner = Mock()
    owner.publish_error.return_value = True
    owner.take_outcome.return_value = type("Outcome", (), {"kind": "ERROR", "value": error})()

    def failing():
        """Raise the exact worker error."""
        raise error
        yield

    with pytest.raises(TimeoutError) as caught:
        list(iter_with_first_byte_timeout(
            failing(), 1, owner=owner, timing_ticket="ticket",
            pause=lambda ticket: None, on_timeout=warning, make_timeout_error=make_error,
        ))
    assert caught.value is error

    owner = Mock()
    owner.publish_outcome.return_value = False
    owner.take_outcome.return_value = type("Outcome", (), {"kind": "NOT_READY"})()
    assert list(iter_with_first_byte_timeout(
        iter(("rejected",)), 1, owner=owner, on_timeout=warning,
        make_timeout_error=make_error,
    )) == []


def test_monitored_raise_and_pause_failure_keep_primary_failure():
    """Raising mode and pause diagnostics retain timeout or iterator identity."""
    warning, make_error, timeout_error = _callbacks()
    blocker = threading.Event()

    def blocked():
        """Block beyond the absolute deadline."""
        blocker.wait(1)
        yield "late"

    with pytest.raises(TimeoutError) as caught:
        list(iter_with_first_byte_timeout(
            blocked(), .001, raise_on_timeout=True, on_timeout=warning,
            make_timeout_error=make_error,
        ))
    assert caught.value is timeout_error
    blocker.set()

    primary = ValueError("primary")
    owner = Mock()
    owner.publish_error.return_value = True
    owner.take_outcome.return_value = type("Outcome", (), {"kind": "ERROR", "value": primary})()

    def failing():
        """Raise a primary iterator error."""
        raise primary
        yield

    def pause(_ticket):
        """Raise a cleanup error after the primary error is staged."""
        raise RuntimeError("pause")

    with pytest.raises(ValueError) as caught:
        list(iter_with_first_byte_timeout(
            failing(), 1, owner=owner, timing_ticket="ticket", pause=pause,
            on_timeout=warning, make_timeout_error=make_error,
        ))
    assert caught.value is primary
    assert "pause failed" in str(primary.__notes__[0])


def test_safe_phase_diagnostic_swallows_ordinary_logger_failure():
    """Ordinary diagnostic failures are logged without changing the result."""
    host = _Host()
    host.logger = Mock()
    host.logger.debug.side_effect = RuntimeError("diagnostic")
    host._safe_log_first_byte_phase_elapsed("creation", .1)
    host.logger.debug.assert_called_once()


class _OutcomeOwner:
    """Minimal owner double with real boolean staging decisions."""

    def __init__(self, outcome, error=None):
        """Initialize the outcome returned to the consumer."""
        self.outcome = outcome
        self.error = error
        self.errors = []
        self.finished = []

    def publish_response(self, response):
        """Accept the response for this attempt."""
        return True

    def publish_outcome(self, value, *, phase):
        """Accept a staged value."""
        return self.outcome != "REJECTED"

    def publish_eof(self, *, phase):
        """Accept a staged EOF."""
        return self.outcome == "EOF"

    def publish_error(self, error, *, phase):
        """Accept a staged error."""
        self.errors.append(error)
        return self.outcome == "ERROR"

    def take_outcome(self, *, phase):
        """Return the configured terminal outcome."""
        kind = "NOT_READY" if self.outcome == "REJECTED" else self.outcome
        value = "response" if kind == "VALUE" else self.error
        return type("Outcome", (), {"kind": kind, "value": value})()

    def worker_finished(self, *, phase):
        """Record worker completion."""
        self.finished.append(phase)

    def abandon(self, error=None):
        """Accept abandonment."""
        return None

def test_direct_adapter_and_unmonitored_owner_paths():
    """Exercise adapter delegation and the disabled owner lifecycle."""
    host = _Host()
    assert list(host._iter_first_byte_timeout(iter(("x",)), 1, False, False,
                                              on_timeout=Mock(),
                                              make_timeout_error=TimeoutError)) == ["x"]
    owner = _OutcomeOwner("VALUE")
    assert host._create_without_first_byte_timeout(
        {}, stream=False, owner=owner
    ) == "response"
    assert ("complete", "ticket", False) in host.events


def test_creation_preparation_expiry_and_worker_start_expiry(monkeypatch):
    """Cover preparation failure, admission expiry, and worker expiry."""
    preparation = RuntimeError("preparation")
    host = _Host(build_error=preparation)
    with pytest.raises(RuntimeError) as caught:
        host._create_with_first_byte_timeout([], first_byte_timeout=1,
                                             raise_on_timeout=True)
    assert caught.value is preparation

    expired = FirstByteBudget(time.monotonic() - 1, 1)
    with pytest.raises(TimeoutError):
        _Host()._create_with_first_byte_timeout([], first_byte_timeout=1,
                                                raise_on_timeout=True,
                                                budget=expired)

    class AdvancingHost(_Host):
        """Advance the shared clock immediately after ticket allocation."""

        def _start_first_byte_request(self):
            """Return a ticket after advancing beyond its deadline."""
            self.events.append("start")
            return "ticket"

    clock = Mock(side_effect=[10.0, 10.0, 12.0, 12.0, 12.0, 12.0])
    budget = FirstByteBudget(11.0, 1.0, clock=clock)
    with pytest.raises(TimeoutError):
        AdvancingHost()._create_with_first_byte_timeout(
            [], first_byte_timeout=1, raise_on_timeout=True, budget=budget
        )
    monkeypatch.setattr(threading.Thread, "start", threading.Thread.start)


def test_thread_start_failure_is_preserved(monkeypatch):
    """A failure launching the creation worker is propagated and abandoned."""
    failure = RuntimeError("thread start")

    def fail_start(_thread):
        """Raise the controlled launch failure."""
        raise failure

    monkeypatch.setattr(threading.Thread, "start", fail_start)
    with pytest.raises(RuntimeError) as caught:
        _Host()._create_with_first_byte_timeout([], first_byte_timeout=1)
    assert caught.value is failure


def test_monitored_real_owner_terminal_decisions():
    """Exercise value, EOF, error, and rejected decisions without mocks."""
    warning = lambda elapsed, timeout: None
    make_error = lambda timeout: TimeoutError(timeout)
    for source, result in ((iter(("value",)), ["response"]), (iter(()), [])):
        kind = "VALUE" if result else "EOF"
        owner = _OutcomeOwner(kind)
        assert list(iter_with_first_byte_timeout(
            source, 1, owner=owner, on_timeout=warning,
            make_timeout_error=make_error,
        )) == result
    primary = ValueError("iterator")

    def failing():
        """Raise the primary iterator failure."""
        raise primary
        yield

    owner = _OutcomeOwner("ERROR", primary)
    with pytest.raises(ValueError) as caught:
        list(iter_with_first_byte_timeout(
            failing(), 1, owner=owner, on_timeout=warning,
            make_timeout_error=make_error,
        ))
    assert caught.value is primary
    owner = _OutcomeOwner("REJECTED")
    assert list(iter_with_first_byte_timeout(
        iter(("rejected",)), 1, owner=owner, on_timeout=warning,
        make_timeout_error=make_error,
    )) == []


def test_monitored_publication_and_pause_failures(monkeypatch):
    """Preserve primary errors when publication or pause diagnostics fail."""
    primary = ValueError("primary")
    owner = _OutcomeOwner("ERROR", primary)
    owner.publish_error = lambda error, *, phase: (_ for _ in ()).throw(RuntimeError("stage"))

    def failing():
        """Raise the primary iterator failure."""
        raise primary
        yield

    with pytest.raises(ValueError) as caught:
        list(iter_with_first_byte_timeout(
            failing(), 1, owner=owner, timing_ticket="ticket",
            pause=lambda ticket: (_ for _ in ()).throw(RuntimeError("pause")),
            on_timeout=lambda elapsed, timeout: None,
            make_timeout_error=lambda timeout: TimeoutError(timeout),
        ))
    assert caught.value is primary


def test_warning_mode_continues_unbound_callback_after_timeout():
    """The production-shaped unbound callback continues after a slow item."""
    release = threading.Event()

    def delayed():
        """Yield after the warning threshold."""
        release.wait(.02)
        yield "late"

    warning = Mock()
    stream = delayed()
    owner = AttemptResponseOwner()
    budget = FirstByteBudget.create(.001)
    assert list(iter_with_first_byte_timeout(
        stream, .001, owner=owner, budget=budget, on_timeout=warning,
        make_timeout_error=lambda timeout: TimeoutError(timeout),
    )) == ["late"]
    release.set()
    warning.assert_called_once()


def test_creation_expired_after_preparation_uses_timeout_result():
    """Exercise the admission rejection after request preparation."""
    host = _Host()
    budget = FirstByteBudget(time.monotonic() - 2, 1)
    with pytest.raises(TimeoutError) as caught:
        host._create_with_first_byte_timeout(
            [], first_byte_timeout=1, raise_on_timeout=True, budget=budget
        )
    assert caught.value is host.timeout_error
    assert host.events == []


def test_creation_provider_error_after_ticket_finishes_ticket():
    """Preserve provider errors and finish an already-started creation ticket."""
    failure = RuntimeError("provider after start")
    host = _Host(create_error=failure)
    with pytest.raises(RuntimeError) as caught:
        host._create_with_first_byte_timeout([], first_byte_timeout=1)
    assert caught.value is failure
    assert ("finish", "ticket") in host.events


class _FinishFailureHost(_Host):
    """Provider adapter whose ticket cleanup fails once."""

    def _finish_first_byte_request(self, ticket):
        """Raise a cleanup failure for the active ticket."""
        self.events.append(("finish", ticket))
        raise RuntimeError("finish")


def test_creation_cleanup_failure_does_not_replace_provider_error():
    """Cleanup diagnostics must not replace the primary provider exception."""
    failure = RuntimeError("provider")
    host = _FinishFailureHost(create_error=failure)
    with pytest.raises(RuntimeError) as caught:
        host._create_with_first_byte_timeout([], first_byte_timeout=1)
    assert caught.value is failure


def test_legacy_unbound_timeout_waits_for_late_value():
    """The unbound compatibility adapter continues after a late first item."""
    release = threading.Event()

    class Late:
        """One-item iterator released after the timeout warning."""

        def __iter__(self):
            """Return this iterator."""
            return self

        def __next__(self):
            """Wait until the caller has entered continuation mode."""
            release.wait(1)
            release.clear()
            raise StopIteration

    stream = Late()
    warning = Mock()
    def release_late(elapsed, timeout):
        """Release the worker when the warning is emitted."""
        warning(elapsed, timeout)
        release.set()
    assert list(iter_with_first_byte_timeout(
        stream, .001, on_timeout=release_late,
        make_timeout_error=lambda timeout: TimeoutError(timeout),
    )) == []
    warning.assert_called_once()


def test_monitored_rejected_outcome_returns_without_sentinel_value():
    """A real rejected staging decision suppresses output explicitly."""
    owner = _OutcomeOwner("REJECTED")
    assert list(iter_with_first_byte_timeout(
        iter(("value",)), 1, owner=owner,
        on_timeout=lambda elapsed, timeout: None,
        make_timeout_error=TimeoutError,
    )) == []



def test_post_preparation_expiry_and_unmonitored_error_cleanup(monkeypatch):
    """Cover post-build admission and unmonitored cleanup/error branches."""
    clock = Mock(side_effect=[10.0, 12.0, 12.0, 12.0])
    budget = FirstByteBudget(11.0, 1.0, clock=clock)

    class SlowBuild(_Host):
        """Advance the attempt clock during request preparation."""
        def _build_first_byte_request_parameters(self, messages, **kwargs):
            clock()
            return super()._build_first_byte_request_parameters(messages, **kwargs)

    host = SlowBuild()
    with pytest.raises(TimeoutError):
        host._create_with_first_byte_timeout(
            [], first_byte_timeout=1, raise_on_timeout=True, budget=budget
        )
    assert host.events == []

    class ErrorOwner(_OutcomeOwner):
        """Return an error from the unmonitored owner path."""
        def publish_outcome(self, value, *, phase):
            return True
        def take_outcome(self, *, phase):
            return type("Outcome", (), {"kind": "ERROR", "value": self.error})()

    failure = RuntimeError("unmonitored")
    with pytest.raises(RuntimeError) as caught:
        _Host()._create_without_first_byte_timeout(
            {}, stream=False, owner=ErrorOwner("ERROR", failure)
        )
    assert caught.value is failure


def test_legacy_timeout_close_failure_is_best_effort():
    """Cover legacy compatibility cleanup when iterator close fails."""
    class Bound:
        """Bound callback selecting legacy compatibility behavior."""
        def on_timeout(self, elapsed, timeout):
            """Accept the timeout notification."""

    class BrokenClose:
        """Iterator whose close operation fails after timeout."""
        def __iter__(self):
            return self
        def __next__(self):
            time.sleep(.02)
            raise RuntimeError("late")
        def close(self):
            raise RuntimeError("close")

    assert list(iter_with_first_byte_timeout(
        BrokenClose(), .001, on_timeout=Bound().on_timeout,
        make_timeout_error=lambda timeout: TimeoutError(timeout),
    )) == []


def test_unmonitored_timeout_propagates_late_error_with_unbound_callback():
    """Cover the non-legacy timeout continuation error branch."""
    def delayed_error():
        time.sleep(.02)
        raise ValueError("late stream")
        yield

    with pytest.raises(ValueError, match="late stream"):
        list(iter_with_first_byte_timeout(
            delayed_error(), .001, owner=AttemptResponseOwner(),
            budget=FirstByteBudget.create(.001),
            on_timeout=lambda elapsed, timeout: None,
            make_timeout_error=lambda timeout: TimeoutError(timeout),
        ))


def test_monitored_budget_none_diagnostic_failure_and_tail_disposal(monkeypatch):
    """Cover disabled monitoring, phase diagnostics, and local-owner cleanup."""
    host = _Host()
    assert list(iter_with_first_byte_timeout(
        iter(("plain",)), 0, on_timeout=host._log_first_byte_timeout,
        make_timeout_error=TimeoutError,
    )) == ["plain"]

    host._log_first_byte_phase_elapsed = Mock(side_effect=RuntimeError("diag"))
    budget = FirstByteBudget.create(1)
    from topsailai.ai_base.llm_control.first_byte_deadline import first_byte_budget_scope
    with first_byte_budget_scope(budget):
        assert list(iter_with_first_byte_timeout(
            iter(("one", "two")), 1, on_timeout=host._log_first_byte_timeout,
            make_timeout_error=TimeoutError,
        )) == ["one", "two"]


def test_pause_note_failure_and_not_ready_error_paths():
    """Cover defensive note handling and explicit unexplained worker failures."""
    class NoNotes(ValueError):
        """Error whose note operation fails."""
        def add_note(self, note):
            raise RuntimeError("notes unavailable")

    failure = NoNotes("primary")
    owner = _OutcomeOwner("ERROR", failure)
    with pytest.raises(NoNotes):
        list(iter_with_first_byte_timeout(
            iter(("x",)), 1, owner=owner, timing_ticket="ticket",
            pause=lambda ticket: (_ for _ in ()).throw(RuntimeError("pause")),
            on_timeout=lambda elapsed, timeout: None,
            make_timeout_error=TimeoutError,
        ))

    owner = _OutcomeOwner("NOT_READY")
    with pytest.raises(RuntimeError, match="without a published outcome"):
        list(iter_with_first_byte_timeout(
            iter(("x",)), 1, owner=owner,
            on_timeout=lambda elapsed, timeout: None,
            make_timeout_error=TimeoutError,
        ))



def test_monitored_owner_without_budget_delegates_to_plain_stream():
    """Cover the explicit owner path when timeout monitoring is disabled."""
    owner = _OutcomeOwner("VALUE")
    assert list(iter_with_first_byte_timeout(
        iter(("plain",)), 0, owner=owner,
        on_timeout=lambda elapsed, timeout: None,
        make_timeout_error=TimeoutError,
    )) == ["plain"]


def test_not_ready_worker_error_is_re_raised_when_owner_rejects_error():
    """Cover worker error propagation when ownership rejects staging."""
    error = ValueError("worker")

    def failing():
        """Raise the worker error."""
        raise error
        yield

    owner = _OutcomeOwner("NOT_READY")
    with pytest.raises(ValueError) as caught:
        list(iter_with_first_byte_timeout(
            failing(), 1, owner=owner,
            on_timeout=lambda elapsed, timeout: None,
            make_timeout_error=TimeoutError,
        ))
    assert caught.value is error



def test_direct_reachable_cleanup_and_disabled_contract_paths():
    """Exercise disabled accounting, local disposal, and pause error paths."""
    class Stream:
        """Closable iterator with deterministic terminal behavior."""
        def __init__(self, values=()):
            self.values = iter(values)
            self.closed = False

        def __iter__(self):
            return self

        def __next__(self):
            return next(self.values)

        def close(self):
            self.closed = True

    resumed = []
    paused = []
    stream = Stream(("x",))
    assert list(iter_with_first_byte_timeout(
        stream, 0, timing_ticket="ticket", resume=resumed.append,
        pause=paused.append, on_timeout=lambda *args: None,
        make_timeout_error=TimeoutError,
    )) == ["x"]
    assert resumed == ["ticket"]
    assert paused == ["ticket"]

    stream = Stream(("x", "y"))
    assert list(iter_with_first_byte_timeout(
        stream, 0, on_timeout=lambda *args: None,
        make_timeout_error=TimeoutError,
    )) == ["x", "y"]
    assert not stream.closed

    stream = Stream(("x",))
    primary = ValueError("primary")
    def fail_pause(_ticket):
        raise RuntimeError("pause")
    def failing_stream():
        raise primary
        yield
    with pytest.raises(ValueError) as caught:
        list(iter_with_first_byte_timeout(
            failing_stream(), 0, timing_ticket="ticket", pause=fail_pause,
            on_timeout=lambda *args: None, make_timeout_error=TimeoutError,
        ))
    assert caught.value is primary


def test_direct_reachable_owner_disposal_and_warning_logging_failures():
    """Exercise local owner disposal and swallowed warning/diagnostic failures."""
    class BrokenClose:
        """Response whose close reports a cleanup failure."""
        def close(self):
            raise RuntimeError("close")

    owner = AttemptResponseOwner()
    owner.publish_response(BrokenClose())
    owner.dispose(background=False)
    assert owner.close_error is not None

    warning = Mock(side_effect=RuntimeError("warning"))
    stream = iter(("value",))
    assert list(iter_with_first_byte_timeout(
        stream, 1, owner=AttemptResponseOwner(),
        budget=FirstByteBudget.create(1),
        on_timeout=warning, make_timeout_error=TimeoutError,
    )) == ["value"]


def test_direct_reachable_creation_cleanup_failure_and_outcome_guards():
    """Exercise ticket cleanup failures and non-ready creation outcomes."""
    host = _FinishFailureHost()
    owner = AttemptResponseOwner()
    host._finish_ticket("ticket", owner)
    assert host.events == [("finish", "ticket")]
    assert owner.close_error is not None

    owner = AttemptResponseOwner()
    owner.publish_response("response")
    owner.publish_error(RuntimeError("late"), phase="create")
    assert owner.take_outcome(phase="create").kind == "ERROR"



def test_creation_worker_error_and_cleanup_branches_are_reachable():
    """Exercise creation worker error, ticket cleanup, and late start states."""
    class FinishErrorHost(_Host):
        """Provider whose ticket cleanup fails."""
        def _finish_first_byte_request(self, ticket):
            raise RuntimeError("finish")

    failure = RuntimeError("provider")
    host = FinishErrorHost(create_error=failure)
    with pytest.raises(RuntimeError) as caught:
        host._create_without_first_byte_timeout({}, stream=False, owner=AttemptResponseOwner())
    assert caught.value is failure

    owner = AttemptResponseOwner()
    owner.abandon()
    assert owner.publish_error(RuntimeError("late"), phase="create") is False


def test_monitored_eof_rejection_and_pause_failure_paths():
    """Exercise monitored EOF rejection and terminal pause failure."""
    class RejectEOF(AttemptResponseOwner):
        """Reject EOF publication to force expiry handling."""
        def publish_eof(self, *, phase="first_item"):
            return False

    owner = RejectEOF()
    with pytest.raises(RuntimeError, match="without a published outcome"):
        list(iter_with_first_byte_timeout(
            iter(()), 1, owner=owner, on_timeout=lambda *args: None,
            make_timeout_error=TimeoutError,
        ))

    owner = AttemptResponseOwner()
    owner.publish_eof = lambda *, phase="first_item": True
    owner.take_outcome = lambda *, phase="first_item": type("Outcome", (), {"kind": "EOF", "value": None})()
    with pytest.raises(RuntimeError, match="pause"):
        list(iter_with_first_byte_timeout(
            iter(()), 1, owner=owner, timing_ticket="ticket",
            pause=lambda ticket: (_ for _ in ()).throw(RuntimeError("pause")),
            on_timeout=lambda *args: None, make_timeout_error=TimeoutError,
        ))
