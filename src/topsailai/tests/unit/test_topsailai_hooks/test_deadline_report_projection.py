"""Aggregate deadline report projection regressions. Author: DawsonLin."""
from types import SimpleNamespace
import pytest
from topsailai.hooks import configured_runtime as configured
from topsailai.hooks.registry import HookRegistry
from topsailai.tests.unit.test_topsailai_hooks.test_simplified_configured_coverage import _publish


@pytest.mark.parametrize("stage,status,now,expected", [
    ("module", "timeout", 12.0, True),
    ("script", "timeout", 12.5, True),
    ("empty", "timeout", 12.0, True),
    ("module", "success", 11.0, False),
    ("empty", "success", 11.0, False),
    ("module", "error", 11.0, False),
    ("module", "timeout", 11.0, False),
])
def test_completion_observes_original_aggregate_deadline(tmp_path, monkeypatch, stage, status, now, expected):
    """Project report time, not status or admission-relative duration, before cleanup."""
    registry = HookRegistry()
    plan, _ = _publish(registry, tmp_path)
    reader = registry.acquire_hook_point("scope-a", "hook_test")
    event = SimpleNamespace(event_id="event")
    admission = configured._ConfiguredAdmission(event, plan, 7, 100_000, 10.0,
        reader=reader, registry=registry, deadline=12.0)
    recovery = SimpleNamespace(reserve=lambda receiver: "ticket", bind=lambda *args: None)
    runtime = SimpleNamespace(_publication_recovery=recovery, _backend=None,
        _settings=SimpleNamespace(limits=SimpleNamespace(bindings_per_event=32)))
    terminal = SimpleNamespace(status="success", not_run_reason=None)
    module = SimpleNamespace(status=status, handler=SimpleNamespace(id="module"),
        timing=SimpleNamespace(elapsed_ms=0), error=None, not_run_reason=None)
    result = SimpleNamespace(status=status, handlers=(module, terminal) if stage == "module" else (terminal,))
    if stage == "script":
        admission.plan = SimpleNamespace(entries=(object(),))
    seen = []
    finished = []

    def execute(**kwargs):
        """Record the original forwarded budget and return a controlled settled result."""
        seen.append(kwargs["deadline"])
        if stage == "script":
            kwargs["settlement_receiver"](SimpleNamespace(status=status, error_category="deadline", started=True))
        return result

    def finish(*args):
        """Record finalization separately from report clock observation."""
        finished.append(True)
        admission.release()

    monkeypatch.setattr(configured, "time", SimpleNamespace(monotonic=lambda: now))
    monkeypatch.setattr(configured, "ExecutionCleanupCustody", lambda *args: SimpleNamespace())
    monkeypatch.setattr(registry, "retain_hook_point_cleanup", lambda *args: None)
    monkeypatch.setattr(configured, "_ExecutionRunners", lambda *args: SimpleNamespace(scripts=None))
    monkeypatch.setattr(configured, "execute_hook_point", execute)
    monkeypatch.setattr(configured, "_finish_configured_execution", finish)
    try:
        report = configured._execute_configured(runtime, admission)
        assert report.deadline_exhausted is expected
        assert report.unified_result is result and report.rejection_reason is None
        assert len(report.outcomes) == (0 if stage == "empty" else 1)
        if report.outcomes:
            assert report.outcomes[0].status.value == status
        assert seen == [12.0] and finished == [True] and admission.released
    finally:
        admission.release()
        plan.retire()


@pytest.mark.parametrize("branch", ["queued", "running"])
def test_expired_carriers_are_independently_asserted(tmp_path, monkeypatch, branch):
    """Exercise each terminal carrier deterministically, without scheduler branch luck."""
    registry = HookRegistry()
    plan, _ = _publish(registry, tmp_path)
    admission = configured._ConfiguredAdmission(SimpleNamespace(event_id="event"), plan, 7,
        100_000, 10.0, reader=registry.acquire_hook_point("scope-a", "hook_test"),
        registry=registry, deadline=12.0)
    try:
        if branch == "queued":
            report = configured._terminal_configured(admission, "deadline")
            assert report.unified_result is None and report.rejection_reason == "deadline"
        else:
            runtime = SimpleNamespace(_publication_recovery=SimpleNamespace(
                reserve=lambda receiver: "ticket", bind=lambda *args: None),
                _backend=None, _settings=SimpleNamespace(limits=SimpleNamespace(bindings_per_event=32)))
            monkeypatch.setattr(configured, "time", SimpleNamespace(monotonic=lambda: 12.0))
            monkeypatch.setattr(configured, "ExecutionCleanupCustody", lambda *args: SimpleNamespace())
            monkeypatch.setattr(registry, "retain_hook_point_cleanup", lambda *args: None)
            monkeypatch.setattr(configured, "_ExecutionRunners", lambda *args: SimpleNamespace(scripts=None))
            result = SimpleNamespace(status="timeout", handlers=(SimpleNamespace(status="not_run", not_run_reason="deadline"),))
            monkeypatch.setattr(configured, "execute_hook_point", lambda **kwargs: result)
            monkeypatch.setattr(configured, "_finish_configured_execution", lambda *args: admission.release())
            report = configured._execute_configured(runtime, admission)
            assert report.unified_result is result and report.rejection_reason is None
        assert report.deadline_exhausted and admission.released
    finally:
        admission.release()
        plan.retire()


@pytest.mark.parametrize("stage,status,expired", [
    ("module", "timeout", True), ("script", "timeout", True),
    ("empty", "timeout", True), ("module", "success", False),
    ("empty", "success", False), ("module", "error", False),
    ("module", "timeout", False),
])
def test_real_unified_engine_projects_aggregate_not_handler_timeout(monkeypatch, stage, status, expired):
    """Compose real plan ordering and settlement with detached execution clocks."""
    from topsailai.hooks.hook_point_executor import execute_hook_point
    from topsailai.hooks.process_state import WorkerResult
    from topsailai.hooks.hook_script_contracts import HookScriptSettlement, HookScriptEntryResult
    from topsailai.hooks.contracts import HookStatus
    from topsailai.tests.unit.test_topsailai_hooks.test_hook_point_executor import reader
    from topsailai.tests.unit.test_topsailai_hooks.test_hook_point_plan_contracts import captured
    snapshot = reader(modules=(captured("module"),) if stage == "module" else (),
        scripts=(captured("script"),) if stage == "script" else ())
    clock = [12.0 if stage == "empty" and expired else 10.0]
    calls = []
    releases = []
    registry = SimpleNamespace(retain_hook_point_cleanup=lambda *args: None,
        release_hook_point=lambda token: releases.append(token))
    admission = configured._ConfiguredAdmission(SimpleNamespace(event_id="event"),
        SimpleNamespace(entries=snapshot.snapshot.plan.default_script_hook.scripts), 7,
        100_000, 10.0, reader=snapshot, registry=registry, deadline=12.0)
    runtime = SimpleNamespace(_publication_recovery=SimpleNamespace(
        reserve=lambda receiver: "ticket", bind=lambda *args: None), _backend=None,
        _settings=SimpleNamespace(limits=SimpleNamespace(bindings_per_event=32)))

    def module_execute(*args, **kwargs):
        """Return a local timeout independently from aggregate expiry."""
        calls.append(kwargs["deadline"])
        clock[0] = 12.0 if expired else 11.0
        return WorkerResult(status, cleanup_confirmed=True)

    def script_execute(**kwargs):
        """Expire the shared budget only in the Script execution seam."""
        calls.append(kwargs["dispatch_deadline"])
        clock[0] = 12.0
        child = HookScriptEntryResult(0, "plugin", HookStatus.TIMEOUT, True, cleanup_confirmed=True)
        return HookScriptSettlement("timeout", (child,), True, "deadline")

    def execute(**kwargs):
        """Use the real unified orchestration with an explicit isolated clock."""
        return execute_hook_point(**kwargs, clock=lambda: clock[0])

    monkeypatch.setattr(configured, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(configured, "ExecutionCleanupCustody", lambda *args: SimpleNamespace())
    monkeypatch.setattr(configured, "_ExecutionRunners", lambda *args: SimpleNamespace(
        modules=SimpleNamespace(execute=module_execute), scripts=None))
    monkeypatch.setattr(configured, "execute_hook_point", execute)
    monkeypatch.setattr(configured, "execute_configured_hook_script", script_execute)
    monkeypatch.setattr(configured, "_finish_configured_execution", lambda *args: admission.release())
    report = configured._execute_configured(runtime, admission)
    assert report.deadline_exhausted is expired
    result = report.unified_result
    expected_status = "completed_with_errors" if status == "error" else status
    assert result.status == expected_status and result.cleanup.state == "safe"
    assert calls == ([] if stage == "empty" else [12.0])
    assert releases == [snapshot] and admission.released
    if stage == "module" and status == "timeout":
        assert result.handlers[-1].status == "not_run"
        assert result.handlers[-1].not_run_reason == ("deadline" if expired else "timeout")
