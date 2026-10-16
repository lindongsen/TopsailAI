"""Diagnostic custody, interruption and recovery checks for U5 exhaustion."""

def test_u5_diagnostics_keep_overflow_and_host_identity():
    """Display chunks never truncate recovery identities or host priority."""
    import pytest
    from tests.bdd.llm_first_byte_exhaustion_evidence import RunState

    state = RunState()
    errors = [RuntimeError(str(index)) for index in range(130)]
    host = KeyboardInterrupt("host")
    for error in errors + [host, errors[0], host]:
        state.publish_failure(error)
    assert len(state.iter_failures()) == 132
    assert sum(error is state.overflow_error for error in state.iter_failures()) == 1
    assert all(len(chunk) <= 128 for chunk in state.diagnostics)
    assert all(any(item is error for item in state.iter_failures()) for error in errors)
    with pytest.raises(KeyboardInterrupt) as caught:
        state.raise_failure()
    assert caught.value is host


def test_u5_transparent_delegate_preserves_both_outcomes():
    """Observer pre/post failures cannot skip or replace an exact delegate outcome."""
    import pytest
    from tests.bdd.llm_first_byte_exhaustion_evidence import RunState

    for before in (True, False):
        for raises in (True, False):
            state = RunState()
            result = object()
            original = KeyboardInterrupt("delegate")
            observation = RuntimeError("observer")
            calls = []

            def delegate(value):
                """Record exactly one saved call and return or raise its exact object."""
                calls.append(value)
                if raises:
                    raise original
                return result

            def observer(call):
                """Fail before delegation or while unwinding its outcome."""
                if before:
                    raise observation
                try:
                    return call(result)
                finally:
                    raise observation

            if raises:
                with pytest.raises(KeyboardInterrupt) as caught:
                    state.transparent(observer, delegate, result)
                assert caught.value is original
            else:
                assert state.transparent(observer, delegate, result) is result
            assert calls == [result]
            assert any(error is observation for error in state.iter_failures())


def test_u5_annotation_failure_retains_later_host_identity():
    """Diagnostic annotation failure is retained and cannot replace a host error."""
    from tests.bdd.llm_first_byte_exhaustion_evidence import RunState

    annotation = RuntimeError("annotation")

    class Unannotatable(KeyboardInterrupt):
        """Reject optional diagnostic attributes while remaining the primary host."""

        def __setattr__(self, name, value):
            """Inject a fallible annotation without mutating shared modules."""
            raise annotation

    state = RunState()
    host = Unannotatable("host")
    state.publish_failure(host)
    assert state.failure_to_raise() is host
    assert any(error is annotation for error in state.iter_failures())


def test_u5_repeated_journal_faults_retain_middle_and_allocator_identities(monkeypatch):
    """Journal allocation failures retain every identity after reporting returns."""
    from tests.bdd.llm_first_byte_exhaustion_evidence import RunState

    state = RunState()
    allocations = []

    def fail_node(*args):
        """Create a distinct, locally injected allocation failure on every attempt."""
        error = MemoryError("journal")
        allocations.append(error)
        raise error

    monkeypatch.setattr(state, "_new_failure_node", fail_node)
    errors = [RuntimeError(str(index)) for index in range(3)]
    for error in errors:
        assert state.publish_failure(error)
    retained = state.iter_failures()
    assert all(any(item is error for item in retained) for error in errors + allocations)
    cursor = state.reserve_cursor
    assert state.publish_failure(errors[1])
    assert state.reserve_cursor == cursor
    assert state.emergency_error is errors[0]
    host = KeyboardInterrupt("first host")
    state.publish_failure(host)
    state.publish_failure(SystemExit("later host"))
    assert state.failure_to_raise() is host
    assert state.retention_failed


def test_u5_zero_and_one_cell_saturation_preserve_delegate_outcomes(monkeypatch):
    """Rejected publication cannot skip delegation or falsely claim complete custody."""
    import pytest
    from tests.bdd.llm_first_byte_exhaustion_evidence import RunState

    for remaining in (0, 1):
        state = RunState()
        allocator = MemoryError("journal")

        def fail_node(*args):
            """Fail only the owned journal seam."""
            raise allocator

        monkeypatch.setattr(state, "_new_failure_node", fail_node)
        originals = [RuntimeError(str(index)) for index in range(256 - remaining)]
        for error in originals:
            assert state._reserve_failure(error, None)
        observation = RuntimeError("observer")
        result = object()
        calls = []

        def observer(call):
            """Reject observation before the saved delegate is invoked."""
            raise observation

        def delegate():
            """Return the original object exactly once despite reporting saturation."""
            calls.append(result)
            return result

        assert state.transparent(observer, delegate) is result
        assert calls == [result]
        assert state.publication_saturated and state.retention_failed
        assert state.publish_failure(observation) is False
        retained = state.iter_failures()
        assert all(any(item is error for item in retained) for error in originals)
        assert any(item is observation for item in retained) is bool(remaining)
        assert not any(item is allocator for item in retained)
        host = KeyboardInterrupt("late host")
        assert state.publish_failure(host) is False
        with pytest.raises(KeyboardInterrupt) as caught:
            state.raise_failure()
        assert caught.value is host

def test_u5_secondary_faults_survive_wrapper_return_and_collection(monkeypatch):
    """Keep first/middle/latest and secondary identities in scenario-owned custody."""
    import gc
    from tests.bdd.llm_first_byte_exhaustion_harness import ExhaustionScenario

    scenario = ExhaustionScenario("headers")
    state = scenario.state
    display = MemoryError("display")
    allocations = []

    class BrokenChunk(list):
        """Fail display allocation independently from identity-node allocation."""

        def append(self, value):
            """Inject only the RunState-owned display fault."""
            raise display

    def node(error, context, previous):
        """Fail secondary retention only, preserving distinct allocator identities."""
        if error is display:
            allocation = MemoryError("secondary journal")
            allocations.append(allocation)
            raise allocation
        return [error, context, previous, True]

    monkeypatch.setattr(state, "_new_failure_node", node)
    state.diagnostics = [BrokenChunk()]
    originals = [RuntimeError(str(i)) for i in range(3)]
    result = object()
    calls = []
    for error in originals:
        def observer(call):
            """Fail before delegation so nonthrowing publication must preserve fallback."""
            raise error

        def delegate():
            """Keep the original return object and exact call count."""
            calls.append(result)
            return result

        assert state.transparent(observer, delegate) is result
    del observer, delegate, error
    gc.collect()
    retained = scenario.state.iter_failures()
    assert calls == [result] * 3
    assert all(sum(item is error for item in retained) == 1 for error in originals + [display] + allocations)
    assert state.emergency_error is originals[0]
    assert state.retention_failed and not state.publication_saturated


def test_u5_annotation_host_selection_and_shared_graph_are_preserved():
    """An annotation host outranks ordinary failures without rewriting shared ancestry."""
    from tests.bdd.llm_first_byte_exhaustion_evidence import RunState

    host = KeyboardInterrupt("annotation host")

    class Unannotatable(RuntimeError):
        """Reject diagnostic attachment with a host interruption."""

        def __setattr__(self, key, value):
            """Inject annotation failure without mutating any exception graph edge."""
            if key == "u5_diagnostics":
                raise host
            super().__setattr__(key, value)

    state = RunState()
    primary = Unannotatable("primary")
    ancestor = ValueError("ancestor")
    diagnostic = RuntimeError("diagnostic")
    primary.__context__ = ancestor
    diagnostic.__context__ = ancestor
    state.publish_failure(primary)
    state.publish_failure(diagnostic)
    assert state.failure_to_raise() is host
    assert any(error is host for error in state.iter_failures())
    assert primary.__context__ is ancestor and diagnostic.__context__ is ancestor
    later = SystemExit("later")
    state.publish_failure(later)
    assert state.failure_to_raise() is host


def test_u5_reserve_recovers_normal_allocator_without_overwriting_cells(monkeypatch):
    """Normal journal recovery keeps earlier reserve custody and identity deduplication."""
    from tests.bdd.llm_first_byte_exhaustion_evidence import RunState

    state = RunState()
    original_node = state._new_failure_node
    allocation = MemoryError("one-shot")

    def fail(*args):
        """Fail exactly the explicitly installed journal seam."""
        raise allocation

    monkeypatch.setattr(state, "_new_failure_node", fail)
    first = RuntimeError("reserve")
    assert state.publish_failure(first)
    cells = tuple(tuple(cell) for cell in state.failure_reserve[:state.reserve_cursor])
    monkeypatch.setattr(state, "_new_failure_node", original_node)
    last = RuntimeError("normal")
    assert state.publish_failure(last)
    assert state.publish_failure(first)
    assert tuple(tuple(cell) for cell in state.failure_reserve[:state.reserve_cursor]) == cells
    assert state.iter_failures() == (first, allocation, last)
def test_u5_diagnostic_allocation_failure_blocks_restoration_and_preserves_host():
    """Allocation failure retains emergency identities and explicit recovery debt."""
    from tests.bdd.llm_first_byte_exhaustion_evidence import RunState

    allocation = MemoryError("retention")

    class BrokenChunk(list):
        """Inject allocation failure only into the run-owned diagnostic chunk."""

        def append(self, value):
            """Reject retention without changing any global allocator."""
            raise allocation

    state = RunState()
    state.diagnostics = [BrokenChunk()]
    host = KeyboardInterrupt("host")
    state.publish_failure(host)
    assert state.retention_failed
    assert state.emergency_error is host
    assert state.emergency_diagnostic is allocation
    assert state.failure_to_raise() is host


def test_u5_graph_attachment_does_not_cycle_through_primary_context():
    """Shared ancestry remains authoritative without attaching a cycle-forming edge."""
    from tests.bdd.llm_first_byte_exhaustion_evidence import RunState

    state = RunState()
    primary = RuntimeError("primary")
    diagnostic = ValueError("diagnostic")
    diagnostic.__context__ = primary
    state.publish_failure(primary)
    state.publish_failure(diagnostic)
    assert state.failure_to_raise() is primary
    assert primary.u5_diagnostics == ()
    assert any(item is diagnostic for item in state.iter_failures())
    assert diagnostic.__context__ is primary


def test_u5_cleanup_continues_with_secondary_journal_debt_and_retains_context(monkeypatch):
    """Actual cleanup and BDD finalization retain the same receiver across retry."""
    import time
    import pytest
    from types import SimpleNamespace
    from tests.bdd.llm_first_byte_exhaustion_harness import ExhaustionScenario
    from tests.bdd.steps import test_llm_first_byte_timeout_exhaustion_steps as steps

    scenario = ExhaustionScenario("headers")
    scenario.state.deadline = time.monotonic() + 2
    resources = scenario.resources
    trace = []
    fault = RuntimeError("close")
    allocation = MemoryError("journal")
    armed = [True]

    class Model:
        """Fail one concrete obligation while leaving the next independently closable."""

        def close(self):
            """Retain the failed resource for the same recovery owner to retry."""
            trace.append("model")
            if armed[0]:
                raise fault

    class Pool:
        """Record independent closure despite prior diagnostic allocation failure."""

        def close_all(self):
            """Complete exactly one unrelated obligation."""
            trace.append("pool")

    def fail_node(*args):
        """Inject only identity-journal allocation failure."""
        raise allocation

    resources.retain("model", Model())
    resources.retain("pool", Pool())
    monkeypatch.setattr(scenario.state, "_new_failure_node", fail_node)
    request = SimpleNamespace(node=SimpleNamespace(nodeid="u5-recovery-custody"))
    steps._CONTEXTS[request.node.nodeid] = scenario
    gate = resources.recovery_gate
    try:
        with pytest.raises(RuntimeError) as caught:
            steps._close(request)
        assert caught.value is fault
        assert trace[:2] == ["model", "pool"]
        assert resources.entries["pool"]["closed"]
        assert not resources.entries["model"]["closed"]
        armed[0] = False
        with pytest.raises(RuntimeError) as caught:
            steps._close(request)
        assert caught.value is fault
        assert resources.entries["model"]["closed"]
        assert trace == ["model", "pool", "model"]
        assert resources.recovery_gate is gate
        assert steps._CONTEXTS[request.node.nodeid] is scenario
        assert not resources.restoration_complete
        assert scenario.state.retention_failed
        assert all(any(item is error for item in scenario.state.iter_failures())
                   for error in (fault, allocation))
    finally:
        steps._CONTEXTS.pop(request.node.nodeid, None)

def test_u5_installed_delegate_outcomes_survive_reporting_faults(monkeypatch):
    """Exercise installed wrappers, not transparent() alone, with exact delegate outcomes."""
    import gc
    import pytest
    from types import SimpleNamespace
    from tests.bdd.llm_first_byte_exhaustion_evidence import RunState
    from tests.bdd.llm_first_byte_exhaustion_support import ScenarioResources

    names = ("_get_first_byte_timeout_config", "_start_llm_request",
             "_create_first_byte_response", "_create_with_first_byte_timeout",
             "iter_stream_with_first_byte_timeout", "_finish_llm_request")
    for name in names:
        for outcome in ("return", "ordinary", "host"):
            for position in ("before", "after"):
                state = RunState()
                resources = ScenarioResources(state, {})
                calls = []
                result = object()
                original_error = RuntimeError("delegate") if outcome == "ordinary" else KeyboardInterrupt("delegate")
                report_error = ValueError("report")
                allocation = MemoryError("journal")

                def delegate(*args, **kwargs):
                    """Preserve a concrete original return or raised object."""
                    calls.append((args, kwargs))
                    if outcome != "return":
                        raise original_error
                    return result

                def stream(*args, **kwargs):
                    """Execute the same delegate once at generator consumption."""
                    yield delegate(*args, **kwargs)

                def fail(*args, **kwargs):
                    """Inject a reporting failure only, never the original delegate."""
                    raise report_error

                def fail_node(*args):
                    """Keep reporting errors in reserve after journal allocation fails."""
                    raise allocation

                def observe(operation, call, ticket, **kwargs):
                    """Inject either side of the installed callback observer."""
                    if position == "before":
                        raise report_error
                    value = call(ticket)
                    raise report_error

                client = SimpleNamespace(max_retries=0, base_url="http://loopback.invalid",
                    _client=SimpleNamespace(_send_single_request=delegate))
                chat = SimpleNamespace(create=delegate, _client=client)
                model = SimpleNamespace(chat_model=chat)
                for method in names + ("call_llm_model_by_stream", "_pause_llm_request", "_resume_llm_request"):
                    setattr(model, method, stream if method == "iter_stream_with_first_byte_timeout" else delegate)
                state.ledger = SimpleNamespace(seal_ticket=fail, record_start=fail, observe_callback=observe)
                monkeypatch.setattr(state, "active_row", fail)
                monkeypatch.setattr(state, "row_for_owner", fail)
                monkeypatch.setattr(state, "_new_failure_node", fail_node)
                monkeypatch.setattr(resources, "note_spawn_scope", fail)
                monkeypatch.setattr(resources, "prepare_observation", lambda *args: None)
                original = getattr(model, name)
                try:
                    state.install(model, resources)
                    installed = getattr(model, name)
                    assert installed is not original
                    args = ({},) if name == "_create_first_byte_response" else (object(),)
                    if name == "_get_first_byte_timeout_config":
                        args = ()
                    actual = None
                    if outcome == "return":
                        actual = installed(*args)
                        if name == "iter_stream_with_first_byte_timeout":
                            actual = list(actual)[0]
                        assert actual is result
                    else:
                        with pytest.raises(BaseException) as caught:
                            actual = installed(*args)
                            if name == "iter_stream_with_first_byte_timeout":
                                list(actual)
                        assert caught.value is original_error
                    assert len(calls) == 1
                    del installed, actual
                    gc.collect()
                    retained = state.iter_failures()
                    reports = outcome == "return" or name not in {
                        "_get_first_byte_timeout_config", "_start_llm_request"}
                    if name == "_finish_llm_request" and position == "after" and outcome != "return":
                        reports = False
                    if reports:
                        assert any(error is report_error for error in retained)
                        assert any(error is allocation for error in retained)
                        assert state.retention_failed
                    else:
                        assert not any(error is report_error for error in retained)
                        if name == "_finish_llm_request" and outcome == "host":
                            assert any(error is original_error for error in retained)
                        else:
                            assert retained == ()
                finally:
                    resources._restore()
                    assert getattr(model, name) is original



def test_u5_reserve_construction_failure_precedes_external_acquisition(monkeypatch):
    """Interrupt the real eighth cell allocation before any resource constructor entry."""
    import pytest
    from tests.bdd import llm_first_byte_exhaustion_harness as harness
    from tests.bdd.llm_first_byte_exhaustion_evidence import RunState

    original_init = RunState.__init__
    original_cell = RunState._new_reserve_cell
    for phase in ("headers", "first_item"):
        for sentinel in (MemoryError("reserve"), KeyboardInterrupt("reserve")):
            entries, cells, acquired = [], [], []

            def fail_cell(state):
                """Use the real allocator seven times, then interrupt the comprehension."""
                entries.append(state)
                if len(entries) == 8:
                    raise sentinel
                cell = original_cell(state)
                cells.append(cell)
                return cell

            def guard(*args, **kwargs):
                """Fail if the resource boundary following RunState is ever entered."""
                acquired.append(args)
                raise AssertionError("external acquisition reached")

            with monkeypatch.context() as patch:
                patch.setattr(RunState, "_new_reserve_cell", fail_cell)
                patch.setattr(harness, "ScenarioResources", guard)
                with pytest.raises(type(sentinel)) as caught:
                    harness.ExhaustionScenario(phase)
                assert caught.value is sentinel
                assert RunState.__init__ is original_init
                assert len(entries) == 8 and all(state is entries[0] for state in entries)
                assert len(cells) == len({id(cell) for cell in cells}) == 7
                assert all(cell == [None, None, None, False] for cell in cells)
                assert entries[0].failure_head is None
                assert not {"failure_reserve", "reserve_cursor", "ledger"} & vars(entries[0]).keys()
                assert acquired == []
            assert RunState.__init__ is original_init and RunState._new_reserve_cell is original_cell
            normal = RunState()
            assert len(normal.failure_reserve) == len({id(cell) for cell in normal.failure_reserve}) == 256
            assert all(cell == [None, None, None, False] for cell in normal.failure_reserve)
            assert normal.reserve_cursor == 0


def test_u5_fault_publication_wakes_waiter_and_true_predicate_cannot_bypass_debt(monkeypatch):
    """One publication wakes a proven waiter despite initial or secondary retention faults."""
    import threading
    import time
    import pytest
    from tests.bdd.llm_first_byte_exhaustion_evidence import RunState

    for position in ("initial", "secondary"):
        for allocator in (MemoryError("allocator"), KeyboardInterrupt("allocator host")):
            state = RunState()
            original, display = RuntimeError("original"), ValueError("display")
            waiting, finished = threading.Event(), threading.Event()
            outcome = []
            real_wait = state.condition.wait
            real_node = state._new_failure_node

            class BrokenChunk(list):
                """Keep display failure separate from journal allocation."""

                def append(self, value):
                    """Raise the exact display diagnostic."""
                    raise display

            def node(error, context, previous):
                """Inject only the selected run-owned journal boundary."""
                if position == "initial" or error is display:
                    raise allocator
                return real_node(error, context, previous)

            def wait(seconds):
                """Signal under the Condition before atomically releasing it."""
                waiting.set()
                return real_wait(seconds)

            def consume():
                """Capture the exact published error without losing host interruptions."""
                try:
                    state.wait_until(lambda: False, time.monotonic() + 2)
                except BaseException as error:
                    outcome.append(error)
                finally:
                    finished.set()

            with monkeypatch.context() as patch:
                patch.setattr(state, "_new_failure_node", node)
                patch.setattr(state.condition, "wait", wait)
                if position == "secondary":
                    state.diagnostics = [BrokenChunk()]
                worker = threading.Thread(target=consume)
                worker.start()
                try:
                    assert waiting.wait(1)
                    assert state.publish_failure(original)
                    assert finished.wait(1)
                    expected = allocator if not isinstance(allocator, Exception) else original
                    assert outcome == [expected]
                    with pytest.raises(type(expected)) as caught:
                        state.wait_until(lambda: True, time.monotonic() + 1)
                    assert caught.value is expected and state.retention_failed
                    assert all(any(item is error for item in state.iter_failures())
                               for error in (original, allocator))
                finally:
                    with state.condition:
                        state.condition.notify_all()
                    worker.join(3)
                    assert not worker.is_alive()


def test_u5_graph_matrix_retains_identity_without_rewriting_edges():
    """Preserve disjoint, shared, descending and cyclic graphs with earliest host priority."""
    import gc
    from tests.bdd.llm_first_byte_exhaustion_evidence import RunState

    for shape in ("disjoint", "shared", "cause", "context", "cycle"):
        for host_first in (False, True):
            state = RunState()
            primary = KeyboardInterrupt("first host") if host_first else RuntimeError("primary")
            diagnostic, ancestor = ValueError("diagnostic"), LookupError("ancestor")
            if shape == "shared":
                primary.__context__ = diagnostic.__context__ = ancestor
            if shape in ("cause", "cycle"):
                diagnostic.__cause__ = primary
            if shape in ("context", "cycle"):
                primary.__context__ = diagnostic
            edges = (primary.__cause__, primary.__context__, diagnostic.__cause__, diagnostic.__context__)
            host = SystemExit("later host")
            for error in (primary, diagnostic, host, diagnostic):
                state.publish_failure(error)
            del error
            gc.collect()
            assert state.failure_to_raise() is (primary if host_first else host)
            assert all(sum(item is error for item in state.iter_failures()) == 1
                       for error in (primary, diagnostic, host))
            assert edges == (primary.__cause__, primary.__context__, diagnostic.__cause__, diagnostic.__context__)



def test_u5_late_cleanup_discovered_after_producers_cannot_authorize_global_restore():
    """Late create/fetch cleanup joins belong to the same owner, not global authority."""
    import threading
    import time
    import pytest
    from types import SimpleNamespace
    from tests.bdd.llm_first_byte_exhaustion_evidence import RunState
    from tests.bdd.llm_first_byte_exhaustion_support import ScenarioResources

    for role in ("create", "fetch"):
        state = RunState()
        resources = ScenarioResources(state, {})
        owner = SimpleNamespace(cleanup_thread=None, close_finished_event=threading.Event())
        row = state.allocate(object())
        row.owner = owner
        row["invocation_exited"] = True
        token, spawned, allow_cleanup = object(), threading.Event(), threading.Event()
        produce_now = threading.Event()
        resources.note_spawn_scope(owner, role, token, "ENTERED")

        def cleanup():
            """Keep late cleanup alive until its exact retained identity is observed."""
            allow_cleanup.wait(2)
            owner.close_finished_event.set()

        def produce():
            """Publish a new cleanup thread before the original producer exits."""
            produce_now.wait(2)
            owner.cleanup_thread = threading.Thread(target=cleanup)
            owner.cleanup_thread.start()
            spawned.set()

        producer = threading.Thread(target=produce)
        setattr(owner, role + "_thread", producer)
        chat_exit = threading.Event()
        chat = threading.Thread(target=lambda: chat_exit.wait(2))
        resources.register_worker(chat, "chat", time.monotonic() + 3)
        resources.start_worker(chat)
        real_join = producer.join

        def join_producer(seconds):
            """Publish cleanup only after the first worker discovery has completed."""
            assert owner.cleanup_thread is None
            produce_now.set()
            real_join(seconds)

        producer.join = join_producer
        producer.start()
        try:
            resources.note_spawn_scope(owner, role, token, "EXITED")
            allow_cleanup.set()
            proof = resources.attempt_quiescent(owner, time.monotonic() + 3)
            assert proof["owner"] is owner and chat.is_alive() and spawned.is_set()
            late_entry = resources.workers[id(owner.cleanup_thread)]
            assert late_entry["owner"] is owner and late_entry["role"] == "cleanup"
            assert resources.workers[id(producer)]["joined"]["thread"] is producer
            assert late_entry["joined"]["thread"] is owner.cleanup_thread
            state.seal_settlers()
            with pytest.raises(AssertionError, match="global worker"):
                resources.global_quiescent(time.monotonic() + 3)
            assert not resources.restoration_complete
            chat_exit.set()
            resources.join_worker(chat, time.monotonic() + 3)
            open_token = object()
            resources.note_spawn_scope(owner, "late", open_token, "ENTERED")
            with pytest.raises(AssertionError, match="spawning authority"):
                resources.global_quiescent(time.monotonic() + 3)
            assert not resources.restoration_complete
            resources.note_spawn_scope(owner, "late", open_token, "EXITED")
            resources.close_normal(time.monotonic() + 3)
            assert resources.restoration_complete
        finally:
            produce_now.set()
            producer.join = real_join
            allow_cleanup.set()
            chat_exit.set()
            for worker in (producer, owner.cleanup_thread, chat):
                if worker is not None and worker.ident is not None:
                    worker.join(3)
                    assert not worker.is_alive()
