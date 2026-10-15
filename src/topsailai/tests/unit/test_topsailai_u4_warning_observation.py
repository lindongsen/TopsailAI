"""Focused checks for U4 warning observations and cleanup evidence."""

import pytest

from tests.bdd.llm_first_byte_deadline_harness import should_signal_timing_completion
from tests.bdd.llm_first_byte_warning_observation import (
    WarningObservation,
    assert_transparent_call,
)


def test_warning_completion_requires_completed_abandoned_owner_and_ticket():
    """Accept only exact terminal cleanup evidence used by U4."""
    owner = type("Owner", (), {"_abandoned": True})()
    ticket = object()
    record = {
        "operation": "finish", "completed": True, "initiator": owner,
        "expected_ticket": ticket, "ticket": ticket, "source": "owner",
        "abandoned_before": True,
    }
    assert should_signal_timing_completion(record, ticket)
    record["ticket"] = object()
    assert not should_signal_timing_completion(record, ticket)


def test_warning_completion_rejects_incomplete_or_non_owner_evidence():
    """Reject incomplete callbacks and invocation-only cleanup records."""
    owner = type("Owner", (), {"_abandoned": True})()
    ticket = object()
    record = {
        "operation": "finish", "completed": False, "initiator": owner,
        "expected_ticket": ticket, "ticket": ticket, "source": "owner",
        "abandoned_before": True,
    }
    assert not should_signal_timing_completion(record, ticket)
    record["completed"] = True
    record["source"] = "invocation"
    assert should_signal_timing_completion(record, ticket)


def test_observer_transparency_and_exception_identity():
    """Observer delegates preserve exact results and exception identity."""
    from topsailai.ai_base.llm_control.first_byte_deadline import FirstByteBudget, FirstBytePhase
    from topsailai.ai_base.llm_control.response_ownership import AttemptResponseOwner, bind_response_owner
    failure = RuntimeError("same")
    original_publish = FirstBytePhase.publish

    def raising_publish(*args, **kwargs):
        raise failure

    FirstBytePhase.publish = raising_publish
    observer = WarningObservation().start()
    try:
        owner = AttemptResponseOwner()
        phase = FirstBytePhase(FirstByteBudget.create(1))
        with bind_response_owner(owner):
            with pytest.raises(RuntimeError) as caught:
                phase.publish(allow_late=True)
        assert caught.value is failure
    finally:
        observer.stop()
        FirstBytePhase.publish = original_publish


def test_observer_start_stop_is_scoped_and_idempotent():
    """Observer installation is reversible and repeated start is harmless."""
    observer = WarningObservation()
    assert observer.start() is observer
    assert observer.start() is observer
    observer.stop()
    observer.stop()
    assert observer.events == []


def test_observer_delegate_records_real_phase_and_identity():
    """Installed observer delegates preserve publication and close identities."""
    from topsailai.ai_base.llm_control.first_byte_deadline import FirstByteBudget, FirstBytePhase
    from topsailai.ai_base.llm_control.response_ownership import AttemptResponseOwner, bind_response_owner

    observer = WarningObservation().start()
    try:
        owner = AttemptResponseOwner()
        phase = FirstBytePhase(FirstByteBudget.create(1))
        with bind_response_owner(owner):
            assert phase.publish(allow_late=True) is True
        events = observer.phase_events()
        assert events and events[0]["owner"] is owner
        assert events[0]["budget"] is phase.budget
    finally:
        observer.stop()


@pytest.mark.parametrize("raw_failure", [False, True])
def test_observer_stop_restores_raw_close_after_failure(raw_failure):
    """Observer wraps raw close, preserves its failure, and restores identity."""
    from topsailai.ai_base.llm_pool.openai_client_pool import OpenAIResponseAdapter
    from topsailai.ai_base.llm_control.response_ownership import AttemptResponseOwner

    class Raw:
        """Minimal raw SDK response with an injectable close failure."""

        def close(self):
            """Raise the injected error or return the normal close result."""
            if raw_failure:
                raise failure
            return "closed"

    failure = RuntimeError("raw close failure")
    raw = Raw()
    original_raw_close = raw.close
    stream = OpenAIResponseAdapter._ClosableOpenAIStream(raw, lambda error: error)
    observer = WarningObservation().start()
    owner = AttemptResponseOwner()
    try:
        owner.publish_response(stream)
        assert raw.close is not original_raw_close
        if raw_failure:
            with pytest.raises(RuntimeError) as caught:
                stream.close()
            assert caught.value is failure
        else:
            assert stream.close() is None
        close_events = observer.events_for("stream_close_after")
        assert len(close_events) == 1
        assert close_events[0]["raw"] is raw
        assert close_events[0]["stream"] is stream
    finally:
        observer.stop()
    assert raw.close.__func__ is original_raw_close.__func__
    assert raw.close.__self__ is original_raw_close.__self__



def test_observer_retains_restoration_debt_after_restore_failure(monkeypatch):
    """A restoration failure keeps the observer marked active for recovery."""
    observer = WarningObservation().start()
    original_stop = observer._patches[0].stop
    failure = RuntimeError("restore failure")

    def fail_stop():
        """Inject one delegate restoration failure."""
        raise failure

    monkeypatch.setattr(observer._patches[0], "stop", fail_stop)
    with pytest.raises(RuntimeError) as caught:
        observer.stop()
    assert caught.value is failure
    assert observer._started is True
    assert observer.restoration_complete is False
    monkeypatch.setattr(observer._patches[0], "stop", original_stop)
    observer.stop()
    assert observer.restoration_complete is True


@pytest.mark.parametrize(
    "module_name",
    [
        "tests.bdd.steps.test_llm_first_byte_timeout_warning_steps",
        "tests.bdd.steps.test_llm_first_byte_timeout_retry_steps",
    ],
)
def test_context_reference_is_removed_when_exit_fails(module_name):
    """Both BDD finalizers remove state while preserving the exact exit error."""
    import importlib

    module = importlib.import_module(module_name)
    nodeid = f"u4-context-failure:{module_name}"
    failure = RuntimeError(f"cleanup failure:{module_name}")

    class BrokenContext:
        """Raise one stable exception from scenario context exit."""

        def __exit__(self, *args):
            """Raise the injected cleanup exception."""
            raise failure

    context = BrokenContext()
    module._CONTEXTS[nodeid] = {"context": context}
    with pytest.raises(RuntimeError) as caught:
        module._cleanup_context(nodeid, context)
    assert caught.value is failure
    assert nodeid not in module._CONTEXTS


def test_observer_settled_preserves_host_interruption_after_all_joins():
    """Finish independent joins while preserving the exact host interruption."""
    interruption = KeyboardInterrupt("cancel settlement")

    class Worker:
        """Worker double that interrupts only its join operation."""

        def __init__(self):
            self.joined = False

        def join(self, timeout):
            """Raise the injected host interruption once."""
            self.joined = True
            raise interruption

        def is_alive(self):
            """Report that the worker settled after the interrupted join."""
            return False

    class Event:
        """Completion event double."""

        def wait(self, timeout):
            """Report completed cleanup."""
            return True

    owner = type("Owner", (), {})()
    owner.create_thread = Worker()
    owner.fetch_thread = Worker()
    owner.cleanup_thread = Worker()
    owner.close_finished_event = Event()
    owner._close_state = type("State", (), {"name": "CLOSED"})()
    owner.disposal_error = None
    with pytest.raises(KeyboardInterrupt) as caught:
        WarningObservation().assert_settled([owner])
    assert caught.value is interruption
    assert owner.create_thread.joined
    assert owner.fetch_thread.joined
    assert owner.cleanup_thread.joined
def test_recover_scenario_patches_restores_both_owners():
    """The recovery entry retries observer and owner patch restoration together."""
    from tests.bdd.llm_first_byte_deadline_harness import ScenarioPatchRecovery

    calls = []

    class Observation:
        """Observer double retaining restoration debt."""
        restoration_complete = False

        def stop(self):
            """Settle observer restoration."""
            calls.append("observer")
            self.restoration_complete = True

    class OwnerPatch:
        """Owner patch double."""

        def stop(self):
            """Settle owner restoration."""
            calls.append("owner")

    recovery = ScenarioPatchRecovery(Observation(), OwnerPatch())
    recovery.recover()
    assert recovery.owner_patch is not None
    assert recovery.observation.restoration_complete
    assert calls == ["observer", "owner"]


def test_recovery_preserves_later_host_interruption_and_diagnostics():
    """Recovery keeps a later host interruption over an earlier ordinary error."""
    from tests.bdd.llm_first_byte_deadline_harness import ScenarioPatchRecovery

    ordinary = RuntimeError("observer restore failed")
    host = KeyboardInterrupt("owner restore interrupted")

    class Observation:
        """Observer double with an ordinary restoration failure."""
        restoration_complete = False

        def stop(self):
            """Raise the ordinary observer failure."""
            raise ordinary

    class OwnerPatch:
        """Owner patch double with a host interruption."""

        def stop(self):
            """Raise the host interruption."""
            raise host

    with pytest.raises(KeyboardInterrupt) as caught:
        ScenarioPatchRecovery(Observation(), OwnerPatch()).recover()
    assert caught.value is host
    assert any("observer restore failed" in note for note in caught.value.__notes__)



def test_real_harness_model_close_failure_releases_server(monkeypatch):
    """A real loopback scenario still shuts down independent resources after close fails."""
    from tests.bdd.llm_first_byte_deadline_harness import (
        production_deadline_scenario,
        server_config,
    )

    failure = RuntimeError("model close failure")
    context = production_deadline_scenario(
        monkeypatch,
        stream=False,
        timeout=1.0,
        raise_on_timeout=False,
        server_config=server_config(stream=False),
    )
    data = context.__enter__()
    original_close = data["model"].close
    failed = False

    def fail_close():
        """Inject one model cleanup failure after the real request completes."""
        nonlocal failed
        data["model"].close = original_close
        original_close()
        if failed:
            return None
        failed = True
        raise failure

    data["model"].close = fail_close
    with pytest.raises(RuntimeError) as caught:
        context.__exit__(None, None, None)
    assert caught.value is failure
    assert data["server"].socket.fileno() == -1


def test_real_harness_settlement_gate_retries_before_recovery(monkeypatch):
    """A failed settlement retains both patches until the real recovery succeeds."""
    from tests.bdd.llm_first_byte_deadline_harness import (
        production_deadline_scenario,
        server_config,
    )
    from tests.bdd.llm_first_byte_warning_observation import WarningObservation
    from topsailai.ai_base.llm_control.first_byte_deadline import FirstBytePhase
    from topsailai.ai_base.llm_control.response_ownership import AttemptResponseOwner

    original_publish = FirstBytePhase.publish
    original_owner_init = AttemptResponseOwner.__init__
    observation = WarningObservation()
    context = production_deadline_scenario(
        monkeypatch,
        stream=True,
        timeout=1.0,
        raise_on_timeout=False,
        server_config=server_config(stream=True, replies=("full answer",)),
        observation=observation,
    )
    data = context.__enter__()
    failure = RuntimeError("persistent settlement failure")
    original_settled = observation.assert_settled

    def fail_settlement(owners):
        """Keep settlement faulted until the recovery gate is deliberately cleared."""
        raise failure

    observation.assert_settled = fail_settlement
    try:
        with pytest.raises(RuntimeError) as caught:
            context.__exit__(None, None, None)
        assert caught.value is failure
        assert FirstBytePhase.publish is not original_publish
        assert AttemptResponseOwner.__init__ is not original_owner_init
        assert not observation.restoration_complete

        with pytest.raises(RuntimeError) as caught:
            data["recovery"].recover()
        assert caught.value is failure
        assert FirstBytePhase.publish is not original_publish
        assert AttemptResponseOwner.__init__ is not original_owner_init
        assert not observation.restoration_complete

        observation.assert_settled = original_settled
        data["recovery"].recover()
        assert observation.restoration_complete
        assert FirstBytePhase.publish is original_publish
        assert AttemptResponseOwner.__init__ is original_owner_init
        assert data["server"].socket.fileno() == -1
    finally:
        observation.assert_settled = original_settled
        if not observation.restoration_complete:
            try:
                data["recovery"].recover()
            except BaseException:
                observation.stop()
