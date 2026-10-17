"""Completed-result and composed acceptance checks for U5 exhaustion."""

def _u5_valid_candidate(mode):
    """Build complete identity-linked facts for resource-free validator negatives."""
    from types import SimpleNamespace
    from tests.bdd.llm_first_byte_exhaustion_evidence import AttemptEvidence

    owner = SimpleNamespace(create_thread=object(), fetch_thread=None, cleanup_thread=object())
    invocation = SimpleNamespace(expected_ticket=object())
    raw = SimpleNamespace(is_closed=True)
    response = SimpleNamespace(_response=raw)
    row = AttemptEvidence(1, invocation=invocation, owner=owner, adapter_entry=1,
                          release_returned=3, settlement_deadline=33)
    row.update(phase=mode, raw_deadline=5, release_deadline=4, abandoned_at=2,
               publication=mode == "first_item", configs=[(1.0, True)],
               ticket=invocation.expected_ticket, budget=object(), params={}, error=object(), handle=object())
    row["transport"] = {"timeout": (5, 300), "max_retries": 0, "body": {}}
    if mode == "first_item":
        row["first_item_budget"] = row["budget"]
    row.accept_event({"kind": "response_before", "at": 3.1, "owner": owner, "raw": raw, "response": response})
    events = list(row.events) + [dict(kind=kind, at=at, raw=raw, stream=response)
                                for kind, at in (("stream_close_before", 3.2), ("stream_close_after", 3.3))]
    operations = ["start", "finish", "finish"] if mode == "headers" else ["start", "pause", "resume", "pause", "finish"]
    callbacks = [dict(operation=op, completed=True, error=None, initiator=owner,
                      invocation=invocation, ticket=row["ticket"], source="owner") for op in operations]
    snapshots = dict(owner=owner, invocation=invocation, events=events, close_finished=True,
                     close_state="SUCCEEDED", close_error=None, disposal_error=None, primary_error=row["error"],
                     callbacks=callbacks, handler=dict(handle=row["handle"], thread_exited=True, connection_closed=True),
                     quiescence=dict(owner=owner, invocation_exited=True, scopes=[dict(closed=True)],
                                     workers=[dict(thread=worker, at=3.5) for worker in (owner.create_thread, owner.cleanup_thread)]))
    normalized = dict(connect=5, read=300, write=5, pool=5)
    row["transport_normalized"] = dict(normalized, units="seconds")
    row["http_request"] = SimpleNamespace(extensions={"timeout": normalized})
    thread, owner.fetch_thread = owner.create_thread, owner.create_thread if mode == "first_item" else None
    row["http_thread"] = thread
    phase = "receive_response_headers" if mode == "headers" else "receive_response_body"
    row["http_phases"] = [dict(name="http11." + phase + ".started", at=1.1, thread=thread)]
    row["create_budget_facts"] = dict(budget=row["budget"], timeout=1.0, deadline=2,
                                     before=1, after=1.1, remaining=0.95,
                                     timeout_seconds=1.0, raise_on_timeout=True)
    row["first_item_budget_facts"] = dict(row["create_budget_facts"])
    row["start_boundary"] = dict(owner=owner, invocation=invocation, ticket=row["ticket"],
                                 thread=thread, before=0.8, after=0.9)
    row["config_boundaries"] = [dict(value=(1.0, True), invocation=invocation,
                                    thread=thread, before=0.5, after=0.6)]
    row["callback_boundaries"] = [dict(item, before=3.1 if mode == "headers" else 1.5, after=3.2 if mode == "headers" else 1.6) for item in callbacks[1:]]
    return row, snapshots


def test_u5_mode_specific_candidate_negative_matrix():
    """Reject missing/wrong publication, shared budget, callbacks and dynamic joins."""
    import copy
    import pytest
    from tests.bdd.llm_first_byte_exhaustion_harness import validate_settlement

    for mode in ("headers", "first_item"):
        row, snapshots = _u5_valid_candidate(mode)
        assert validate_settlement(row, snapshots, now=4)["ordinal"] == 1
        for field, bad in (("publication", None), ("publication", mode != "first_item"),
                           ("configs", []), ("ticket", object()), ("abandoned_at", 3.5)):
            saved = row[field]
            row[field] = bad
            with pytest.raises(AssertionError):
                validate_settlement(row, snapshots, now=4)
            row[field] = saved
        for field, bad in (("close_finished", False), ("close_state", "FAILED"), ("callbacks", []),
                           ("primary_error", object())):
            with pytest.raises(AssertionError):
                validate_settlement(row, dict(snapshots, **{field: bad}), now=4)
        for callback_field, bad in (("completed", False), ("ticket", object()), ("source", "UNATTRIBUTED")):
            callbacks = [dict(item) for item in snapshots["callbacks"]]
            callbacks[-1][callback_field] = bad
            with pytest.raises(AssertionError):
                validate_settlement(row, dict(snapshots, callbacks=callbacks), now=4)
        with pytest.raises(AssertionError):
            validate_settlement(row, dict(snapshots, quiescence=dict(snapshots["quiescence"], workers=[])), now=4)
        with pytest.raises(AssertionError):
            validate_settlement(row, snapshots, now=34)
        if mode == "first_item":
            row["first_item_budget"] = None
            with pytest.raises(AssertionError):
                validate_settlement(row, snapshots, now=4)



def _completed_scenario(mode):
    """Build completed consumer input without using it as composed lifecycle proof."""
    from types import SimpleNamespace
    from tests.bdd.llm_first_byte_exhaustion_harness import validate_settlement

    rows = {}
    settlements = {}
    pool = object()
    for ordinal in range(1, 19):
        row, snapshots = _u5_valid_candidate(mode)
        row.ordinal = ordinal
        row["settlement_worker"] = object()
        if ordinal == 18:
            row["terminal_at"] = 2.1
            row["control_before_release"] = dict(
                at=2.5, start_before=2.2, start_returned=2.3, pool=pool,
                client=object(), primary_client=object(), stream=object(),
                control_key="control", primary_key="primary")
            row["primary_close"] = dict(at=4.1)
            control = row["control_before_release"]
            row["control_survival"] = dict(at=4.2, client=control["client"], stream=control["stream"])
            row["control_settlement"] = dict(released=4.3, content="CONTROL", lease_released=True)
            row["no19"] = dict(start=5, end=10)
        candidate = validate_settlement(row, snapshots, now=4)
        row.completed_bundle = dict(candidate, success=True, validated_at=4,
            settler_join=dict(thread=row["settlement_worker"], at=4, never_started=False))
        rows[ordinal] = row
        settlements[ordinal] = row.completed_bundle
    result = dict(bodies=[{} for _ in rows], expected_body={}, releases=list(rows),
                  cleanup=dict(restoration_complete=True), backoff_gaps=[5 * i for i in range(1, 18)],
                  budgets=[row["budget"] for row in rows.values()], rows=tuple(rows.values()),
                  prompt_calls=(), state=dict(dropped_request_body_count=0), terminal_at=2.1)
    result.update(settlements=settlements, final=rows[18], error=object())
    capture = SimpleNamespace(state=lambda: dict(dropped_lifecycle_count=0))
    return SimpleNamespace(records=rows, settlements=settlements, releases=list(rows),
        result=result, chat_error=result["error"], phase=mode, resources=SimpleNamespace(pool=pool),
        primary=SimpleNamespace(server=SimpleNamespace(lifecycle_capture=capture)))


def test_u5_actual_completed_consumers_accept_and_reject_both_modes():
    """Call both registered consumers with complete positives and isolated bad facts."""
    import pytest
    from types import SimpleNamespace
    from tests.bdd.steps import test_llm_first_byte_timeout_exhaustion_steps as steps

    request = SimpleNamespace(node=SimpleNamespace(nodeid="u5-consumer-only"))
    mutations = (
        ("bodies", []), ("bodies", [{}] * 19), ("bodies", [{"wrong": True}] * 18),
        ("prompt_calls", ("prompt",)), ("rows", ()), ("backoff_gaps", []),
        ("backoff_gaps", [0] * 17), ("cleanup", dict(restoration_complete=False)),
        ("state", dict(dropped_request_body_count=1)), ("terminal_at", 3),
    )
    try:
        for mode in ("headers", "first_item"):
            scenario = _completed_scenario(mode)
            steps._CONTEXTS[request.node.nodeid] = scenario
            steps.exact_counts(request)
            steps.terminal_settlement(request)
            for key, bad in mutations:
                saved = scenario.result[key]
                scenario.result[key] = bad
                for consumer in (steps.exact_counts, steps.terminal_settlement):
                    with pytest.raises(AssertionError):
                        consumer(request)
                scenario.result[key] = saved
            row = scenario.records[18]
            for key, bad in (("completed_bundle", None), ("settlement_worker", object()),
                             ("budget", scenario.records[1]["budget"])):
                saved = row[key]
                row[key] = bad
                for consumer in (steps.exact_counts, steps.terminal_settlement):
                    with pytest.raises(AssertionError):
                        consumer(request)
                row[key] = saved
            for key, bad in (("success", False), ("callbacks", []),
                             ("handler", dict(connection_closed=False))):
                saved = row.completed_bundle[key]
                row.completed_bundle[key] = bad
                for consumer in (steps.exact_counts, steps.terminal_settlement):
                    with pytest.raises(AssertionError):
                        consumer(request)
                row.completed_bundle[key] = saved
            paths = (
                (("http_phases",), []),
                (("http_phases",), row["http_phases"] * 2),
                (("transport_normalized", "read"), 0),
                (("create_budget_facts", "budget"), object()),
                (("create_budget_facts", "deadline"), 100),
                (("start_boundary", "owner"), object()),
                (("start_boundary", "ticket"), object()),
                (("start_boundary", "after"), 100),
                (("config_boundaries", 0, "thread"), object()),
                (("callback_boundaries", 0, "ticket"), object()),
                (("callback_boundaries", 0, "after"), 100),
                (("control_before_release", "pool"), object()),
                (("control_before_release", "control_key"), "primary"),
                (("control_before_release", "client"), row["control_before_release"]["primary_client"]),
                (("control_before_release", "start_before"), 0),
                (("control_survival", "client"), object()),
                (("control_survival", "at"), 0),
                (("control_settlement", "content"), "wrong"),
                (("control_settlement", "lease_released"), False),
                (("no19", "end"), 6),
            )
            for path, bad in paths:
                target = row
                for key in path[:-1]:
                    target = target[key]
                saved = target[path[-1]]
                target[path[-1]] = bad
                for consumer in (steps.exact_counts, steps.terminal_settlement):
                    with pytest.raises(AssertionError):
                        consumer(request)
                target[path[-1]] = saved
            steps.exact_counts(request)
            steps.terminal_settlement(request)
    finally:
        steps._CONTEXTS.pop(request.node.nodeid, None)


def test_u5_observer_acquisition_failure_retains_adapter_before_next_boundary(monkeypatch):
    """Start/attach faults retain the actual adapter before cleanup is attempted."""
    import time
    import pytest
    from tests.bdd import llm_first_byte_exhaustion_support as support
    from tests.bdd.llm_first_byte_exhaustion_evidence import RunState

    for boundary in ("start", "attach_model"):
        state = RunState()
        resources = support.ScenarioResources(state, {})
        failure = RuntimeError(boundary)
        trace = []

        class Observation:
            """Expose only the acquired observer lifecycle for deterministic faults."""

            def __init__(self, *args):
                """Record construction before the resource is returned."""
                trace.append("constructed")
                self.stop = lambda: trace.append(("stop", target.value))

            def start(self):
                """Assert retained custody at actual start entry."""
                assert resources.observation is self
                trace.append("start")
                if boundary == "start":
                    raise failure

            def attach_model(self, model):
                """Assert retained custody at model attachment entry."""
                assert resources.observation is self
                trace.append("attach_model")
                raise failure

        target = type("PatchTarget", (), {"value": "original"})()
        resources.patch(target, "value", "patched")
        monkeypatch.setattr(support, "NotifyingObservation", Observation)
        with pytest.raises(RuntimeError) as caught:
            resources.prepare_observation(object(), state.accept_event, state.publish_failure)
        assert caught.value is failure
        assert resources.entries["observation"]["closed"] is False
        assert trace == (["constructed", "start"] if boundary == "start"
                         else ["constructed", "start", "attach_model"])
        resources.recover(time.monotonic() + 3)
        assert trace[-1] == ("stop", "patched") and resources.restoration_complete
        assert target.value == "original" and resources.patches[0][4]
        from tests.bdd.llm_first_byte_exhaustion_harness import ExhaustionScenario
        scenario = ExhaustionScenario("headers")
        scenario.resources = resources
        scenario.close()
        assert trace.count(("stop", "patched")) == 1



def test_u5_real_loopback_transport_both_policies_and_phases():
    """Observe actual SDK requests, phase anchors, owned outcomes and restoration."""
    import threading
    import time
    from tests.bdd.llm_first_byte_exhaustion_harness import ExhaustionScenario
    from topsailai.ai_base.llm_control.exception import LLMProviderTimeoutError

    for phase in ("headers", "first_item"):
        for raises in (False, True):
            scenario = ExhaustionScenario(phase)
            resources, state = scenario.resources, scenario.state
            state.deadline = time.monotonic() + 15
            outcome = {}
            extracted = []
            original_accept = state.accept_event

            def accept(event):
                """Retain expected continuation content without the exhaustion-only assertion."""
                if event.get("kind") == "extract":
                    extracted.append(event.get("content"))
                    return
                original_accept(event)

            state.accept_event = accept
            http = send_patch = None
            done = threading.Event()

            def call():
                """Execute one real owned attempt, never the long production retry loop."""
                try:
                    outcome["result"] = resources.model.call_llm_model_by_stream(
                        [{"role": "user", "content": "bounded transport probe"}])
                except BaseException as error:
                    outcome["error"] = error
                finally:
                    done.set()

            worker = threading.Thread(target=call)
            try:
                scenario.prepare()
                resources.environment.setenv("TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT_RAISE", str(int(raises)))
                http = resources.model.chat_model._client._client
                send_patch = next(entry for entry in resources.patches
                                  if entry[0] is http and entry[1] == "_send_single_request")
                resources.register_worker(worker, "probe", state.deadline)
                resources.start_worker(worker)
                state.wait_until(lambda: ("primary", 1) in resources.handles, state.deadline)
                handle = resources.handles[("primary", 1)]["handle"]
                resources.wait_external(lambda seconds: handle.wait_for_phase(phase, seconds), state.deadline)
                row = state.records[1]
                if raises:
                    assert done.wait(3)
                    assert isinstance(outcome["error"], LLMProviderTimeoutError)
                    assert outcome["error"] is row["error"]
                    assert row["abandoned"] is True
                else:
                    remaining = row["budget"].deadline - time.monotonic() + 0.1
                    assert not done.wait(max(0, remaining))
                    assert row.owner._abandoned is False
                released = resources.release_handle("primary", 1)
                assert done.wait()
                resources.join_worker(worker, state.deadline)
                if not raises:
                    assert "error" not in outcome
                    assert outcome["result"][1] == "STALE_0"
                    assert "STALE_0" in extracted
                state.raise_failure()
                assert row.owner is row.invocation.owner
                assert row["ticket"] is row.invocation.expected_ticket
                assert row["transport"]["client"] is resources.model.chat_model._client
                assert row["transport"]["max_retries"] == 0
                actual = row["http_request"].extensions["timeout"]
                assert actual == {key: row["transport_normalized"][key]
                                  for key in ("connect", "read", "write", "pool")}
                assert actual["read"] == 300
                suffix = "receive_response_headers.started" if phase == "headers" else "receive_response_body.started"
                anchors = [item for item in row["http_phases"] if item["name"].endswith(suffix)]
                assert len(anchors) == 1
                assert row.adapter_entry <= anchors[0]["at"] <= released
                assert released - anchors[0]["at"] < actual["read"]
                state.wait_until(lambda: row.raw_event is not None, state.deadline)
                assert row.raw_event["owner"] is row.owner
                capture = scenario.primary.server.request_body_capture.state()
                assert len(capture["request_bodies"]) == 1
                assert capture["request_bodies"][0]["body"] == row["params"]
            finally:
                resources.recover(time.monotonic() + 5)
                assert not worker.is_alive()
                assert resources.restoration_complete
                if send_patch is not None:
                    if send_patch[2]:
                        assert vars(http)["_send_single_request"] is send_patch[3]
                    else:
                        assert "_send_single_request" not in vars(http)


def test_u5_consumers_independently_reject_full_semantic_mutations():
    """Reject one bad fact per invocation, then restore both complete consumer positives."""
    import pytest
    from types import SimpleNamespace
    from tests.bdd.steps import test_llm_first_byte_timeout_exhaustion_steps as steps

    request = SimpleNamespace(node=SimpleNamespace(nodeid="u5-independent-matrix"))
    consumers = (steps.exact_counts, steps.terminal_settlement)
    missing = object()
    try:
        for mode in ("headers", "first_item"):
            scenario = _completed_scenario(mode)
            steps._CONTEXTS[request.node.nodeid] = scenario
            final = scenario.records[18]
            bundle = final.completed_bundle
            cases = [
                ("context", steps._CONTEXTS, request.node.nodeid, missing),
                ("absent result", vars(scenario), "result", missing),
                ("null result", vars(scenario), "result", None),
            ]
            cases.extend(("missing result " + key, scenario.result, key, missing)
                         for key in tuple(scenario.result))
            for count in (17, 19):
                records = dict(scenario.records)
                if count == 17:
                    records.pop(18)
                else:
                    records[19] = final
                cases.extend(((f"records {count}", vars(scenario), "records", records),
                              (f"rows {count}", scenario.result, "rows", tuple(records.values())),
                              (f"requests {count}", scenario.result, "bodies", [{}] * count)))
            cases.extend((
                ("missing completion", final, "completed_bundle", None),
                ("candidate only", final, "completed_bundle", dict(bundle, success=False)),
                ("mismatched completion", scenario.settlements, 18, dict(bundle)),
                ("wrong ordinal", bundle, "ordinal", 17),
                ("wrong settler", bundle["settler_join"], "thread", object()),
                ("unstarted settler", bundle["settler_join"], "never_started", True),
                ("late join", bundle["settler_join"], "at", 34),
                ("late validation", bundle, "validated_at", 34),
                ("candidate after completion", bundle, "candidate_at", 5),
                ("result budget identity", scenario.result, "budgets", [object()] * 18),
                ("duplicate result budget", scenario.result, "budgets", [scenario.result["budgets"][0]] * 18),
                ("result release missing", scenario.result, "releases", []),
                ("result terminal identity", scenario.result, "error", object()),
                ("result final identity", scenario.result, "final", scenario.records[17]),
                ("wrong settlement view", scenario.result, "settlements", dict(scenario.settlements)),
            ))
            cases.extend(("duplicate " + key, final, key, scenario.records[1][key])
                         for key in ("invocation", "owner", "ticket", "budget"))
            paths = (
                (("http_phases", 0, "thread"), object()),
                (("http_phases", 0, "at"), 0),
                (("create_budget_facts", "remaining"), -1),
                (("create_budget_facts", "timeout_seconds"), 180),
                (("create_budget_facts", "raise_on_timeout"), False),
                (("start_boundary", "invocation"), object()),
                (("config_boundaries",), []),
                (("primary_close", "at"), 0),
                (("config_boundaries", 0, "invocation"), object()),
                (("config_boundaries", 0, "value"), (180, False)),
                (("config_boundaries", 0, "before"), 100),
                (("callback_boundaries", 0, "initiator"), object()),
                (("callback_boundaries", 0, "invocation"), object()),
                (("callback_boundaries", 0, "operation"), "wrong"),
                (("control_before_release", "stream"), object()),
                (("control_before_release", "at"), 100),
                (("control_survival", "stream"), object()),
                (("control_settlement", "released"), 0),
                (("no19", "end"), 6),
            )
            for path, bad in paths:
                target = final
                for key in path[:-1]:
                    target = target[key]
                cases.append((repr(path), target, path[-1], bad))
            capture = scenario.primary.server.lifecycle_capture
            cases.append(("dropped lifecycle", vars(capture), "state",
                          lambda: dict(dropped_lifecycle_count=1)))
            for label, target, key, bad in cases:
                saved = target[key]
                try:
                    if bad is missing:
                        del target[key]
                    else:
                        target[key] = bad
                    for consumer in consumers:
                        with pytest.raises(AssertionError) as rejection:
                            consumer(request)
                        assert isinstance(rejection.value, AssertionError), label
                finally:
                    target[key] = saved
                for consumer in consumers:
                    consumer(request)
    finally:
        steps._CONTEXTS.pop(request.node.nodeid, None)


import pytest


@pytest.mark.parametrize("startup_fault", (None, "register", "launch", "mark"))
def test_u5_composed_run_uses_actual_settlers_supervisor_and_caller(monkeypatch, startup_fault):
    """Compose real orchestration with deterministic external facts, not real retry timing."""
    import threading
    from types import SimpleNamespace
    from tests.bdd import llm_first_byte_exhaustion_harness as harness
    from tests.bdd import llm_first_byte_exhaustion_support as support
    from tests.bdd import llm_first_byte_exhaustion_evidence as evidence
    from topsailai.ai_base.exception import LLMRetryExhaustedError
    from topsailai.ai_base.llm_control.exception import LLMProviderTimeoutError

    for mode in ("headers", "first_item"):
        scenario = harness.ExhaustionScenario(mode)
        state, resources = scenario.state, scenario.resources
        clock, trace, callbacks = [3.6], [], []
        fault = KeyboardInterrupt("final " + str(startup_fault))
        release_final = threading.Event()
        real_register, real_settle = resources.register_worker, scenario._settle
        armed = [startup_fault is not None]

        class StartMark(dict):
            """Interrupt the exact start-return mark only after its mutation."""

            def __setitem__(self, key, value):
                """Retain the real mutated state before the one-shot host fault."""
                super().__setitem__(key, value)
                if key == "start" and value == "START_RETURNED" and armed[0]:
                    armed[0] = False
                    raise fault

        def final_settle(ordinal, row, released):
            """Hold the final target until the startup fault has been observed."""
            if ordinal == 18 and startup_fault is not None:
                release_final.wait(3)
            real_settle(ordinal, row, released)

        def register(worker, role="worker", deadline=None, owner=None, starter=None):
            """Inject only after real final-attempt registration has acquired custody."""
            entry = real_register(worker, role, deadline, owner, starter)
            if role != "settler" or owner is not state.records.get(18, {}).get("owner"):
                return entry
            assert set(state.settlements) == set(range(1, 18))
            if startup_fault == "register" and armed[0]:
                armed[0] = False
                raise fault
            if startup_fault == "mark":
                resources.workers[id(worker)] = StartMark(entry)
            if startup_fault == "launch":
                original_start = worker.start

                def launch():
                    """Launch the actual exact target, then interrupt its caller once."""
                    original_start()
                    armed[0] = False
                    raise fault

                worker.start = launch
            return entry

        monkeypatch.setattr(resources, "register_worker", register)
        monkeypatch.setattr(scenario, "_settle", final_settle)
        for module in (harness, support, evidence):
            monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
        error = LLMProviderTimeoutError("timeout")
        terminal = LLMRetryExhaustedError.__new__(LLMRetryExhaustedError)
        terminal.attempts, terminal.manual_cycle_count, terminal.retry_reason = 18, 0, "timeout"
        terminal.last_error = terminal.__cause__ = error
        body = dict(model="u5-exhaustion-model", messages=[{"role": "system", "content": ""},
                    {"role": "user", "content": "u5 exhaustion"}], stream=True, max_tokens=1,
                    temperature=0, top_p=1, frequency_penalty=0, n=1,
                    parallel_tool_calls=False,
                    stop=None, stream_options={"include_usage": True})
        capture = SimpleNamespace(state=lambda: dict(dropped_lifecycle_count=0))

        def no_request(number, timeout):
            """Advance only the local deterministic no-request observation clock."""
            assert number == 19
            clock[0] += 5
            return False

        capture.wait_for_request = no_request
        server = SimpleNamespace(lifecycle_capture=capture, request_body_capture=SimpleNamespace(
            state=lambda: dict(request_bodies=[dict(body=body) for _ in range(18)], dropped_request_body_count=0)))
        resources.retain("primary", SimpleNamespace(server=server))

        def chat(messages, **kwargs):
            """Admit external rows serially while real settlement proceeds and chat stays alive."""
            for ordinal in range(1, 19):
                row, facts = _u5_valid_candidate(mode)
                row.ordinal = ordinal
                row.invocation.owner = row.owner
                row.owner.create_thread = row.owner.fetch_thread = row.owner.cleanup_thread = None
                row.owner.close_finished_event = threading.Event()
                row.owner.close_finished_event.set()
                row.owner._close_state = SimpleNamespace(name="SUCCEEDED")
                row.owner.close_error = row.owner.disposal_error = None
                row.owner.primary_error = error
                row.events = facts["events"]
                row.release_returned = None
                if ordinal == 18:
                    for event, at in zip(row.events, (3.7, 3.8, 3.9)):
                        event["at"] = at
                    row.raw_event = row.events[0]
                    row["callback_boundaries"][-1].update(before=3.7 if mode == "headers" else 3.4, after=3.8 if mode == "headers" else 3.5)
                row.update(error=error, timeout=True, abandoned=True, invocation_exited=True,
                           entered_at=1000 * ordinal, error_at=1000 * ordinal + 1)
                def handler_exit(seconds):
                    """Expose final external close completion after terminal and release."""
                    if ordinal == 18:
                        clock[0] = 4.0
                    return True

                handle = SimpleNamespace(record=dict(connection_closed=True), release_delay=lambda: None,
                    wait_for_phase=lambda phase, seconds: True, wait_for_thread_exit=handler_exit)
                row["handle"] = handle
                with state.condition:
                    state.records[ordinal] = row
                    resources.handles[("primary", ordinal)] = dict(handle=handle, released=None, joined=None)
                    callbacks.extend(facts["callbacks"])
                    state.condition.notify_all()
                token = object()
                resources.note_spawn_scope(row.owner, "external", token, "ENTERED")
                resources.note_spawn_scope(row.owner, "external", token, "EXITED")
                if ordinal < 18:
                    state.wait_until(lambda: ordinal in state.settlements, state.deadline)
                    assert not state.no_more_settlers
            raise terminal

        model = SimpleNamespace(chat=chat, close=lambda: None, max_tokens=1, temperature=0, top_p=1, frequency_penalty=0)
        resources.retain("model", model)
        state.ledger = SimpleNamespace(snapshot=lambda: tuple(callbacks), validate=lambda entries: None)

        def control(deadline):
            """External held control observes real completed predecessors and terminal publication."""
            assert set(state.settlements) == set(range(1, 18))
            assert state.terminal_error is terminal
            trace.append("held")
            return dict(start_before=3.6, start_returned=3.6, at=3.6)

        def close_primary(deadline):
            """Observe actual completion eighteen before closing the external primary."""
            assert state.settlements[18]["success"] is True
            trace.append("primary close")
            return dict(at=clock[0])

        def finish(deadline):
            """Record the externally held control's final settlement boundary."""
            trace.append("control finish")
            return dict(released=3.6)

        def close_normal(deadline):
            """Require exact real orchestration and settler joins before external cleanup."""
            resources.global_quiescent(deadline)
            assert state.coordinator_done and state.settlement_supervisor_done
            assert all(entry["joined"] is not None for entry in resources.workers.values())
            trace.append("normal close")
            return dict(restoration_complete=True)

        monkeypatch.setattr(resources, "start_control", control)
        monkeypatch.setattr(resources, "close_primary", close_primary)
        monkeypatch.setattr(resources, "assert_control_held", lambda: trace.append("survival"))
        monkeypatch.setattr(resources, "finish_control", finish)
        monkeypatch.setattr(resources, "close_normal", close_normal)
        try:
            if startup_fault is not None:
                with pytest.raises(KeyboardInterrupt) as caught:
                    scenario.run()
                assert caught.value is fault and not armed[0]
                release_final.set()
                resources.arm_recovery()
                for entry in tuple(resources.workers.values()):
                    resources.join_worker(entry["thread"], state.deadline, recovery=True)
                final_entries = [entry for entry in resources.workers.values()
                                 if entry["role"] == "settler" and entry["owner"] is state.records[18].owner]
                assert len(final_entries) == 1
                entry = final_entries[0]
                assert entry["joined"]["thread"] is entry["thread"]
                assert entry["joined"]["never_started"] is (startup_fault == "register")
                assert state.no_more_settlers and state.coordinator_done
                assert state.records[18].completed_bundle is None
                assert set(state.settlements) == set(range(1, 18))
                assert trace == ["held"] and not resources.restoration_complete
                gate = resources.recovery_gate
                with pytest.raises(KeyboardInterrupt) as recovered:
                    resources.recover(state.deadline)
                assert recovered.value is fault and resources.recovery_gate is gate
                assert resources.restoration_complete
                continue
            result = scenario.run()
            assert len(result["rows"]) == len(result["settlements"]) == 18
            assert trace == ["held", "primary close", "survival", "control finish", "normal close"]
            for row in scenario.records.values():
                assert row.completed_bundle is state.settlements[row.ordinal]
                assert row.completed_bundle["settler_join"]["thread"] is row["settlement_worker"]
                assert not row["settlement_worker"].is_alive()
        finally:
            release_final.set()
            state.seal_settlers()
            for entry in resources.workers.values():
                if entry["thread"].ident is not None:
                    entry["thread"].join(3)
                    assert not entry["thread"].is_alive()


def test_u5_actual_coordinator_startup_interruption_seals_retained_worker(monkeypatch):
    """A coordinator startup fault keeps registered custody and seals future admission."""
    from tests.bdd.llm_first_byte_exhaustion_harness import ExhaustionScenario

    scenario = ExhaustionScenario("headers")
    row, _ = _u5_valid_candidate("headers")
    scenario.state.records[1] = row
    fault = KeyboardInterrupt("settler startup")

    def prerequisites(ordinal, deadline):
        """Provide only the externally established prerequisites for the first attempt."""
        assert ordinal == 1
        return row

    def release(current):
        """Represent the already observed external release without publishing completion."""
        return current.release_returned

    def start(thread):
        """Interrupt after actual coordinator registration, before worker launch."""
        assert scenario.resources.workers[id(thread)]["thread"] is thread
        raise fault

    monkeypatch.setattr(scenario, "_wait_prerequisites", prerequisites)
    monkeypatch.setattr(scenario, "_release_once", release)
    monkeypatch.setattr(scenario.resources, "start_worker", start)
    scenario._coordinate()
    assert scenario.state.failure_to_raise() is fault
    assert scenario.state.no_more_settlers and scenario.state.coordinator_done
    assert row.completed_bundle is None
    assert scenario.resources.workers[id(row["settlement_worker"])]["joined"] is None
