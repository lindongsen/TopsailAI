"""Remaining independent U2 boundary checks. Author: DawsonLin."""
import threading
from uuid import uuid4

import pytest

from tests.unit.test_topsailai_ai_base_llm_control_u2_verification import AccountingHost
from tests.unit.test_topsailai_ai_base_llm_control_control_wait import scope
from topsailai.ai_base.llm_control import control_runtime as runtime
from topsailai.ai_base.llm_control import control_wait as wait
from topsailai.ai_base.llm_control import control_recovery as recovery
from topsailai.ai_base.llm_control.attempt_control import AttemptTarget
from topsailai.ai_base.llm_control.request_control import REQUEST_CONTROL
from topsailai.ai_base.llm_control.first_byte_deadline import FirstByteBudget, first_byte_budget_scope
from topsailai.ai_base.llm_control.response_ownership import AttemptResponseOwner, response_ownership_scope


@pytest.mark.parametrize("stream", [False, True])
def test_warning_accounting_parity_at_publication(stream):
    """A late accepted publication warns once and accounts like the legacy path."""
    snapshots = []
    for routed in (False, True):
        clock = [0.0]
        budget = FirstByteBudget.create(1, clock=lambda: clock[0])

        def provider():
            """Cross the warning threshold at the real publication boundary."""
            clock[0] = 2.0
            return iter(["", "body"]) if stream else "body"

        host = AccountingHost(provider)
        with scope(0) if routed else response_ownership_scope():
            with first_byte_budget_scope(budget):
                assert host.invoke(stream, 1) == (["", "body"] if stream else "body")
        assert len(host.warnings) == 1
        snapshots.append(host.llm_request_stat.get_request_stat_info())
    assert snapshots[0] == snapshots[1]


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("mode", ["host", "hard_interrupt", "force_retry"])
def test_late_worker_cannot_recount_abandoned_request(monkeypatch, stream, mode):
    """An admitted blocked creation keeps one failure even after late completion."""
    entered, release = threading.Event(), threading.Event()
    primary = KeyboardInterrupt("host during owned wait")

    def provider():
        """Publish only after the coordinator has abandoned this exact request."""
        entered.set()
        assert release.wait(5)
        return iter(["STALE"]) if stream else "STALE"

    host = AccountingHost(provider)
    original_tick = wait._tick
    with scope(0) as (_, owner, context):
        armed = [True]

        def tick(ctx, exact_owner):
            """Inject after genuine provider admission using an event handshake."""
            if owner.create_thread is not None and armed[0]:
                assert entered.wait(3)
                armed[0] = False
                if mode == "host":
                    raise primary
                REQUEST_CONTROL.submit(ctx[1].target, uuid4().hex, mode)
            return original_tick(ctx, exact_owner)

        monkeypatch.setattr(wait, "_tick", tick)
        try:
            expected = KeyboardInterrupt if mode == "host" else (
                runtime.LLMControlledInterruptError if mode == "hard_interrupt"
                else runtime.LLMRequestedRetryError)
            with pytest.raises(expected) as caught:
                host.invoke(stream, 0)
            if mode == "host":
                assert caught.value is primary
            else:
                assert recovery.acknowledge_control(caught.value)
            before = host.llm_request_stat.get_request_stat_info()
            assert before["total_requests"] == before["request_failures"] == before["request_duration_count"] == 1
            assert before["request_successes"] == 0
        finally:
            release.set()
            if owner.create_thread is not None:
                owner.create_thread.join(3)
                assert not owner.create_thread.is_alive()
        assert host.llm_request_stat.get_request_stat_info() == before


@pytest.mark.parametrize("first", ["control", "publication", "deadline"])
def test_deadline_control_publication_barrier(first):
    """At equality expiry wins unless another terminal already committed."""
    clock = [0.0]
    ready, proceed = threading.Event(), threading.Event()
    outcomes, errors = [], []
    with scope(0) as (_, owner, context):
        authority = context[1]
        authority._clock = lambda: clock[0]
        authority._deadline = 1.0
        authority._raise_timeout = True
        assert authority.created(streaming=True)
        REQUEST_CONTROL.submit(authority.target, uuid4().hex, "hard_interrupt")

        def publish():
            """Publish in another thread only after the chosen boundary."""
            ready.set()
            try:
                assert proceed.wait(3)
                outcomes.append(authority.publish("value"))
            except BaseException as error:
                errors.append(error)

        worker = threading.Thread(target=publish)
        worker.start()
        try:
            assert ready.wait(3)
            if first == "control":
                with pytest.raises(runtime.LLMControlledInterruptError) as caught:
                    wait._tick(context, owner)
                assert recovery.acknowledge_control(caught.value)
            elif first == "deadline":
                clock[0] = 1.0
            proceed.set()
            worker.join(3)
            assert not worker.is_alive() and not errors
            clock[0] = 1.0
            wait._tick(context, owner)
            assert authority.snapshot().outcome == {
                "control": "hard_interrupt", "publication": "value", "deadline": "timeout",
            }[first]
            assert outcomes == [first == "publication"]
        finally:
            proceed.set()
            worker.join(3)


@pytest.mark.parametrize("after", [False, True])
def test_pool_local_removal_interruption_keeps_reconciliation_reachable(after):
    """Before/after exact deletion interrupts do not poison the maintenance lock."""
    pool = recovery.RecoveryPool(1)
    target = AttemptTarget(uuid4().hex, 1, uuid4().hex, uuid4().hex)
    lease = pool.reserve(target, AttemptResponseOwner())
    lease.active = False
    primary = KeyboardInterrupt("local pool removal")

    class InterruptOnce(dict):
        """Disarm before interrupting exact local deletion."""
        armed = True

        def __delitem__(self, key):
            """Expose both transaction sides without affecting other registries."""
            if self.armed:
                self.armed = False
                if after:
                    super().__delitem__(key)
                raise primary
            super().__delitem__(key)

    pool.leases = InterruptOnce(pool.leases)
    with pytest.raises(KeyboardInterrupt) as caught:
        pool.maintain()
    assert caught.value is primary
    assert pool.pass_lock.acquire(False)
    pool.pass_lock.release()
    pool.maintain()
    assert not pool.leases
    assert pool.reserve(target, AttemptResponseOwner()) is not None
    pool.leases[target].active = False
    pool.maintain()


@pytest.mark.parametrize("phase", ["creation", "first_fetch"])
def test_raising_expiry_accounts_once_after_late_worker(monkeypatch, phase):
    """A real started ticket fails once when equality expires an admitted worker."""
    clock = [0.0]
    budget = FirstByteBudget.create(1, clock=lambda: clock[0])
    entered, release = threading.Event(), threading.Event()

    def records():
        """Block the first decoded record when that phase is selected."""
        entered.set()
        assert release.wait(5)
        yield "STALE"

    def provider():
        """Block either creation or first record without wall-clock expiry."""
        if phase == "creation":
            entered.set()
            assert release.wait(5)
            return "STALE"
        return records()

    host = AccountingHost(provider)
    original_tick = wait._tick
    with scope(0) as (_, owner, context):
        context[2]["raise_timeout"] = True
        context[1]._deadline = 1.0
        context[1]._clock = lambda: clock[0]
        context[1]._raise_timeout = True

        def tick(ctx, exact_owner):
            """Move to equality only after the exact provider phase begins."""
            if entered.is_set():
                clock[0] = 1.0
            return original_tick(ctx, exact_owner)

        monkeypatch.setattr(wait, "_tick", tick)
        try:
            with first_byte_budget_scope(budget), pytest.raises(TimeoutError):
                host.invoke(phase == "first_fetch", 1, raising=True)
            before = host.llm_request_stat.get_request_stat_info()
            assert before["total_requests"] == before["request_failures"] == before["request_duration_count"] == 1
            assert len(host.warnings) == 1
        finally:
            release.set()
            for worker in (owner.create_thread, owner.fetch_thread):
                if worker is not None:
                    worker.join(3)
                    assert not worker.is_alive()
        assert host.llm_request_stat.get_request_stat_info() == before
