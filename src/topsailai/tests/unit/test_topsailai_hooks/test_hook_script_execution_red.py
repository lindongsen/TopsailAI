"""RED contracts for non-empty hook-script execution orchestration."""
from __future__ import annotations
import asyncio, dataclasses, math, threading
from dataclasses import replace
from pathlib import Path
import pytest
from topsailai.hooks import (Binding, HookContext, HookEvent, HookPointBindingPlan, HookScriptDiscoveryResult, HookScriptEntry, HookScriptSettlement, HookStatus, build_hook_point_binding_plan_from_discovery)
from topsailai.tests.unit.test_topsailai_hooks.hook_script_execution_helpers import (CallbackClock, Clock, FakeDebt, FakeHookScriptRunner, LOCAL_FIELDS, LocalHookContext, LocalHookScriptEntryResult, LocalHookScriptExecutionOptions, LocalHookScriptExecutionPolicy)
def _mapping(record: object) -> dict:
    return {item.name: getattr(record, item.name) for item in dataclasses.fields(record)}
def _preflight() -> None:
    for record_type, names in LOCAL_FIELDS.items():
        assert record_type.__dataclass_params__.frozen
        assert tuple(item.name for item in dataclasses.fields(record_type)) == names
    clock = Clock(3.0)
    local = LocalHookScriptEntryResult(0, "a", HookStatus.SUCCESS, True, 0)
    runner = FakeHookScriptRunner(lambda value: value, clock)
    entry = HookScriptEntry(Path("/tmp/a"), "a")
    event = _event()
    context = HookContext(event, "delivery-red", "hook_script", 1, 10000)
    options = LocalHookScriptExecutionOptions()
    policy = LocalHookScriptExecutionPolicy()
    result = runner.execute_entry(
        entry_index=0, entry=entry, context=context, options=options,
        policy=policy, execution_deadline=4.0, cleanup_deadline=5.0,
        output_remaining_bytes=6, cancellation=threading.Event(),
    )
    assert result == local and runner.current_result(0) == runner.snapshots[0]
    assert runner.calls[0]["execution_deadline"] == 4.0
    debt = FakeDebt("preflight-debt")
    def interrupted(call, fake):
        fake.snapshots[0] = local
        fake.debts = (debt,)
        raise ValueError("preflight")
    runner.actions = (interrupted,)
    with pytest.raises(ValueError, match="preflight"):
        runner.execute_entry(entry_index=0, entry=entry, context=context, options=options,
            policy=policy, execution_deadline=4.0, cleanup_deadline=5.0,
            output_remaining_bytes=6, cancellation=threading.Event())
    assert runner.current_result(0) is local and runner.cleanup_debts() == (debt,)
    assert runner.retry_cleanup("preflight-debt") and runner.cleanup_debts() == ()
    runner.actions = (lambda call, fake: object(),)
    malformed = runner.execute_entry(entry_index=0, entry=entry, context=context,
        options=options, policy=policy, execution_deadline=4.0,
        cleanup_deadline=5.0, output_remaining_bytes=6, cancellation=threading.Event())
    assert type(malformed) is object and runner.current_result(0) != malformed
    cancelled = threading.Event(); captured = replace(local, stdout=b"out", stderr=b"err")
    runner.actions = (lambda call, fake: (cancelled.set(), captured)[1],)
    assert runner.execute_entry(entry_index=0, entry=entry, context=context, options=options,
        policy=policy, execution_deadline=4.0, cleanup_deadline=5.0,
        output_remaining_bytes=6, cancellation=cancelled) is captured
    assert cancelled.is_set() and (captured.stdout, captured.stderr) == (b"out", b"err")
    runner.calls.clear(); runner.current_calls.clear(); runner.snapshots.clear(); runner.recovery_events.clear(); runner.retry_calls.clear()
def _api():
    _preflight()
    import topsailai.hooks as hooks
    api = getattr(hooks, "execute_configured_hook_script", None)
    if not callable(api): pytest.fail("nonempty hook_script execution API missing")
    names = ("HookScriptExecutionOptions", "HookScriptExecutionPolicy",
             "HookScriptRunner", "HookScriptEntryResult")
    types = tuple(getattr(hooks, name, None) for name in names)
    if any(value is None for value in types): pytest.fail("nonempty hook_script execution types missing")
    for public, local in zip((types[0], types[1], types[3]),
                             (LocalHookScriptExecutionOptions, LocalHookScriptExecutionPolicy, LocalHookScriptEntryResult)):
        assert dataclasses.is_dataclass(public); public_fields, local_fields = dataclasses.fields(public), dataclasses.fields(local)
        assert tuple(item.name for item in public_fields) == tuple(item.name for item in local_fields)
        assert all((left.default, left.default_factory) == (right.default, right.default_factory)
                   for left, right in zip(public_fields, local_fields))
    return (api, *types)
def _event(name: str = "conversation.started", payload=None) -> HookEvent:
    return HookEvent(
        "event-red", name, 1, "owner-red", "scope-red", "operation-red", None,
        1, "2026-10-01T00:00:00+00:00", "test", "hook-script-red",
        {"message": "literal"} if payload is None else payload,
    )
def _baseline(names: tuple[str, ...] = ("a", "b", "c"), clock=None) -> dict:
    root = Path("/TopsailAI/src/topsailai/.tmp/hook-script-red-input")
    entries = tuple(HookScriptEntry(root / name, name) for name in names); return {
        "hook_point": "conversation.started",
        "module_bindings": (Binding(
            "module:alpha", "conversation.started", 1, "fixtures.alpha:main"
        ),),
        "bindings_per_event": 2,
        "discovery_result": HookScriptDiscoveryResult(True, entries),
        "context": LocalHookContext(
            _event(), "delivery-red", "hook_script", 1, 10000
        ),
        "options": LocalHookScriptExecutionOptions(
            ("--literal",), root, (("SAFE", "1"),)
        ),
        "policy": LocalHookScriptExecutionPolicy(hook_timeout_ms=5000),
        "dispatch_deadline": 10.0,
        "clock": clock or Clock(),
        "cancellation": threading.Event(),
    }
def _primitive(value):
    if isinstance(value, dict) or hasattr(value, "items"):
        return tuple(sorted((key, _primitive(item)) for key, item in value.items()))
    if isinstance(value, (tuple, list)) or (
        not isinstance(value, (str, bytes, bytearray))
        and hasattr(value, "__iter__")
    ):
        return tuple(_primitive(item) for item in value)
    if isinstance(value, float) and math.isnan(value): return ("nan",)
    if dataclasses.is_dataclass(value):
        return tuple((item.name, _primitive(getattr(value, item.name))) for item in dataclasses.fields(value))
    if isinstance(value, Path): return ("path", str(value))
    return value
def _projection(case: dict):
    keys = ("hook_point", "module_bindings", "bindings_per_event",
            "discovery_result", "context", "options", "policy",
            "dispatch_deadline")
    return tuple((key, _primitive(case[key])) for key in keys)
def _prepare(case: dict, resolved):
    _, options_type, policy_type, _, result_type = resolved
    actual = dict(case)
    local_context = case["context"]
    actual["context"] = HookContext(**_mapping(local_context)) if type(local_context) is LocalHookContext else local_context
    actual["options"] = options_type(**_mapping(case["options"])) if type(case["options"]) is LocalHookScriptExecutionOptions else case["options"]
    actual["policy"] = policy_type(**_mapping(case["policy"])) if type(case["policy"]) is LocalHookScriptExecutionPolicy else case["policy"]
    runner = FakeHookScriptRunner(lambda value: result_type(**_mapping(value)), case["clock"])
    actual["runner"] = runner; return actual, runner
def _invoke(resolved, case: dict, runner: FakeHookScriptRunner):
    api = resolved[0]
    return api(
        hook_point=case["hook_point"],
        module_bindings=case["module_bindings"],
        bindings_per_event=case["bindings_per_event"],
        discovery_result=case["discovery_result"],
        context=case["context"], options=case["options"], policy=case["policy"],
        runner=runner, dispatch_deadline=case["dispatch_deadline"],
        cancellation=case["cancellation"], clock=case["clock"],
    )
def _assert_settlement(value, status, token, length, started):
    assert type(value) is HookScriptSettlement
    assert (value.status, value.error_category, value.started, len(value.entry_results)) == (status, token, started, length)
def _assert_skipped(value, status, index, basename, token):
    assert type(value.status) is HookStatus and value.status is status
    assert (value.entry_index, value.basename, value.error_category) == (index, basename, token)
    assert value.started is False and value.exit_code is None and value.duration_ms == 0
    assert value.stdout == value.stderr == b"" and value.stdout_dropped == value.stderr_dropped == 0
    assert value.cleanup_confirmed is True and value.cleanup_debt is None
def _run(case: dict, actions=()):
    resolved = _api()
    actual, runner = _prepare(case, resolved)
    before = _projection(actual)
    refs = {key: actual[key] for key in ("context", "options", "policy", "discovery_result", "cancellation", "clock")}
    runner.actions = actions
    result = _invoke(resolved, actual, runner)
    assert _projection(actual) == before
    assert all(actual[key] is value for key, value in refs.items())
    for call in runner.calls:
        assert (call["context"] is actual["context"] and call["options"] is actual["options"]
            and call["policy"] is actual["policy"] and call["cancellation"] is actual["cancellation"])
    return result, runner, actual, resolved
def _local(call, **changes):
    base = LocalHookScriptEntryResult(
        call["entry_index"], call["entry"].basename, HookStatus.SUCCESS, True, 0
    )
    return replace(base, **changes)
def test_b01_planning_and_discovery_rejection_precedence(monkeypatch):
    cases = []
    for discovery, binding, limit in (
        (HookScriptDiscoveryResult(True, _baseline()["discovery_result"].entries), Binding("bad", "conversation.started", 1, "x:y"), 2),
        (HookScriptDiscoveryResult(False, errors=("discovery",)), _baseline()["module_bindings"][0], 2),
        (object(), _baseline()["module_bindings"][0], 2),
        (HookScriptDiscoveryResult(False, errors=("discovery",)), Binding("bad", "wrong", 1, "x:y"), 0),
        (HookScriptDiscoveryResult(False, errors=("discovery",)), _baseline()["module_bindings"][0], 2),
        (HookScriptDiscoveryResult(True, ()), Binding("bad", "wrong", 1, "x:y"), 0),
    ):
        case = _baseline(); case.update(discovery_result=discovery, module_bindings=(binding,), bindings_per_event=limit)
        cases.append(case)
    rejected_invalid = _baseline()
    rejected_invalid.update(discovery_result=HookScriptDiscoveryResult(False, errors=("discovery",)), options=object())
    cases.append(rejected_invalid)
    resolved = _api()
    import topsailai.hooks.hook_script as module
    original = module.build_hook_point_binding_plan_from_discovery
    calls = []
    def bridge(**kwargs):
        plan = original(**kwargs); calls.append((kwargs, plan)); return plan
    monkeypatch.setattr(module, "build_hook_point_binding_plan_from_discovery", bridge)
    for case in cases:
        actual, runner = _prepare(case, resolved); before = _projection(actual)
        previous_calls = len(calls)
        result = _invoke(resolved, actual, runner)
        assert len(calls) == previous_calls + 1
        call, plan = calls[-1]
        expected_call = {"hook_point": case["hook_point"], "module_bindings": case["module_bindings"],
            "bindings_per_event": case["bindings_per_event"], "hook_script_configured": True,
            "discovery_result": case["discovery_result"]}
        assert call == expected_call
        assert plan.errors == build_hook_point_binding_plan_from_discovery(**expected_call).errors
        _assert_settlement(result, "error", "hook_script_plan_rejected", 0, False)
        assert runner.calls == runner.current_calls == runner.retry_calls == []
        assert _projection(actual) == before
def test_b02_accepted_empty_rejects_without_fallback(monkeypatch):
    case = _baseline(())
    import topsailai.hooks.hook_script as module
    counts = {"configured": 0, "legacy": 0, "bridge": 0}
    original_bridge = module.build_hook_point_binding_plan_from_discovery
    terminals = []
    def bridge(**kwargs):
        counts["bridge"] += 1
        plan = original_bridge(**kwargs); terminals.append(plan); return plan
    monkeypatch.setattr(module, "build_hook_point_binding_plan_from_discovery", bridge)
    def forbidden(name):
        def call(*args, **kwargs):
            counts[name] += 1
            return HookScriptSettlement("success")
        return call
    monkeypatch.setattr(module, "settle_configured_empty_hook_script", forbidden("configured"))
    monkeypatch.setattr(module, "settle_unconfigured_hook_script", forbidden("legacy"))
    result, runner, _, _ = _run(case)
    _assert_settlement(result, "error", "hook_script_empty_entries", 0, False)
    assert counts == {"configured": 0, "legacy": 0, "bridge": 1}
    assert terminals[0].accepted is True and terminals[0].bindings[-1].configured is True
    assert terminals[0].bindings[-1].entries == () and runner.calls == runner.current_calls == runner.retry_calls == []
def test_b03_invalid_inputs_are_independent_and_pure():
    root = _baseline()["options"].cwd
    option_mutations = [
        object(), LocalHookScriptExecutionOptions(argv=[]),
        LocalHookScriptExecutionOptions((1,)), LocalHookScriptExecutionOptions(("x\0",)),
        LocalHookScriptExecutionOptions(("\ud800",)),
        LocalHookScriptExecutionOptions(cwd=Path("relative")),
        LocalHookScriptExecutionOptions(environment=[]),
        LocalHookScriptExecutionOptions(environment=(("A",),)),
        LocalHookScriptExecutionOptions(environment=(("A", "1"), ("A", "2"))),
        LocalHookScriptExecutionOptions(environment=(("", "1"),)),
        LocalHookScriptExecutionOptions(environment=(("A=B", "1"),)),
        LocalHookScriptExecutionOptions(environment=(("A\0", "1"),)),
        LocalHookScriptExecutionOptions(environment=(("A", "x\0"),)),
        LocalHookScriptExecutionOptions(environment=(("\ud800", "1"),)),
        LocalHookScriptExecutionOptions(environment=(("A", "\ud800"),)),
    ]
    policy_mutations = [object()]
    duration_names = (
        "entry_timeout_ms", "hook_timeout_ms", "cleanup_timeout_ms", "terminate_grace_ms"
    )
    for name in duration_names:
        for value in (True, 0, -1, 1.5, 600_001):
            policy_mutations.append(replace(_baseline()["policy"], **{name: value}))
    byte_names = (
        "stdin_limit_bytes", "stdout_limit_bytes", "stderr_limit_bytes",
        "output_total_limit_bytes", "argument_environment_limit_bytes", "result_limit_bytes",
    )
    for name in byte_names:
        for value in (True, 0, -1, 1.5, 1_048_577):
            policy_mutations.append(replace(_baseline()["policy"], **{name: value}))
    for value in (True, 0, -1, 1.5, 33):
        policy_mutations.append(replace(_baseline()["policy"], max_entries=value))
    policy_mutations.append(
        replace(_baseline()["policy"], cleanup_timeout_ms=99, terminate_grace_ms=100)
    )
    cases = []
    for value in option_mutations:
        case = _baseline(); case["options"] = value; cases.append(case)
    for value in policy_mutations:
        case = _baseline(); case["policy"] = value; cases.append(case)
    matching_event = type("MatchingEvent", (), {"name": "conversation.started"})()
    for value in (
        object(),
        LocalHookContext(_event(), "d", "wrong", 1, 1),
        LocalHookContext(None, "d", "hook_script", 1, 1),
        LocalHookContext(matching_event, "d", "hook_script", 1, 1),
    ):
        case = _baseline()
        case["context"] = value
        cases.append(case)
    for value in (float("nan"), float("inf"), "10"):
        case = _baseline(); case["dispatch_deadline"] = value; cases.append(case)
    bad_entries = (
        (HookScriptEntry(Path("relative"), "a"),),
        (HookScriptEntry(root / "a", ""),),
        (HookScriptEntry(root / "a", "a/b"),),
        (HookScriptEntry(root / "a", "a"), HookScriptEntry(root / "a", "b")),
        (HookScriptEntry(root / "a", "a"), HookScriptEntry(root / "b", "a")),
    )
    for entries in bad_entries:
        case = _baseline(); case["discovery_result"] = HookScriptDiscoveryResult(True, entries); cases.append(case)
    cap = _baseline(("a", "b")); cap["policy"] = replace(cap["policy"], max_entries=1); cases.append(cap)
    argv = _baseline(); argv["options"] = replace(argv["options"], argv=("é",), environment=()); argv["policy"] = replace(argv["policy"], argument_environment_limit_bytes=1); cases.append(argv)
    env = _baseline(); env["options"] = replace(env["options"], argv=(), environment=(("A", "é"),)); env["policy"] = replace(env["policy"], argument_environment_limit_bytes=2); cases.append(env)
    payload = _baseline(); payload["context"] = replace(payload["context"], event=_event(payload={"message": "é" * 20})); payload["policy"] = replace(payload["policy"], stdin_limit_bytes=1); cases.append(payload)
    for case in cases:
        result, runner, _, _ = _run(case); plan = build_hook_point_binding_plan_from_discovery(
            hook_point=case["hook_point"], module_bindings=case["module_bindings"],
            bindings_per_event=case["bindings_per_event"], hook_script_configured=True,
            discovery_result=case["discovery_result"],
        )
        token = "hook_script_plan_rejected" if not plan.accepted else "hook_script_invalid_execution_input"
        _assert_settlement(result, "error", token, 0, False)
        assert runner.calls == runner.current_calls == runner.retry_calls == []
def test_b04_order_and_single_execution(monkeypatch):
    case = _baseline(); captured = []
    import topsailai.hooks.hook_script as module
    original = module.build_hook_point_binding_plan_from_discovery
    def bridge(**kwargs):
        plan = original(**kwargs); captured.append(plan); return plan
    monkeypatch.setattr(module, "build_hook_point_binding_plan_from_discovery", bridge)
    result, runner, _, resolved = _run(case)
    _assert_settlement(result, "success", None, 3, True)
    assert [call["entry_index"] for call in runner.calls] == [0, 1, 2]
    assert len(captured) == 1
    assert all(call["entry"] is captured[0].bindings[-1].entries[index] for index, call in enumerate(runner.calls))
    assert runner.current_calls == runner.retry_calls == []
    for index, item in enumerate(result.entry_results):
        assert type(item) is resolved[-1]
        assert (item.entry_index, item.basename, item.status, item.started, item.exit_code,
            item.duration_ms, item.error_category, item.stdout, item.stderr,
            item.stdout_dropped, item.stderr_dropped, item.cleanup_confirmed, item.cleanup_debt) == (
            index, "abc"[index], HookStatus.SUCCESS, True, 0, 0, None, b"", b"", 0, 0, True, None)
def test_b05_nonzero_and_signal_are_retained_and_continue():
    def execute(first_success=False):
        case = _baseline(("a-nonzero", "b-signal", "c-good"))
        def action(call, fake):
            facts = [(HookStatus.ERROR, "hook_script_nonzero_exit", 7), (HookStatus.WORKER_LOST, "hook_script_signal_exit", -15), (HookStatus.SUCCESS, None, 0)]
            if first_success: facts[0] = (HookStatus.SUCCESS, None, 0)
            status, token, code = facts[call["entry_index"]]
            return fake.result_factory(_local(call, status=status, error_category=token, exit_code=code))
        result, runner, _, _ = _run(case, (action, action, action))
        assert [call["entry_index"] for call in runner.calls] == [0, 1, 2]
        assert [(item.status, item.error_category, item.exit_code) for item in result.entry_results] == ([
            (HookStatus.SUCCESS, None, 0), (HookStatus.WORKER_LOST, "hook_script_signal_exit", -15), (HookStatus.SUCCESS, None, 0)
        ] if first_success else [
            (HookStatus.ERROR, "hook_script_nonzero_exit", 7), (HookStatus.WORKER_LOST, "hook_script_signal_exit", -15), (HookStatus.SUCCESS, None, 0)
        ])
        assert all((item.entry_index, item.basename, item.started, item.cleanup_confirmed, item.cleanup_debt) ==
            (index, ("a-nonzero", "b-signal", "c-good")[index], True, True, None)
            for index, item in enumerate(result.entry_results))
        return result
    first = execute(); _assert_settlement(first, "error", "hook_script_nonzero_exit", 3, True)
    second = execute(True); _assert_settlement(second, "worker_lost", "hook_script_signal_exit", 3, True)
def test_b06_started_is_observed_start_or():
    scenarios = (
        (("start", "start", "start"), False, "worker_lost", "hook_script_start_failed"),
        (("start", "success"), True, "worker_lost", "hook_script_start_failed"),
        (("nonzero",), True, "error", "hook_script_nonzero_exit"),
    )
    for facts, expected, group_status, group_token in scenarios:
        case = _baseline(tuple(chr(97 + i) for i in range(len(facts))))
        def action(call, fake):
            fact = facts[call["entry_index"]]
            if fact == "success": return fake.result_factory(_local(call))
            started = fact == "nonzero"
            return fake.result_factory(_local(call, status=HookStatus.ERROR if started else HookStatus.WORKER_LOST,
                started=started, exit_code=7 if started else None,
                error_category="hook_script_nonzero_exit" if started else "hook_script_start_failed"))
        result, runner, _, _ = _run(case, tuple(action for _ in facts))
        _assert_settlement(result, group_status, group_token, len(facts), expected)
        assert len(result.entry_results) == len(facts) == len(runner.calls)
        assert [item.started for item in result.entry_results] == [fact != "start" for fact in facts]
        assert [item.exit_code for item in result.entry_results] == [7 if fact == "nonzero" else (0 if fact == "success" else None) for fact in facts]
def test_b07_exception_snapshot_cleanup_and_current_failure(caplog):
    sentinel = "secret-runner-sentinel"
    for started, cleanup, continues in ((False, True, True), (True, True, True), (True, False, False)):
        case = _baseline(("a", "b")); debt = FakeDebt("d7")
        def broken(call, fake):
            snapshot = fake.result_factory(_local(call, status=HookStatus.ERROR, started=started, exit_code=7 if started else None, error_category="ignored", stdout=b"fact", cleanup_confirmed=cleanup, cleanup_debt=None if cleanup else "d7"))
            fake.snapshots[0] = snapshot
            if not cleanup: fake.debts = (debt,)
            raise ValueError(sentinel)
        result, runner, _, _ = _run(case, (broken,))
        assert len(runner.calls) == (2 if continues else 1)
        _assert_settlement(result, "error", "hook_script_execution_error" if cleanup else "hook_script_cleanup_pending", 2, started or continues)
        first = result.entry_results[0]
        expected = "hook_script_execution_error" if cleanup else "hook_script_cleanup_pending"
        assert first.status is HookStatus.ERROR and first.error_category == expected
        assert first.started is started and first.stdout == b"fact"
        assert sentinel not in repr(result) and runner.current_calls == [0] and runner.retry_calls == []
        assert (first.exit_code, first.cleanup_confirmed, first.cleanup_debt) == (7 if started else None, cleanup, None if cleanup else "d7")
        if continues: assert result.entry_results[1].status is HookStatus.SUCCESS
        if not cleanup: _assert_skipped(result.entry_results[1], HookStatus.SKIPPED_DEPENDENCY, 1, "b", expected)
    for fault in (RuntimeError(sentinel), object()):
        case = _baseline(("a", "b")); resolved = _api(); actual, runner = _prepare(case, resolved)
        debt = FakeDebt("recover-7"); runner.debts = (debt,); runner.snapshot_faults[0] = fault
        def raises(call, fake): raise ValueError(sentinel)
        runner.actions = (raises,)
        with pytest.raises(RuntimeError, match="^hook_script_runner_error$") as caught:
            _invoke(resolved, actual, runner)
        assert sentinel not in str(caught.value) and sentinel not in caplog.text
        assert len(runner.calls) == 1 and runner.current_calls == [0] and runner.retry_calls == []
        assert runner.cleanup_debts()[0] is debt and runner.retry_cleanup("recover-7")
def test_b08_deadlines_are_minimums_and_cleanup_is_shared():
    rows = ((12, 5000, 5000, 12, 12, 12, 14), (20, 2000, 5000, 12, 12, 12, 14), (20, 5000, 500, 15, 10.5, 10.75, 17))
    for dispatch, hook_ms, entry_ms, group_deadline, first, second, cleanup in rows:
        clock = Clock(10); case = _baseline(("a", "b"), clock)
        case["dispatch_deadline"] = dispatch
        case["policy"] = replace(case["policy"], hook_timeout_ms=hook_ms, entry_timeout_ms=entry_ms, cleanup_timeout_ms=2000)
        def action(call, fake):
            if call["entry_index"] == 0: fake.clock.value = 10.25
            return fake.result_factory(_local(call))
        _, runner, actual, _ = _run(case, (action, action))
        assert [call["observed_start"] for call in runner.calls] == [10, 10.25]
        assert [call["execution_deadline"] for call in runner.calls] == pytest.approx([first, second], abs=1e-12, rel=0)
        assert [call["cleanup_deadline"] for call in runner.calls] == pytest.approx([cleanup, cleanup], abs=1e-12, rel=0)
        assert all(call["policy"] is actual["policy"] for call in runner.calls)
def test_b09_deadline_before_and_between_entries_skips_remaining():
    for now in (10.0, 10.125):
        case = _baseline(); case["clock"].value = now
        result, runner, _, _ = _run(case)
        _assert_settlement(result, "skipped_deadline", "hook_script_deadline", 3, False)
        assert runner.calls == []
        for index, item in enumerate(result.entry_results): _assert_skipped(item, HookStatus.SKIPPED_DEADLINE, index, "abc"[index], "hook_script_deadline")
    case = _baseline()
    def first(call, fake):
        fake.clock.value = 5.0
        return fake.result_factory(_local(call))
    result, runner, _, _ = _run(case, (first,))
    assert len(result.entry_results) == 3 and [call["entry_index"] for call in runner.calls] == [0]
    assert (result.status, result.error_category, result.started) == ("timeout", "hook_script_timeout", True)
    first_result = result.entry_results[0]
    assert (first_result.status, first_result.error_category, first_result.exit_code,
        first_result.stdout, first_result.stderr, first_result.cleanup_confirmed) == (
        HookStatus.TIMEOUT, "hook_script_timeout", 0, b"", b"", True)
    for index in (1, 2): _assert_skipped(result.entry_results[index], HookStatus.SKIPPED_DEADLINE, index, "abc"[index], "hook_script_deadline")
def test_b10_late_success_is_bound_to_captured_deadline():
    for delta in (0.0, 0.125):
        case = _baseline(("late", "next"))
        def late(call, fake):
            assert call["execution_deadline"] == pytest.approx(1.0)
            fake.clock.value = call["execution_deadline"] + delta
            assert fake.clock.value < 5
            return fake.result_factory(_local(call, stdout=b"out", stderr=b"err"))
        result, runner, _, _ = _run(case, (late,))
        assert len(runner.calls) == 2
        first, second = result.entry_results
        assert (first.entry_index, first.basename, first.status, first.started,
            first.error_category, first.exit_code, first.stdout, first.stderr,
            first.cleanup_confirmed) == (0, "late", HookStatus.TIMEOUT, True,
            "hook_script_timeout", 0, b"out", b"err", True)
        assert second.status is HookStatus.SUCCESS and (second.entry_index, second.basename, second.started, second.exit_code) == (1, "next", True, 0)
        _assert_settlement(result, "timeout", "hook_script_timeout", 2, True)
    case = _baseline(("a", "b"))
    def timeout(call, fake): return fake.result_factory(_local(call, status=HookStatus.TIMEOUT, error_category="hook_script_timeout"))
    result, runner, _, _ = _run(case, (timeout,)); _assert_settlement(result, "timeout", "hook_script_timeout", 2, True); assert len(runner.calls) == 2 and result.entry_results[1].status is HookStatus.SUCCESS
    case = _baseline(("a", "b")); debt = FakeDebt("late-debt")
    def pending(call, fake):
        fake.clock.value = call["execution_deadline"]
        fake.debts = (debt,)
        return fake.result_factory(_local(call, stdout=b"fact", cleanup_confirmed=False, cleanup_debt="late-debt"))
    result, runner, _, _ = _run(case, (pending,))
    _assert_settlement(result, "error", "hook_script_cleanup_pending", 2, True)
    first = result.entry_results[0]
    assert (first.status, first.error_category, first.started, first.exit_code,
        first.stdout, first.cleanup_confirmed, first.cleanup_debt) == (
        HookStatus.ERROR, "hook_script_cleanup_pending", True, 0, b"fact", False, "late-debt")
    assert len(runner.calls) == 1 and len(result.entry_results) == 2
    assert runner.cleanup_debts()[0] is debt and runner.retry_calls == []
    _assert_skipped(result.entry_results[1], HookStatus.SKIPPED_DEPENDENCY, 1, "b", "hook_script_cleanup_pending")
def test_b11_cleanup_debt_stops_without_retry():
    case = _baseline(); debt = FakeDebt("debt-11")
    def pending(call, fake):
        fake.debts = (debt,)
        return fake.result_factory(_local(call, cleanup_confirmed=False, cleanup_debt="debt-11"))
    result, runner, _, _ = _run(case, (pending,))
    _assert_settlement(result, "error", "hook_script_cleanup_pending", 3, True)
    first = result.entry_results[0]
    assert (first.status, first.error_category, first.started, first.exit_code, first.cleanup_confirmed, first.cleanup_debt) == (HookStatus.ERROR, "hook_script_cleanup_pending", True, 0, False, "debt-11")
    assert len(runner.calls) == 1 and runner.retry_calls == [] and runner.cleanup_debts()[0] is debt
    for index in (1, 2): _assert_skipped(result.entry_results[index], HookStatus.SKIPPED_DEPENDENCY, index, "abc"[index], "hook_script_cleanup_pending")
    assert runner.retry_cleanup("unknown") is False and runner.cleanup_debts() == (debt,)
    assert runner.retry_cleanup("debt-11") is True and runner.cleanup_debts() == ()
def test_b12_cancellation_before_during_and_between():
    case = _baseline(("a", "b")); case["cancellation"].set(); resolved = _api(); actual, runner = _prepare(case, resolved)
    with pytest.raises(asyncio.CancelledError): _invoke(resolved, actual, runner)
    assert runner.calls == []
    case = _baseline(("a", "b")); original = asyncio.CancelledError("during"); debt = FakeDebt("cancel-debt")
    def during(call, fake):
        assert not call["cancellation"].is_set() and fake.active
        fake.debts = (debt,); call["cancellation"].set()
        fake.snapshots[0] = fake.result_factory(_local(call, cleanup_confirmed=False, cleanup_debt="cancel-debt"))
        raise original
    resolved = _api(); actual, runner = _prepare(case, resolved); runner.actions = (during,)
    with pytest.raises(asyncio.CancelledError) as caught: _invoke(resolved, actual, runner)
    assert caught.value is original and len(runner.calls) == 1 and runner.cleanup_debts()[0] is debt
    assert runner.retry_calls == [] and runner.calls[0]["cleanup_deadline"] == pytest.approx(6.0, rel=0, abs=1e-12)
    assert runner.current_result(0).cleanup_debt == "cancel-debt"
    cancel = threading.Event(); clock = CallbackClock(); case = _baseline(("a", "b"), clock); case["cancellation"] = cancel
    def between(call, fake):
        result = fake.result_factory(_local(call)); fake.snapshots[0] = result
        fake.recovery_events.append(("action-return", 0))
        def callback():
            assert not fake.active; cancel.set(); fake.recovery_events.append(("clock-cancel", 0))
        clock.callback = callback; clock.armed = True
        return result
    resolved = _api(); actual, runner = _prepare(case, resolved); runner.actions = (between,)
    with pytest.raises(asyncio.CancelledError): _invoke(resolved, actual, runner)
    assert clock.fired and [call["entry_index"] for call in runner.calls] == [0]
    assert runner.retry_calls == [] and runner.calls[0]["cleanup_deadline"] == pytest.approx(6.0, rel=0, abs=1e-12)
    assert runner.current_result(0).started is True
    action_pos = runner.recovery_events.index(("action-return", 0))
    return_pos = runner.recovery_events.index(("return", 0))
    cancel_pos = runner.recovery_events.index(("clock-cancel", 0))
    assert action_pos < return_pos < cancel_pos and len(runner.calls) == 1
def test_b13_host_interruptions_preserve_identity():
    for original in (KeyboardInterrupt("host"), SystemExit(7), asyncio.CancelledError("host")):
        cause = RuntimeError("existing-cause"); context_error = ValueError("existing-context")
        original.__cause__ = cause; original.__context__ = context_error
        case = _baseline(("a", "b")); debt = FakeDebt("interrupt-debt")
        resolved = _api(); actual, runner = _prepare(case, resolved); runner.debts = (debt,)
        def interrupt(call, fake):
            fake.snapshots[0] = fake.result_factory(_local(call, cleanup_confirmed=False, cleanup_debt="interrupt-debt"))
            raise original
        runner.actions = (interrupt,)
        with pytest.raises(type(original)) as caught: _invoke(resolved, actual, runner)
        assert caught.value is original and caught.value.__cause__ is cause and caught.value.__context__ is context_error
        assert len(runner.calls) == 1 and runner.retry_calls == [] and runner.cleanup_debts()[0] is debt
def _capture(stdout: bytes, stderr: bytes, stdout_cap: int, stderr_cap: int, total: int):
    kept_out = stdout[:min(stdout_cap, total)]; remaining = total - len(kept_out)
    kept_err = stderr[:min(stderr_cap, remaining)]
    return kept_out, kept_err, len(stdout) - len(kept_out), len(stderr) - len(kept_err)
def test_b14_stream_caps_and_aggregate_remaining(capsys, caplog):
    cases = ((b"\xffABC", b"", 3, 4, 20, (b"\xffAB", b"", 1, 0)), (b"", b"\xfeXY", 4, 2, 20, (b"", b"\xfeX", 0, 1)))
    for raw_out, raw_err, out_cap, err_cap, total, expected in cases:
        assert _capture(raw_out, raw_err, out_cap, err_cap, total) == expected
        case = _baseline(("a", "b")); case["policy"] = replace(case["policy"], stdout_limit_bytes=out_cap, stderr_limit_bytes=err_cap, output_total_limit_bytes=total)
        def action(call, fake):
            out, err, out_drop, err_drop = _capture(raw_out, raw_err, out_cap, err_cap, call["output_remaining_bytes"])
            return fake.result_factory(_local(call, status=HookStatus.INVALID_OUTPUT, error_category="hook_script_output_limit", stdout=out, stderr=err, stdout_dropped=out_drop, stderr_dropped=err_drop))
        result, runner, _, _ = _run(case, (action,))
        _assert_settlement(result, "invalid_output", "hook_script_output_limit", 2, True)
        first, second = result.entry_results
        assert (first.status, first.error_category, first.stdout, first.stderr,
            first.stdout_dropped, first.stderr_dropped) == (HookStatus.INVALID_OUTPUT,
            "hook_script_output_limit", *expected)
        assert (second.status, second.error_category) == (HookStatus.SUCCESS, None)
        assert len(runner.calls) == 2
    case = _baseline(("a",)); sentinel = b"kept-output-sentinel"
    case["policy"] = replace(case["policy"], stdout_limit_bytes=64, stderr_limit_bytes=64)
    def binary(call, fake): return fake.result_factory(_local(call, stdout=sentinel, stderr=b"\xfe"))
    result, _, _, _ = _run(case, (binary,)); assert result.entry_results[0].status is HookStatus.SUCCESS
    captured = capsys.readouterr(); assert sentinel.decode() not in captured.out and sentinel.decode() not in captured.err and sentinel.decode() not in caplog.text
    case = _baseline(); case["policy"] = replace(case["policy"], stdout_limit_bytes=4, stderr_limit_bytes=4, output_total_limit_bytes=6)
    raws = ((b"abc", b"d"), (b"XYZ", b"q"), (b"z", b""))
    def aggregate(call, fake):
        out, err, out_drop, err_drop = _capture(*raws[call["entry_index"]], 4, 4, call["output_remaining_bytes"])
        invalid = out_drop + err_drop > 0
        return fake.result_factory(_local(call, status=HookStatus.INVALID_OUTPUT if invalid else HookStatus.SUCCESS, error_category="hook_script_output_limit" if invalid else None, stdout=out, stderr=err, stdout_dropped=out_drop, stderr_dropped=err_drop))
    result, runner, _, _ = _run(case, (aggregate, aggregate, aggregate))
    assert [call["output_remaining_bytes"] for call in runner.calls] == [6, 2, 0]
    assert [(x.stdout, x.stderr, x.stdout_dropped, x.stderr_dropped) for x in result.entry_results] == [(b"abc", b"d", 0, 0), (b"XY", b"", 1, 1), (b"", b"", 1, 0)]
    assert sum(len(x.stdout) + len(x.stderr) for x in result.entry_results) == 6 and (result.status, result.error_category) == ("invalid_output", "hook_script_output_limit")
    assert [(item.status, item.error_category) for item in result.entry_results] == [(HookStatus.SUCCESS, None), (HookStatus.INVALID_OUTPUT, "hook_script_output_limit"), (HookStatus.INVALID_OUTPUT, "hook_script_output_limit")]
    resolved = _api()
    malformed_cases = (("not-bytes", 64, 64), (b"overflow", 1, 64), (b"overflow", 64, 1))
    for malformed, stream_cap, total_cap in malformed_cases:
        case = _baseline(("a", "b")); case["policy"] = replace(case["policy"], stdout_limit_bytes=stream_cap, output_total_limit_bytes=total_cap)
        actual, bad_runner = _prepare(case, resolved)
        trusted = bad_runner.result_factory(LocalHookScriptEntryResult(0, "a", HookStatus.SUCCESS, True, 0))
        def malformed_action(call, fake, value=malformed):
            fake.snapshots[0] = trusted
            return fake.result_factory(_local(call, stdout=value))
        bad_runner.actions = (malformed_action,)
        bad = _invoke(resolved, actual, bad_runner)
        _assert_settlement(bad, "invalid_output", "hook_script_invalid_result", 2, True)
        assert len(bad_runner.calls) == 1 and bad_runner.current_calls == [0] and bad_runner.retry_calls == []
        assert (bad.entry_results[0].status, bad.entry_results[0].error_category) == (HookStatus.INVALID_OUTPUT, "hook_script_invalid_result")
        _assert_skipped(bad.entry_results[1], HookStatus.SKIPPED_DEPENDENCY, 1, "b", "hook_script_invalid_result")
def test_b15_malformed_and_unsupported_have_all_successors():
    string_subtype = type("StringSubtype", (str,), {})
    local_malformed = (
        LocalHookScriptEntryResult(9, "a", HookStatus.SUCCESS, True, 0),
        LocalHookScriptEntryResult(False, "a", HookStatus.SUCCESS, True, 0),
        LocalHookScriptEntryResult(0.0, "a", HookStatus.SUCCESS, True, 0),
        LocalHookScriptEntryResult(0, "wrong", HookStatus.SUCCESS, True, 0),
        LocalHookScriptEntryResult(0, string_subtype("a"), HookStatus.SUCCESS, True, 0),
        LocalHookScriptEntryResult(0, "a", HookStatus.SUCCESS, True, 0, stdout=b"x" * 70000),
        LocalHookScriptEntryResult(0, "a", HookStatus.SUCCESS, True, 0, duration_ms="bad"),
    )
    resolved = _api(); result_type = resolved[-1]
    malformed_values = (object(), "text", *(result_type(**_mapping(value)) for value in local_malformed))
    for malformed in malformed_values:
        case = _baseline(); actual, runner = _prepare(case, resolved)
        trusted = runner.result_factory(LocalHookScriptEntryResult(0, "a", HookStatus.SUCCESS, True, 0))
        def action(call, fake): fake.snapshots[0] = trusted; return malformed
        runner.actions = (action,)
        result = _invoke(resolved, actual, runner)
        _assert_settlement(result, "invalid_output", "hook_script_invalid_result", 3, True)
        assert len(result.entry_results) == 3 and runner.current_calls == [0] and len(runner.calls) == 1
        first = result.entry_results[0]
        assert (first.status, first.error_category, first.started, first.exit_code,
            first.cleanup_confirmed, first.cleanup_debt) == (
            HookStatus.INVALID_OUTPUT, "hook_script_invalid_result", True, 0, True, None)
        for index in (1, 2): _assert_skipped(result.entry_results[index], HookStatus.SKIPPED_DEPENDENCY, index, "abc"[index], "hook_script_invalid_result")
    case = _baseline(); actual, pending_runner = _prepare(case, resolved); debt = FakeDebt("malformed-pending")
    def malformed_pending(call, fake):
        fake.debts = (debt,)
        fake.snapshots[0] = fake.result_factory(_local(call, exit_code=7, cleanup_confirmed=False, cleanup_debt="malformed-pending"))
        return object()
    pending_runner.actions = (malformed_pending,)
    pending_result = _invoke(resolved, actual, pending_runner)
    _assert_settlement(pending_result, "error", "hook_script_cleanup_pending", 3, True)
    first = pending_result.entry_results[0]
    assert (first.status, first.error_category, first.started, first.exit_code,
        first.cleanup_confirmed, first.cleanup_debt) == (
        HookStatus.ERROR, "hook_script_cleanup_pending", True, 7, False, "malformed-pending")
    assert len(pending_runner.calls) == 1 and pending_runner.current_calls == [0]
    assert pending_runner.retry_calls == [] and pending_runner.cleanup_debts()[0] is debt
    for index in (1, 2): _assert_skipped(pending_result.entry_results[index], HookStatus.SKIPPED_DEPENDENCY, index, "abc"[index], "hook_script_cleanup_pending")
    case = _baseline()
    def unsupported(call, fake): return fake.result_factory(_local(call, status=HookStatus.ERROR, started=False, exit_code=None, error_category="hook_script_unsupported_backend"))
    result, runner, _, _ = _run(case, (unsupported,))
    _assert_settlement(result, "error", "hook_script_unsupported_backend", 3, False)
    assert (result.entry_results[0].status, result.entry_results[0].error_category,
        result.entry_results[0].started, result.entry_results[0].exit_code) == (
        HookStatus.ERROR, "hook_script_unsupported_backend", False, None)
    assert len(result.entry_results) == 3 and len(runner.calls) == 1
    for index in (1, 2): _assert_skipped(result.entry_results[index], HookStatus.SKIPPED_DEPENDENCY, index, "abc"[index], "hook_script_unsupported_backend")
    malformed_snapshots = (
        result_type(**_mapping(LocalHookScriptEntryResult(False, "a", HookStatus.ERROR, False))),
        result_type(**_mapping(LocalHookScriptEntryResult(0.0, "a", HookStatus.ERROR, False))),
        result_type(**_mapping(LocalHookScriptEntryResult(0, string_subtype("a"), HookStatus.ERROR, False))),
    )
    for fault in (RuntimeError("snapshot-secret"), object(), *malformed_snapshots):
        case = _baseline(); resolved = _api(); actual, runner = _prepare(case, resolved); runner.snapshot_faults[0] = fault; runner.actions = (lambda call, fake: object(),)
        with pytest.raises(RuntimeError, match="^hook_script_runner_error$"): _invoke(resolved, actual, runner)
        assert len(runner.calls) == 1 and runner.current_calls == [0] and runner.retry_calls == []
def test_b16_execution_is_pure_and_preserves_inputs(monkeypatch):
    resolved = _api(); case = _baseline(("a",)); actual, runner = _prepare(case, resolved); before = _projection(actual)
    import builtins, importlib, os, subprocess
    import topsailai.hooks as hooks
    import topsailai.hooks.hook_script as script
    import topsailai.hooks.hook_script_discovery as discovery
    counts = {}; plans = []; original_bridge = script.build_hook_point_binding_plan_from_discovery
    def bridge(**kwargs): plan = original_bridge(**kwargs); plans.append(plan); return plan
    def forbidden(name):
        def call(*args, **kwargs): counts[name] = counts.get(name, 0) + 1; raise AssertionError(name)
        return call
    targets = ((discovery, "discover_hook_script_entries", "discover"), (hooks, "discover_hook_script_entries", "discover-public"), (script, "hook_script_ready", "ready"), (script, "settle_configured_empty_hook_script", "configured-empty"), (script, "settle_unconfigured_hook_script", "legacy-empty"), (subprocess, "Popen", "popen"), (subprocess, "run", "run"), (subprocess, "call", "call"), (subprocess, "check_call", "check-call"), (subprocess, "check_output", "check-output"), (os, "system", "system"), (os, "getenv", "getenv"), (importlib, "import_module", "import-module"), (importlib.util, "spec_from_file_location", "spec"))
    original_import = builtins.__import__
    def guarded_import(name, *args, **kwargs):
        if name.startswith(("fixtures.alpha", "hook_script_candidate")): counts["candidate-import"] = counts.get("candidate-import", 0) + 1; raise AssertionError(name)
        return original_import(name, *args, **kwargs)
    class NoEnvironment(dict):
        def _reject(self, *args, **kwargs): counts["environment"] = counts.get("environment", 0) + 1; raise AssertionError("environment")
        get = __getitem__ = __iter__ = copy = items = keys = values = _reject
    with monkeypatch.context() as patch:
        for obj, attribute, name in targets: patch.setattr(obj, attribute, forbidden(name))
        patch.setattr(builtins, "__import__", guarded_import); patch.setattr(script, "build_hook_point_binding_plan_from_discovery", bridge)
        patch.setattr(script.os if hasattr(script, "os") else os, "environ", NoEnvironment())
        scheduler_type = getattr(__import__("topsailai.hooks.scheduler", fromlist=["HookScheduler"]), "HookScheduler")
        for owner, methods in ((hooks.HookRuntime, ("__init__", "dispatch", "adispatch")), (hooks.HookRegistry, ("__init__", "register")), (scheduler_type, ("__init__",))):
            for method in methods: patch.setattr(owner, method, forbidden(f"{owner.__name__}.{method}"))
        result = _invoke(resolved, actual, runner)
    _assert_settlement(result, "success", None, 1, True)
    assert counts == {} and _projection(actual) == before and len(runner.calls) == len(plans) == 1; call = runner.calls[0]
    assert call["context"] is actual["context"] and call["options"] is actual["options"] and call["policy"] is actual["policy"] and call["cancellation"] is actual["cancellation"]
    assert call["entry"] is not actual["discovery_result"].entries[0] and call["entry"] is plans[0].bindings[-1].entries[0]
    assert actual["options"].argv == ("--literal",) and actual["options"].environment == (("SAFE", "1"),) and actual["options"].cwd == case["options"].cwd
