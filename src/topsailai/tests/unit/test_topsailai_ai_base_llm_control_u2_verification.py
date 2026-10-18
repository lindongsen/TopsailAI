"""Independent U2 accounting, race and interruption checks. Author: DawsonLin."""
from contextlib import nullcontext
from types import SimpleNamespace
import threading
from uuid import uuid4

import pytest

from tests.unit.test_topsailai_ai_base_llm_control_control_wait import Host, scope
from topsailai.ai_base.llm_base import LLMModel
from topsailai.ai_base.llm_control import control_runtime as runtime
from topsailai.ai_base.llm_control import control_wait as wait
from topsailai.ai_base.llm_control import control_recovery as recovery
from topsailai.ai_base.llm_control.request_tracking import (
    record_llm_request_outcome, iter_stream_for_request_timing,
)
from topsailai.ai_base.llm_control.response_ownership import response_ownership_scope
from topsailai.ai_base.llm_control.request_control import REQUEST_CONTROL
from topsailai.context.llm_request_stat import LLMRequestStat, RequestTimingTicket


class AccountingHost(Host):
    """Compose genuine production ticket methods with an isolated provider."""
    _start_first_byte_request = LLMModel._start_first_byte_request
    _publish_first_byte_request_ticket = LLMModel._publish_first_byte_request_ticket
    _pause_first_byte_request = LLMModel._pause_first_byte_request
    _finish_first_byte_request = LLMModel._finish_first_byte_request
    _complete_first_byte_request = LLMModel._complete_first_byte_request
    _start_llm_request = LLMModel._start_llm_request
    _finish_llm_request = LLMModel._finish_llm_request
    _get_llm_request_stat = LLMModel._get_llm_request_stat
    _get_llm_request_timing_ticket = LLMModel._get_llm_request_timing_ticket
    _resume_llm_request = LLMModel._resume_llm_request
    _pause_llm_request = LLMModel._pause_llm_request
    _record_llm_request_success = LLMModel._record_llm_request_success
    _record_llm_request_failure = LLMModel._record_llm_request_failure
    _record_llm_request_stat = LLMModel._record_llm_request_stat

    def __init__(self, provider):
        """Use an explicit clock and retain ticket identity for assertions."""
        super().__init__(provider)
        self.now = 1.0
        self.llm_request_stat = LLMRequestStat(clock=lambda: self.now)
        self.exact_ticket = None

    @record_llm_request_outcome
    def invoke(self, stream, timeout, raising=False):
        """Match production streaming timing and outcome composition."""
        result = self._create_with_first_byte_timeout(
            [], stream=stream, first_byte_timeout=timeout, raise_on_timeout=raising,
        )
        self.exact_ticket = self._get_llm_request_timing_ticket()
        if not stream:
            return result
        iterator = self.iter_stream_with_first_byte_timeout(
            result[0], timeout, raise_on_timeout=raising,
        )
        iterator = iter_stream_for_request_timing(
            iterator, self.exact_ticket, resume=self._resume_llm_request,
            pause=self._pause_llm_request,
            first_operation=timeout > 0 or runtime.current_attempt_control() is not None,
        )
        values = list(iterator)
        self._finish_llm_request(self.exact_ticket)
        return values


@pytest.mark.parametrize("timeout", [-1, 0, 1])
@pytest.mark.parametrize("stream,phase", [(False, "value"), (False, "create_error"),
                                         (True, "value"), (True, "eof"),
                                         (True, "fetch_error")])
def test_real_accounting_routed_legacy_parity(timeout, stream, phase):
    """Creation/fetch/EOF each produce one exact outcome and duration sample."""
    snapshots = []
    error = LookupError("exact provider failure")
    for routed in (False, True):
        def records():
            """Keep decoded metadata and payload inside the timing boundary."""
            if phase == "fetch_error":
                raise error
            if phase != "eof":
                yield ""
                yield "body"

        def provider():
            """Fail or publish through the unchanged request adapter."""
            if phase == "create_error":
                raise error
            return records() if stream else "body"

        host = AccountingHost(provider)
        with scope(timeout) if routed else response_ownership_scope():
            if phase.endswith("error"):
                with pytest.raises(LookupError) as caught:
                    host.invoke(stream, timeout)
                assert caught.value is error
            else:
                assert host.invoke(stream, timeout) == ([] if phase == "eof" else ["", "body"] if stream else "body")
                assert isinstance(host.exact_ticket, RequestTimingTicket)
        snapshot = host.llm_request_stat.get_request_stat_info()
        assert snapshot["total_requests"] == 1
        assert snapshot["request_successes"] == (not phase.endswith("error"))
        assert snapshot["request_failures"] == phase.endswith("error")
        assert snapshot["request_duration_count"] == 1
        snapshots.append(snapshot)
    assert snapshots[0] == snapshots[1]


@pytest.mark.parametrize("operation", ["force_retry", "hard_interrupt"])
def test_prestart_control_has_no_production_accounting(operation):
    """A command selected before ticket admission must not create a request."""
    host = AccountingHost(lambda: pytest.fail("provider forbidden"))
    with scope(0) as (_, owner, context):
        proposal = REQUEST_CONTROL.submit(context[1].target, uuid4().hex, operation).proposal
        with pytest.raises((runtime.LLMRequestedRetryError, runtime.LLMControlledInterruptError)) as caught:
            host.invoke(False, 0)
        assert recovery.acknowledge_control(caught.value)
        assert REQUEST_CONTROL.status(proposal.command_id).state == "recovery"
    stat = host.llm_request_stat.get_request_stat_info()
    assert stat["total_requests"] == stat["request_failures"] == stat["request_duration_count"] == 0


@pytest.mark.parametrize("phase", ["create", "first_fetch"])
@pytest.mark.parametrize("control_first", [False, True])
def test_barrier_admission_control_order(phase, control_first):
    """Separate real threads linearize admission/control without timing sleeps."""
    ready, proceed = threading.Event(), threading.Event()
    result, errors = [], []
    host = Host(lambda: "body")
    with scope(0) as (route, owner, context):
        if phase == "first_fetch":
            assert context[1].created(streaming=True)
        proposal = REQUEST_CONTROL.submit(context[1].target, uuid4().hex, "hard_interrupt").proposal

        def claimant():
            """Hold before admission until the selected ordering is established."""
            try:
                ready.set()
                assert proceed.wait(3)
                result.append(wait._claim_operation(context, owner, host, 0, phase))
            except BaseException as error:
                errors.append(error)

        worker = threading.Thread(target=claimant)
        worker.start()
        try:
            assert ready.wait(3)
            if control_first:
                with pytest.raises(runtime.LLMControlledInterruptError) as caught:
                    wait._tick(context, owner)
                assert recovery.acknowledge_control(caught.value)
            proceed.set()
            worker.join(3)
            assert not worker.is_alive() and not errors
            assert result == [not control_first]
            if not control_first:
                with pytest.raises(runtime.LLMControlledInterruptError) as caught:
                    wait._tick(context, owner)
                assert recovery.acknowledge_control(caught.value)
            assert context[1].snapshot().outcome == "hard_interrupt"
        finally:
            proceed.set()
            worker.join(3)


@pytest.mark.parametrize("kind", ["value", "eof", "error"])
@pytest.mark.parametrize("control_first", [False, True])
def test_barrier_publication_control_order(kind, control_first):
    """First-record publication and control have exactly one canonical winner."""
    ready, proceed = threading.Event(), threading.Event()
    published = []
    with scope(0) as (_, owner, context):
        assert context[1].created(streaming=True)
        proposal = REQUEST_CONTROL.submit(context[1].target, uuid4().hex, "hard_interrupt").proposal

        def publish():
            """Delay publication using a barrier instead of sleeps."""
            ready.set()
            if proceed.wait(3):
                published.append(context[1].publish(kind))

        worker = threading.Thread(target=publish)
        worker.start()
        try:
            assert ready.wait(3)
            if control_first:
                with pytest.raises(runtime.LLMControlledInterruptError) as caught:
                    wait._tick(context, owner)
                assert recovery.acknowledge_control(caught.value)
            proceed.set()
            worker.join(3)
            assert not worker.is_alive()
            if not control_first:
                wait._tick(context, owner)
            assert published == [not control_first]
            assert context[1].snapshot().outcome == ("hard_interrupt" if control_first else kind)
        finally:
            proceed.set()
            worker.join(3)


@pytest.mark.parametrize("phase", ["create", "fetch"])
@pytest.mark.parametrize("boundary", ["construct", "start"])
def test_provider_worker_failure_recovers_ticket(monkeypatch, phase, boundary):
    """An interrupted worker handoff retains exact owner/ticket until settled."""
    host = AccountingHost(lambda: iter(["body"]))
    primary = KeyboardInterrupt("worker " + boundary)
    with scope(0) as (_, owner, context):
        if phase == "fetch":
            response, _ = host._create_with_first_byte_timeout([], stream=True, first_byte_timeout=0)
        real_thread = threading.Thread

        def fail(*args, **kwargs):
            """Disarm before injecting so recovery can run normally."""
            monkeypatch.setattr(wait, "threading", threading)
            raise primary

        def construct(*args, **kwargs):
            """Construct the real unstarted thread but interrupt its start once."""
            thread = real_thread(*args, **kwargs)
            monkeypatch.setattr(thread, "start", fail)
            original_join = thread.join

            def join_started(timeout=None):
                """The shared scope helper may observe an unstarted owner."""
                if thread.ident is not None:
                    original_join(timeout)

            monkeypatch.setattr(thread, "join", join_started)
            return thread

        monkeypatch.setattr(wait, "threading", SimpleNamespace(
            Event=threading.Event, RLock=threading.RLock,
            Thread=fail if boundary == "construct" else construct,
        ))
        with pytest.raises(KeyboardInterrupt) as caught:
            if phase == "create":
                host.invoke(True, 0)
            else:
                list(host.iter_stream_with_first_byte_timeout(response, 0))
        assert caught.value is primary
    assert host.llm_request_stat.get_request_stat_info()["request_duration_count"] == 1


@pytest.mark.parametrize("boundary", ["attempt", "application", "invocation"])
@pytest.mark.parametrize("with_primary", [True, False])
def test_context_reset_preserves_existing_host_exception(monkeypatch, boundary, with_primary):
    """A one-shot reset interruption must not replace the original host failure."""
    primary = KeyboardInterrupt("original host interruption")
    reset_error = RuntimeError("context reset interrupted after mutation")
    variable_name = {"attempt": "_ATTEMPT", "application": "_ROUTE",
                     "invocation": "_INVOCATION"}[boundary]
    original = getattr(runtime, variable_name)

    class ResetOnce:
        """Delegate real ContextVar behavior and interrupt only its first reset."""
        armed = True

        def get(self):
            """Read the real current binding."""
            return original.get()

        def set(self, value):
            """Publish using the real ContextVar token."""
            return original.set(value)

        def reset(self, token):
            """Restore first, disarm, then fail at the observed boundary."""
            original.reset(token)
            if self.armed:
                self.armed = False
                raise reset_error

    monkeypatch.setattr(runtime, variable_name, ResetOnce())
    expected = primary if with_primary else reset_error
    with pytest.raises(type(expected)) as caught:
        if boundary == "invocation":
            host = object()
            route = runtime.ControlRoute("unit", 1, host, interrupt_supported=True)

            @runtime.invocation_control
            def invoke(model):
                """Raise through the production invocation restoration boundary."""
                if with_primary:
                    raise primary

            with runtime.application_control_scope(route):
                invoke(host)
            assert route.state == "unavailable"
        else:
            with scope(0):
                if with_primary:
                    raise primary
    assert caught.value is expected
    if with_primary:
        assert any("context reset interrupted after mutation" in note
                   for note in primary.__notes__)
    assert original.get() is None
