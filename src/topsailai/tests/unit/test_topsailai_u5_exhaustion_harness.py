"""Unit checks for the bounded U5 exhaustion harness contract."""

from tests.bdd.llm_first_byte_exhaustion_harness import (
    ATTEMPTS,
    FIRST_BYTE_TIMEOUT,
    RAW_LIMIT,
    RELEASE_LIMIT,
    SETTLEMENT_LIMIT,
)


def test_u5_limits_and_attempt_count_are_bounded():
    """Keep the acceptance constants aligned with the approved design."""
    assert ATTEMPTS == 18
    assert FIRST_BYTE_TIMEOUT == 1.0
    assert RELEASE_LIMIT == 3.0
    assert RAW_LIMIT == 4.0
    assert SETTLEMENT_LIMIT == 30.0


def test_u5_phase_names_are_explicit():
    """Require the two real transport phases used by the BDD outline."""
    from tests.bdd.llm_first_byte_exhaustion_harness import ExhaustionScenario

    assert ExhaustionScenario.__dict__["_wait_prerequisites"].__name__ == "_wait_prerequisites"
    assert ExhaustionScenario.__dict__["_release_once"].__name__ == "_release_once"


def test_u5_settlement_method_is_callable_and_support_is_one_way():
    """Require the real settlement boundary and acyclic support import."""
    import ast
    import importlib
    import sys
    from pathlib import Path

    harness = Path(__file__).parents[1] / "bdd" / "llm_first_byte_exhaustion_harness.py"
    tree = ast.parse(harness.read_text())
    scenario = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ExhaustionScenario")
    settle = next(node for node in scenario.body if isinstance(node, ast.FunctionDef) and node.name == "_settle")
    assert settle.lineno > 0
    support_source = Path(__file__).parents[1] / "bdd" / "llm_first_byte_exhaustion_support.py"
    assert "llm_first_byte_exhaustion_harness" not in support_source.read_text()
    module = importlib.import_module("tests.bdd.llm_first_byte_exhaustion_harness")
    assert callable(module.ExhaustionScenario.__dict__["_settle"])


def test_u5_resources_release_late_handles_and_retain_first_failure():
    """Late accepted handles are released and only the first failure is retained."""
    import threading
    from tests.bdd.llm_first_byte_exhaustion_support import ScenarioResources

    condition = threading.Condition()
    failures = []
    resources = ScenarioResources(condition, failures.append, {"settlement": 1.0})

    class Handle:
        """Record recovery release without performing network I/O."""

        def __init__(self):
            self.released = 0

        def release_delay(self):
            self.released += 1

    handle = Handle()
    resources.arm_recovery()
    assert resources.retain_handle("primary", 1, handle)
    assert handle.released == 1
    assert resources.recovery_armed


def test_u5_observation_preserves_original_timestamp_and_returns_none():
    """Notification uses the stored observer timestamp and no arbitrary return value."""
    from tests.bdd.llm_first_byte_exhaustion_support import NotifyingObservation

    events = []
    observation = NotifyingObservation(events.append)
    assert observation._append("response_before", owner=object()) is None
    assert events
    assert events[0]["kind"] == "response_before"
    assert "at" in events[0]


def test_u5_constructor_is_resource_free_and_prepare_follows_finalizer(monkeypatch):
    """Construction cannot acquire sockets before fixture recovery custody exists."""
    from tests.bdd.llm_first_byte_exhaustion_harness import ExhaustionScenario
    from tests.bdd import llm_first_byte_exhaustion_support as support

    calls = []
    monkeypatch.setattr(support, "create_server", lambda config: calls.append(config))
    scenario = ExhaustionScenario("headers")
    assert not calls
    assert not scenario.resources.entries


def test_u5_dead_unmarked_worker_joins_once_and_old_deadline_is_ignored():
    """A positive dead identity settles immediately and retained proof avoids rejoining."""
    import time
    from tests.bdd.llm_first_byte_exhaustion_evidence import RunState
    from tests.bdd.llm_first_byte_exhaustion_support import ScenarioResources

    class DeadWorker:
        """Expose a dead started worker whose start-return bookkeeping was interrupted."""
        ident = 123

        def __init__(self):
            self.joins = 0

        def is_alive(self):
            """Report actual exit."""
            return False

        def join(self, seconds):
            """Count exact join operations."""
            self.joins += 1

    resources = ScenarioResources(RunState(), {})
    worker = DeadWorker()
    resources.register_worker(worker, "settler", time.monotonic() + 1)
    proof = resources.join_worker(worker, time.monotonic() + 1, recovery=True)
    assert resources.join_worker(worker, 0) is proof
    assert worker.joins == 1


def test_u5_inflight_absent_identity_is_not_never_started():
    """An interrupted start retains uncertainty even with no thread ident."""
    import time
    import pytest
    from tests.bdd.llm_first_byte_exhaustion_evidence import RunState
    from tests.bdd.llm_first_byte_exhaustion_support import ScenarioResources
    import threading

    resources = ScenarioResources(RunState(), {})
    worker = threading.Thread(target=lambda: None)
    entry = resources.register_worker(worker, "settler", time.monotonic() + 1)
    entry["start"] = "STARTING"
    assert resources.join_worker(worker, time.monotonic() + 0.01, recovery=True, slice_only=True) is None
    assert entry["joined"] is None
    with pytest.raises(AssertionError, match="deadline"):
        resources.join_worker(worker, time.monotonic() - 1, recovery=True)


def test_u5_supervisor_retries_live_signalled_settler_without_second_notification():
    """The actual supervisor continues after a notification preceding thread exit."""
    import time
    import threading
    from tests.bdd.llm_first_byte_exhaustion_harness import ExhaustionScenario

    scenario = ExhaustionScenario("headers")
    scenario.state.deadline = time.monotonic() + 2
    row = scenario.state.allocate(object())
    row.settlement_deadline = scenario.state.deadline
    row["candidate"] = {"candidate_at": time.monotonic()}

    class Worker:
        """Exit after one incomplete exact join slice without another notification."""
        ident = 123

        def __init__(self):
            self.joins = 0

        def join(self, seconds):
            """Make only the second join observe exit."""
            self.joins += 1

        def is_alive(self):
            """Keep the first signalled slice live."""
            return self.joins < 2

    worker = Worker()
    row["settlement_worker"] = worker
    scenario.resources.register_worker(worker, "settler", row.settlement_deadline, row.owner)
    scenario.state.seal_settlers()
    scenario._service_settlers()
    assert row.completed_bundle is not None
    assert worker.joins == 2
    assert scenario.state.settlement_supervisor_done
    assert not scenario.state.coordinator_done
    assert threading.current_thread() is not worker


def test_u5_sealed_admission_rejects_new_settler():
    """A failed final startup cannot reopen supervisor admission."""
    import threading
    import pytest
    from tests.bdd.llm_first_byte_exhaustion_harness import ExhaustionScenario

    scenario = ExhaustionScenario("headers")
    scenario.state.seal_settlers()
    with pytest.raises(AssertionError, match="sealed"):
        scenario.resources.register_worker(threading.Thread(), "settler", 1)


def test_u5_wait_checks_failure_before_success():
    """A true predicate cannot mask a previously recorded failure."""
    import time
    import pytest
    from tests.bdd.llm_first_byte_exhaustion_evidence import RunState

    state = RunState()
    error = RuntimeError("observation")
    state.publish_failure(error)
    with pytest.raises(RuntimeError) as caught:
        state.wait_until(lambda: True, time.monotonic() + 1)
    assert caught.value is error


def test_u5_actual_coordinator_holds_control_before_final_release(monkeypatch):
    """Drive the real coordinator and retain both final-attempt prerequisites."""
    import time
    from types import SimpleNamespace
    from tests.bdd.llm_first_byte_exhaustion_harness import ExhaustionScenario
    from topsailai.ai_base.exception import LLMRetryExhaustedError

    scenario = ExhaustionScenario("headers")
    scenario.state.deadline = time.monotonic() + 10
    trace = []
    final_error = object()
    terminal = LLMRetryExhaustedError.__new__(LLMRetryExhaustedError)
    terminal.last_error = final_error
    scenario.state.publish_terminal(terminal)

    def prerequisites(ordinal, deadline):
        """Provide already timeout-ready rows while retaining actual coordination."""
        row = scenario.state.allocate(object())
        row.update(release_deadline=deadline, error=final_error)
        row.settlement_deadline = deadline
        return row

    def release(row):
        """Observe the order rather than manufacturing coordinator results."""
        trace.append(("release", row.ordinal))
        row.release_returned = time.monotonic()
        return row.release_returned

    def start(worker):
        """Complete a registered settler as the supervisor would for this order test."""
        entry = scenario.resources.workers[id(worker)]
        row = next(row for row in scenario.records.values() if row.get("settlement_worker") is worker)
        scenario.settlements[row.ordinal] = {"success": True}
        entry["joined"] = {"thread": worker, "at": time.monotonic()}

    def control(deadline):
        """Independently verify terminal and completed-one-through-seventeen gates."""
        assert scenario.state.terminal_error is terminal
        assert set(scenario.settlements) == set(range(1, 18))
        trace.append(("held", 0))
        return {"at": time.monotonic()}

    monkeypatch.setattr(scenario, "_wait_prerequisites", prerequisites)
    monkeypatch.setattr(scenario, "_release_once", release)
    monkeypatch.setattr(scenario.resources, "start_worker", start)
    monkeypatch.setattr(scenario.resources, "start_control", control)
    monkeypatch.setattr(scenario.resources, "close_primary", lambda deadline: trace.append(("primary_close", 0)))
    monkeypatch.setattr(scenario.resources, "assert_control_held", lambda: trace.append(("survival", 0)))
    monkeypatch.setattr(scenario.resources, "finish_control", lambda deadline: trace.append(("control_finish", 0)))
    capture = SimpleNamespace(wait_for_request=lambda number, timeout: False)
    scenario.resources.retain("primary", SimpleNamespace(server=SimpleNamespace(lifecycle_capture=capture)))
    scenario._coordinate()
    scenario.state.raise_failure()
    assert trace.index(("held", 0)) < trace.index(("release", 18))
    assert trace.index(("release", 18)) < trace.index(("primary_close", 0))
    assert trace.index(("primary_close", 0)) < trace.index(("survival", 0))
    assert trace.index(("survival", 0)) < trace.index(("control_finish", 0))
    assert scenario.state.no_more_settlers
    assert scenario.state.coordinator_done


def test_u5_start_failure_preserves_exact_exception_and_custody():
    """A start delegate exception remains original and its worker remains registered."""
    import pytest
    from tests.bdd.llm_first_byte_exhaustion_evidence import RunState
    from tests.bdd.llm_first_byte_exhaustion_support import ScenarioResources

    failure = KeyboardInterrupt("start")

    class Worker:
        """Simulate interruption before start can prove a target identity."""
        ident = None

        def start(self):
            """Raise the exact interruption."""
            raise failure

    state = RunState()
    resources = ScenarioResources(state, {})
    worker = Worker()
    resources.register_worker(worker, "settler", 1)
    with pytest.raises(KeyboardInterrupt) as caught:
        resources.start_worker(worker)
    assert caught.value is failure
    assert state.failure_to_raise() is failure
    assert resources.workers[id(worker)]["start"] == "START_RAISED"
    assert resources.workers[id(worker)]["joined"] is None


def test_u5_recovery_disposes_before_discovering_late_cleanup():
    """Recovery retains and joins a cleanup worker created by owner disposal."""
    import threading
    import time
    from tests.bdd.llm_first_byte_exhaustion_evidence import RunState
    from tests.bdd.llm_first_byte_exhaustion_support import ScenarioResources

    trace = []

    class Owner:
        """Publish a real late cleanup worker only when disposal starts."""

        def __init__(self):
            """Retain close completion before scheduling."""
            self.cleanup_thread = None
            self.close_finished_event = threading.Event()

        def dispose(self, background=True):
            """Start exactly one cleanup producer."""
            if self.cleanup_thread is not None:
                return
            trace.append("dispose")
            self.cleanup_thread = threading.Thread(target=self.close_finished_event.set)
            self.cleanup_thread.start()

    resources = ScenarioResources(RunState(), {})
    owner = Owner()
    resources.register_owner(owner)
    resources.recover(time.monotonic() + 2)
    entry = resources.workers[id(owner.cleanup_thread)]
    assert trace == ["dispose"]
    assert entry["joined"]["thread"] is owner.cleanup_thread
    assert owner.close_finished_event.is_set()
    assert resources.restoration_complete


def test_u5_external_registered_worker_requires_closed_spawning_authority():
    """Missing identity cannot discharge a worker while its spawning scope is open."""
    import threading
    import time
    from tests.bdd.llm_first_byte_exhaustion_evidence import RunState
    from tests.bdd.llm_first_byte_exhaustion_support import ScenarioResources

    state = RunState()
    resources = ScenarioResources(state, {})
    owner = object()
    row = state.allocate(object())
    row.owner = owner
    row["invocation_exited"] = True
    worker = threading.Thread()
    resources.register_worker(worker, "create", None, owner, starter=(owner, "create"))
    token = object()
    resources.note_spawn_scope(owner, "create_guard", token, "ENTERED")
    resources.arm_recovery()
    deadline = time.monotonic() + 1
    assert resources.join_worker(worker, deadline, recovery=True, slice_only=True) is None
    resources.note_spawn_scope(owner, "create_guard", token, "EXITED")
    proof = resources.join_worker(worker, deadline, recovery=True)
    assert proof["never_started"] is True


def test_u5_restoration_gate_retains_diagnostic_debt():
    """Even empty concrete custody cannot restore after failed diagnostic retention."""
    import time
    import pytest
    from tests.bdd.llm_first_byte_exhaustion_evidence import RunState
    from tests.bdd.llm_first_byte_exhaustion_support import ScenarioResources

    state = RunState()
    resources = ScenarioResources(state, {})
    state.retention_failed = True
    with pytest.raises(AssertionError, match="retention debt"):
        resources.recover(time.monotonic() + 1)
    assert not resources.restoration_complete


def test_u5_worker_duplicate_binding_preserves_facts_and_rejects_conflict():
    """Idempotent registration cannot renew a deadline or replace owner identity."""
    import threading
    import pytest
    from tests.bdd.llm_first_byte_exhaustion_evidence import RunState
    from tests.bdd.llm_first_byte_exhaustion_support import ScenarioResources

    resources = ScenarioResources(RunState(), {})
    worker = threading.Thread()
    owner = object()
    entry = resources.register_worker(worker, "create", 1, owner, starter=owner)
    assert resources.register_worker(worker, "create", 1, owner, starter=owner) is entry
    with pytest.raises(AssertionError, match="deadline"):
        resources.register_worker(worker, "create", 2, owner)
    with pytest.raises(AssertionError, match="binding"):
        resources.register_worker(worker, "create", 1, object())
    assert entry["deadline"] == 1


def test_u5_late_join_cannot_manufacture_timely_normal_evidence(monkeypatch):
    """A join that returns after Si retains no normal success proof."""
    import pytest
    from types import SimpleNamespace
    from tests.bdd import llm_first_byte_exhaustion_support as support
    from tests.bdd.llm_first_byte_exhaustion_evidence import RunState

    clock = [1.0]

    class Worker:
        """Publish actual exit only after advancing the local clock beyond Si."""
        ident = 123

        def join(self, seconds):
            """Return late rather than blocking the test."""
            clock[0] = 3.0

        def is_alive(self):
            """The worker exited, but that alone is not timely proof."""
            return False

    monkeypatch.setattr(support, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    resources = support.ScenarioResources(RunState(), {})
    worker = Worker()
    entry = resources.register_worker(worker, "create", 2)
    with pytest.raises(AssertionError, match="deadline"):
        resources.join_worker(worker, 2)
    assert entry["joined"] is None




def test_u5_actual_settler_supervisor_join_and_completed_long_gaps(monkeypatch):
    """Use real candidate admission and joins while holding target exit after notification."""
    import threading
    from types import SimpleNamespace
    from tests.bdd import llm_first_byte_exhaustion_harness as harness
    from tests.bdd import llm_first_byte_exhaustion_support as support
    from tests.bdd import llm_first_byte_exhaustion_evidence as evidence

    from tests.unit.test_topsailai_u5_exhaustion_acceptance import _u5_valid_candidate

    for mode in ("headers", "first_item"):
        scenario = harness.ExhaustionScenario(mode)
        state, resources = scenario.state, scenario.resources
        clock = [3.6]
        local_time = SimpleNamespace(monotonic=lambda: clock[0])
        for module in (harness, support, evidence):
            monkeypatch.setattr(module, "time", local_time)
        state.deadline = 200
        row, external = _u5_valid_candidate(mode)
        state.records[1] = row
        owner = row.owner
        owner.close_finished_event = threading.Event()
        owner.close_finished_event.set()
        owner._close_state = SimpleNamespace(name="SUCCEEDED")
        owner.close_error = owner.disposal_error = None
        owner.primary_error = row["error"]
        row["invocation_exited"] = True
        row.events = external["events"]
        state.ledger = SimpleNamespace(snapshot=lambda: external["callbacks"], validate=lambda entries: None)
        handle = SimpleNamespace(record=dict(connection_closed=True), wait_for_thread_exit=lambda timeout: True)
        row["handle"] = handle
        resources.handles[("primary", 1)] = dict(handle=handle, joined=None)
        token = object()
        resources.note_spawn_scope(owner, "create", token, "ENTERED")
        resources.note_spawn_scope(owner, "create", token, "EXITED")
        owner.create_thread, owner.fetch_thread = threading.Thread(target=lambda: None), None
        owner.cleanup_thread = threading.Thread(target=lambda: None)
        owner.create_thread.start()
        owner.cleanup_thread.start()
        notified, exit_target, completed = threading.Event(), threading.Event(), threading.Event()

        def settle_then_hold():
            """Keep the exact settler alive after its target's final notification."""
            scenario._settle(1, row, row.release_returned)
            notified.set()
            exit_target.wait(2)

        def supervise():
            """Run the actual supervisor until the sealed registry has drained."""
            scenario._service_settlers()
            completed.set()

        worker = threading.Thread(target=settle_then_hold)
        supervisor = threading.Thread(target=supervise)
        resources.register_worker(worker, "settler", row.settlement_deadline, owner)
        row["settlement_worker"] = worker
        resources.register_worker(supervisor, "supervisor", state.deadline)
        try:
            resources.start_worker(worker)
            assert notified.wait(2)
            assert row.get("candidate") is not None and row.completed_bundle is None
            resources.start_worker(supervisor)
            state.seal_settlers()
            assert worker.is_alive() and not completed.is_set()
            exit_target.set()
            assert completed.wait(2)
            resources.join_worker(supervisor, state.deadline)
            state.raise_failure()
            bundle = row.completed_bundle
            assert bundle["settler_join"]["thread"] is worker
            assert bundle["settler_join"]["never_started"] is False
            assert not worker.is_alive() and not supervisor.is_alive()
            assert resources.workers[id(owner.create_thread)]["joined"] is not None
            assert resources.workers[id(owner.cleanup_thread)]["joined"] is not None
            for gap in (35, 85):
                clock[0] += gap
                scenario._service_settlers()
                assert scenario._finalize_settler(1, bundle["settler_join"]) is bundle
                assert state.settlements[1] is bundle
        finally:
            exit_target.set()
            state.seal_settlers()
            for thread in (worker, supervisor, owner.create_thread, owner.cleanup_thread):
                if thread.ident is not None:
                    thread.join(2)
                    assert not thread.is_alive()






def test_u5_acquisition_recovery_table_preserves_returned_custody(monkeypatch):
    """Exercise real prepare/recover across external acquisition and post-mutation faults."""
    import threading
    import time
    import pytest
    from types import SimpleNamespace
    from tests.bdd import llm_first_byte_exhaustion_support as support
    from tests.bdd.llm_first_byte_exhaustion_evidence import RunState

    boundaries = ("server", "retain_server", "listener", "environment", "pool", "lease", "model", "patch")
    for boundary in boundaries:
        state = RunState()
        resources = support.ScenarioResources(state, {})
        fault = RuntimeError(boundary)
        armed, trace = [True], []
        real_retain = resources.retain
        real_patch = resources.patch
        target = SimpleNamespace(value=object())
        original = target.value
        created = []

        def hit(name):
            """Disarm the one-shot boundary before raising for same-owner reconciliation."""
            trace.append(name)
            if name == boundary and armed[0]:
                armed[0] = False
                raise fault

        class Server:
            """Expose a local socket lifecycle without opening a socket."""
            server_address = ("127.0.0.1", 1)

            def __init__(self):
                """Retain listener lifecycle capture as a concrete patch target."""
                self.lifecycle_capture = SimpleNamespace(start=lambda *args: None)
                self.closed = False
                self.release = threading.Event()

            def serve_forever(self):
                """Keep a real listener thread alive until its exact shutdown."""
                self.release.wait(2)

            def shutdown(self):
                """Release only this server's listener."""
                self.release.set()

            def server_close(self):
                """Observe closure of the returned socket stand-in."""
                self.closed = True

        def server(config):
            """Fail before return or hand back one concrete server for immediate custody."""
            hit("server")
            value = Server()
            created.append(value)
            return value

        def retain(name, value):
            """Inject after successful retention, never discard a returned server."""
            result = real_retain(name, value)
            if name == "primary":
                hit("retain_server")
            return result

        initial = {"OPENAI_API_BASE": object(), "unrelated": object()}
        environment = dict(initial)
        missing = object()

        class Environment:
            """Record setup and exact restoration through the actual recovery gate."""

            previous = {}

            def setenv(self, key, value):
                """Fail after an observed environment mutation boundary."""
                self.previous.setdefault(key, environment.get(key, missing))
                environment[key] = value
                hit("environment")

            def undo(self):
                """Restore once after all other independent obligations settle."""
                for key, value in self.previous.items():
                    if value is missing:
                        environment.pop(key)
                    else:
                        environment[key] = value
                trace.append("environment undo")

        class Pool:
            """Keep lease acquisition and pool closure independently observable."""

            def __init__(self):
                """Fail before returning the private pool if selected."""
                hit("pool")

            def acquire(self, config):
                """Fail before a lease is returned, with no invented lease custody."""
                hit("lease")
                return object()

            def release(self, lease):
                """Settle exactly the retained lease."""
                trace.append("lease release")

            def close_all(self):
                """Close the retained pool independently of model acquisition."""
                trace.append("pool close")

        def model(**kwargs):
            """Fail before returning the model, or return a closable local model."""
            hit("model")
            return SimpleNamespace(close=lambda: trace.append("model close"))

        def install(model, receiver):
            """Inject after a real patch has been journaled and applied."""
            real_patch(target, "value", object())
            hit("patch")

        real_start = resources.start_worker

        def start(worker):
            """Interrupt after actual listener launch and retain its exact identity."""
            result = real_start(worker)
            hit("listener")
            return result

        with monkeypatch.context() as patch:
            patch.setattr(support, "create_server", server)
            patch.setattr(support, "MonkeyPatch", Environment)
            patch.setattr(support, "OpenAIClientPool", Pool)
            patch.setattr(support, "build_registry", lambda pool: object())
            patch.setattr(support, "LLMModel", model)
            patch.setattr(resources, "retain", retain)
            patch.setattr(resources, "start_worker", start)
            gate = resources.recovery_gate
            try:
                with pytest.raises(RuntimeError) as caught:
                    resources.prepare("headers", install)
                assert caught.value is fault
                assert not resources.restoration_complete
                assert "environment undo" not in trace
                if boundary == "environment":
                    assert environment["OPENAI_API_BASE"] != initial["OPENAI_API_BASE"]
                assert ("control_lease" in resources.entries) is (boundary in {"model", "patch"})
                resources.recover(time.monotonic() + 3)
                assert resources.recovery_gate is gate
                assert resources.restoration_complete and target.value is original
                assert environment == initial
                assert all(server.closed for server in created)
                assert all(entry["joined"] is not None for entry in resources.workers.values())
                assert trace.count("environment undo") == 1
                from tests.bdd.llm_first_byte_exhaustion_harness import ExhaustionScenario
                scenario = ExhaustionScenario("headers")
                scenario.resources = resources
                scenario.close()
                assert trace.count("environment undo") == 1
            finally:
                for server_value in created:
                    server_value.release.set()
                for entry in resources.workers.values():
                    if entry["thread"].ident is not None:
                        entry["thread"].join(3)
                        assert not entry["thread"].is_alive()
