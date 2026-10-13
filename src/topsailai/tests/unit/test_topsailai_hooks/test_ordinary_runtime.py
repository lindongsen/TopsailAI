"""Ordinary source registration and complete execution. Author: DawsonLin."""
from topsailai.tests.unit.test_topsailai_hooks.test_simplified_configured_runtime import _runtime, _event


def test_ordinary_empty_default(tmp_path):
    """An ordinary source registration always executes the single default Hook."""
    runtime, scope = _runtime(tmp_path)
    try:
        assert runtime.register_hook_point('hook_before_chat', scope).accepted
        report = runtime.dispatch_hook_point('hook_before_chat', _event(runtime, scope))
        assert report.unified_result.status == 'success'
        assert len(report.unified_result.handlers) == 1
        default = report.unified_result.handlers[0]
        assert default.handler.kind == 'default_script_hook'
        assert default.status == 'success'
        assert not default.returned.present
        assert default.returned.representation == 'unavailable'
        assert default.children == () and default.cleanup.state == 'safe'
        assert not runtime.cleanup_debts()
    finally:
        runtime.close()


def test_real_modules_then_default_scripts(tmp_path, monkeypatch):
    """Capture internally and run sealed Modules before ordered default children."""
    import sys
    import time
    import json
    from pathlib import Path
    from topsailai.hooks import HookRuntime, HookSettings, ConfiguredTrustPolicy
    from topsailai.hooks.configuration import HookLimits
    from topsailai.tests.unit.test_topsailai_hooks.test_hook_point_plan_capture import fixtures
    from topsailai.tests.unit.test_topsailai_hooks.test_simplified_configured_runtime import (
        _protocol_script, _assertion, _real_event,
    )
    import topsailai.hooks.ordinary_runtime as ordinary
    build, inputs, output, imported, called = fixtures(tmp_path)
    scripts = tuple(_protocol_script(entry.source_path.with_name(entry.registered_name),
                    entry.registered_name) for entry in inputs['script_discovery'].entries)
    trust = inputs['trust']
    configured = ConfiguredTrustPolicy(source_roots=trust.source_roots,
        allowed_interpreters=(Path(sys.executable).resolve(),),
        closure_assertions=tuple(a for a in trust.closure_assertions if a.kind == 'python_source')
            + tuple(_assertion(path) for path in scripts), python_runtime=trust.python_runtime)
    runtime = HookRuntime(HookSettings(limits=HookLimits(dispatch_timeout_ms=10_000)), temp_root=str(tmp_path / 'runtime'), configured_trust=configured)
    scope = runtime.open_scope()
    original = ordinary.build_hook_point_candidate
    deadlines = []
    identities = []
    timings = {}
    admit = ordinary._admit_configured

    def admission(*args, **kwargs):
        """Observe exact prepared deadline at the real scheduler admission boundary."""
        timings['prepared_at'] = time.monotonic()
        assert args[5] == deadlines[0]
        return admit(*args, **kwargs)

    def capture(*args, **kwargs):
        """Mutate live sources only after capture and record the original deadline."""
        candidate = original(*args, **kwargs)
        deadlines.append(kwargs['deadline'])
        identities.extend(item.identity for item in candidate.plan.default_script_hook.scripts)
        for source in inputs['modules']:
            source.source_path.chmod(0o600)
            source.source_path.write_text("raise RuntimeError('live source reopened')\n")
        return candidate

    monkeypatch.setattr(ordinary, 'build_hook_point_candidate', capture)
    monkeypatch.setattr(ordinary, '_admit_configured', admission)
    try:
        assert runtime.register_hook_point('hook_real', scope, modules=list(inputs['modules']), scripts=scripts).accepted
        event = _real_event(runtime, scope, tmp_path / 'calls')
        timings['started_at'] = time.monotonic()
        report = runtime.dispatch_hook_point('hook_real', event)
        timings['finished_at'] = time.monotonic()
        assert timings['started_at'] + 10 <= deadlines[0] <= timings['prepared_at'] + 10
        assert timings['finished_at'] < deadlines[0]
        evidence = dict(timings, deadline=deadlines[0],
            preparation_seconds=timings['prepared_at'] - timings['started_at'],
            execution_seconds=timings['finished_at'] - timings['prepared_at'])
        (tmp_path / 'timing.json').write_text(json.dumps(evidence))
        assert report.rejection_reason is None, report.rejection_reason
        result = report.unified_result
        assert result.status == 'success' and result.cleanup.state == 'safe', result
        assert [item.handler.name for item in result.handlers[:-1]] == ['A', 'Z']
        assert all(item.returned.present and item.returned.value is None for item in result.handlers[:-1])
        default = result.handlers[-1]
        assert default.status == 'success' and default.cleanup.state == 'safe'
        assert default.returned.present and default.returned.representation == 'direct'
        assert [item.handler for item in default.children] == identities
        assert [item.handler.name for item in default.children] == ['A', 'Z']
        assert len(default.returned.value) == len(default.children) == 2
        for child, raw in zip(default.children, default.returned.value):
            assert child.status == 'success' and child.cleanup.state == 'safe'
            assert child.returned.present and child.returned.representation == 'direct'
            assert child.returned.value == {
                'exit_code': raw.exit_code, 'stdout': raw.stdout, 'stderr': raw.stderr,
                'stdout_dropped': raw.stdout_dropped, 'stderr_dropped': raw.stderr_dropped,
            }
            assert raw.exit_code == 0 and raw.stdout == raw.stderr == b''
            assert not raw.stdout_dropped and not raw.stderr_dropped
            assert raw.cleanup_confirmed
        assert (tmp_path / 'calls').read_text().splitlines() == ['A', 'Z']
        assert called.exists() and imported.exists() and len(deadlines) == 1
        assert not runtime.cleanup_debts() and not runtime.retry_cleanup('foreign')
    finally:
        runtime.close()


def test_deadline_precedes_discovery(tmp_path, monkeypatch):
    """Preparation cannot restart the execution budget after slow discovery."""
    import time
    import topsailai.hooks.ordinary_runtime as ordinary
    runtime, scope = _runtime(tmp_path)
    original = ordinary.discover_configured_hook_scripts
    entered = []

    def slow_discovery(**kwargs):
        """Consume the complete budget before candidate preparation starts."""
        entered.append(time.monotonic())
        time.sleep(0.03)
        return original(**kwargs)

    monkeypatch.setattr(ordinary, 'discover_configured_hook_scripts', slow_discovery)
    try:
        assert runtime.register_hook_point('hook_before_chat', scope).accepted
        report = runtime.dispatch_hook_point('hook_before_chat', _event(runtime, scope), 10)
        assert report.rejection_reason == 'deadline'
        assert entered and not runtime.cleanup_debts()
    finally:
        runtime.close()


def test_capture_interrupt_preserves_identity(tmp_path, monkeypatch):
    """A preparation interrupt retains original identity and settles reservations."""
    import pytest
    import topsailai.hooks.ordinary_runtime as ordinary
    runtime, scope = _runtime(tmp_path)
    primary = KeyboardInterrupt('capture interrupted')

    def interrupt(*args, **kwargs):
        """Raise before allocation through the real ordinary preparation boundary."""
        raise primary

    monkeypatch.setattr(ordinary, 'build_hook_point_candidate', interrupt)
    try:
        assert runtime.register_hook_point('hook_before_chat', scope).accepted
        with pytest.raises(KeyboardInterrupt) as raised:
            runtime.dispatch_hook_point('hook_before_chat', _event(runtime, scope))
        assert raised.value is primary and not runtime.cleanup_debts()
    finally:
        runtime.close()


def test_scope_cleanup_and_detached_descriptors(tmp_path):
    """Caller mutations and closed scopes cannot retain or change registrations."""
    runtime, scope = _runtime(tmp_path)
    scripts = []
    try:
        assert runtime.register_hook_point('hook_before_chat', scope, scripts=scripts).changed
        scripts.append(tmp_path / 'not-registered')
        assert runtime.dispatch_hook_point('hook_before_chat', _event(runtime, scope)).unified_result.status == 'success'
        scope.close()
        assert not runtime._ordinary_sources
        assert not runtime.register_hook_point('hook_before_chat', scope).accepted
    finally:
        runtime.close()


def test_allocated_capture_interrupt_settles_exact_owner(tmp_path, monkeypatch):
    """Finalize an allocated candidate without replacing its host interruption."""
    import pytest
    import topsailai.hooks.ordinary_runtime as ordinary
    runtime, scope = _runtime(tmp_path)
    original = ordinary.build_hook_point_candidate
    primary = KeyboardInterrupt('allocated capture interrupted')
    owners = []

    def interrupt(*args, **kwargs):
        """Raise after the real builder has armed its receiver and completed capture."""
        owner = original(*args, **kwargs)
        owners.append(owner)
        primary.recovery_owner = owner
        raise primary

    monkeypatch.setattr(ordinary, 'build_hook_point_candidate', interrupt)
    try:
        assert runtime.register_hook_point('hook_before_chat', scope).accepted
        with pytest.raises(KeyboardInterrupt) as raised:
            runtime.dispatch_hook_point('hook_before_chat', _event(runtime, scope))
        assert raised.value is primary
        assert len(owners) == 1 and owners[0]._closed
        assert not runtime.cleanup_debts()
        assert runtime._registry.configured_plan(scope.scope_id, 'hook_before_chat')[1] is None
    finally:
        runtime.close()


def test_registration_rejection_matrix(tmp_path):
    """Reject malformed and excessive sources before publication."""
    from topsailai.tests.unit.test_topsailai_hooks.test_hook_point_plan_capture import fixtures
    runtime, scope = _runtime(tmp_path)
    _, inputs, _, _, _ = fixtures(tmp_path)
    source = inputs['modules'][0]
    try:
        assert runtime.register_hook_point('invalid', scope).errors == ('invalid_hook_name',)
        for arguments in ({'modules': None}, {'scripts': None}, {'scripts': [tmp_path] * 129},
                          {'modules': [object()]}, {'scripts': ['relative']},
                          {'modules': [source, source]}, {'scripts': [None]}):
            assert runtime.register_hook_point('hook_before_chat', scope, **arguments).errors == ('invalid_sources',)
        for index in range(128):
            assert runtime.register_hook_point(f'hook_point_{index}', scope).accepted
        assert runtime.register_hook_point('hook_excess', scope).errors == ('registration_capacity_exceeded',)
        assert runtime.register_hook_point('hook_point_0', scope).accepted
    finally:
        runtime.close()
    assert runtime.register_hook_point('hook_before_chat', scope).errors == ('runtime_closed',)


def test_dispatch_rejection_matrix(tmp_path):
    """Reject missing authority, invalid stop input and closed admission."""
    import pytest
    runtime, scope = _runtime(tmp_path)
    event = _event(runtime, scope)
    try:
        assert runtime.dispatch_hook_point('hook_unknown', event).rejection_reason == 'unknown_hook_point'
        assert runtime.register_hook_point('hook_before_chat', scope).accepted
        with pytest.raises(ValueError, match='invalid cancellation'):
            runtime.dispatch_hook_point('hook_before_chat', event, cancellation=object())
        runtime._configured_trust = None
        assert runtime.dispatch_hook_point('hook_before_chat', event).rejection_reason == 'trust_policy_missing'
        scope.close()
        assert runtime.dispatch_hook_point('hook_before_chat', event).rejection_reason is not None
    finally:
        runtime.close()


def test_prepare_stop_and_rejection_boundaries(tmp_path, monkeypatch):
    """Observe cancellation before discovery and before publication without leaking owners."""
    import threading
    from types import SimpleNamespace
    import topsailai.hooks.ordinary_runtime as ordinary
    for mode in ('capacity', 'cancelled', 'discovery', 'after_discovery', 'closed',
                 'after_capture', 'publication', 'admission'):
        runtime, scope = _runtime(tmp_path / mode)
        cancellation = threading.Event()
        original_build = ordinary.build_hook_point_candidate
        original_discovery = ordinary.discover_configured_hook_scripts
        event = _event(runtime, scope)
        try:
            assert runtime.register_hook_point('hook_before_chat', scope).accepted
            with monkeypatch.context() as patch:
                if mode == 'capacity':
                    patch.setattr(runtime._publication_recovery, 'reserve', lambda receiver: None)
                elif mode == 'cancelled':
                    cancellation.set()
                elif mode == 'discovery':
                    patch.setattr(ordinary, 'discover_configured_hook_scripts', lambda **kwargs: SimpleNamespace(accepted=False))
                elif mode == 'after_discovery':
                    def discovery(**kwargs):
                        """Set cancellation at the completed discovery boundary."""
                        result = original_discovery(**kwargs)
                        cancellation.set()
                        return result
                    patch.setattr(ordinary, 'discover_configured_hook_scripts', discovery)
                elif mode in ('closed', 'after_capture'):
                    def capture(*args, **kwargs):
                        """Move scope or stop facts only after candidate custody is armed."""
                        candidate = original_build(*args, **kwargs)
                        if mode == 'closed':
                            scope.close()
                        else:
                            cancellation.set()
                        return candidate
                    patch.setattr(ordinary, 'build_hook_point_candidate', capture)
                elif mode == 'publication':
                    patch.setattr(runtime._registry, 'publish_hook_point', lambda *args, **kwargs: SimpleNamespace(accepted=False))
                else:
                    patch.setattr(ordinary, '_admit_configured', lambda *args, **kwargs: (None, runtime._rejected(event, 'capacity')))
                report = runtime.dispatch_hook_point('hook_before_chat', event, cancellation=cancellation)
            expected = {'capacity': 'publication_capacity_exceeded', 'cancelled': 'cancelled',
                        'discovery': 'discovery_rejected', 'after_discovery': 'cancelled',
                        'closed': 'closed_scope', 'after_capture': 'cancelled',
                        'publication': 'artifact_rejected', 'admission': 'capacity'}[mode]
            assert report.rejection_reason == expected
            assert not runtime.cleanup_debts()
        finally:
            runtime.close()


def test_concurrent_dispatch_uses_distinct_exact_readers(tmp_path, monkeypatch):
    """Keep concurrent admissions separate across an unchanged exact publication."""
    from concurrent.futures import ThreadPoolExecutor
    import threading
    import topsailai.hooks.configured_runtime as configured
    runtime, scope = _runtime(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    submitted = threading.Event()
    original = configured._execute_configured
    submit = runtime._scheduler.submit
    readers = []
    works = []

    def execute(*args):
        """Hold the first acquired reader while its peer is admitted."""
        readers.append(args[1].reader)
        if len(readers) == 1:
            entered.set()
            assert release.wait(5)
        return original(*args)

    def observe_submit(*args, **kwargs):
        """Record successful second admission before releasing the first worker."""
        work = submit(*args, **kwargs)
        works.append(work)
        if len(works) == 2:
            submitted.set()
        return work

    monkeypatch.setattr(configured, '_execute_configured', execute)
    monkeypatch.setattr(runtime._scheduler, 'submit', observe_submit)
    try:
        assert runtime.register_hook_point('hook_before_chat', scope).accepted
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(runtime.dispatch_hook_point, 'hook_before_chat', _event(runtime, scope), 10_000)
            assert entered.wait(5)
            second = pool.submit(runtime.dispatch_hook_point, 'hook_before_chat', _event(runtime, scope), 10_000)
            try:
                assert submitted.wait(5)
            finally:
                release.set()
            results = [first.result(5), second.result(5)]
        assert all(item.unified_result.status == 'success' for item in results)
        assert len(readers) == 2 and readers[0] is not readers[1]
        assert readers[0].owner is readers[1].owner
        assert not runtime.cleanup_debts() and not runtime.retry_cleanup('foreign')
    finally:
        release.set()
        runtime.close()



def test_scope_cleanup_preserves_peer_registration(tmp_path):
    """Retire only the selected scope while preserving its peer's descriptors."""
    runtime, scope = _runtime(tmp_path)
    peer = runtime.open_scope()
    try:
        assert runtime.register_hook_point('hook_before_chat', scope).accepted
        assert runtime.register_hook_point('hook_before_chat', peer).accepted
        scope.close()
        assert set(runtime._ordinary_sources) == {(peer.scope_id, 'hook_before_chat')}
        result = runtime.dispatch_hook_point('hook_before_chat', _event(runtime, peer))
        assert result.unified_result.status == 'success'
        peer.close()
        assert not runtime._ordinary_sources and not runtime.cleanup_debts()
    finally:
        runtime.close()


def test_public_dispatch_retains_only_exact_execution_debt(tmp_path, monkeypatch):
    """Real ordinary children retain exact custody without granting peer retry rights."""
    import topsailai.hooks.configured_runtime as configured
    from topsailai.tests.unit.test_topsailai_hooks.test_simplified_configured_runtime import (
        _protocol_script, _real_runtime, _real_event,
    )
    script = _protocol_script(tmp_path / 'sources' / 'child', 'child')
    runtime, scope = _real_runtime(tmp_path, (script,))
    backend = runtime._backend
    launch = backend.launch_script
    terminate = backend._terminate_record
    retain = runtime._registry.retain_hook_point_cleanup
    held = []
    custodies = []
    hold = [True]
    retries = []
    retry = backend.retry_cleanup

    def launch_child(**kwargs):
        """Journal the first exact Script record before the real launch."""
        if not held:
            held.append(kwargs['record'])
        return launch(**kwargs)

    def terminate_child(record, process):
        """Hold cleanup only for the first execution's original record."""
        if hold[0] and held and record is held[0]:
            return False
        return terminate(record, process)

    def retain_custody(reader, custody):
        """Observe exact execution custody without changing registration authority."""
        custodies.append(custody)
        return retain(reader, custody)

    def retry_record(debt_id, *, record=None):
        """Record exact retry authority reaching the real shared backend."""
        retries.append((debt_id, record))
        return retry(debt_id, record=record)

    monkeypatch.setattr(backend, 'launch_script', launch_child)
    monkeypatch.setattr(backend, '_terminate_record', terminate_child)
    monkeypatch.setattr(backend, 'retry_cleanup', retry_record)
    monkeypatch.setattr(runtime._registry, 'retain_hook_point_cleanup', retain_custody)
    try:
        assert runtime.register_hook_point('hook_child', scope, scripts=(script,)).accepted
        first = runtime.dispatch_hook_point('hook_child', _real_event(runtime, scope, tmp_path / 'calls'), 10_000)
        assert first.unified_result.cleanup.state != 'safe'
        assert len(custodies) == 1 and custodies[0].completed and not custodies[0].settled
        debt_id = held[0].debt_id
        assert any(debt.debt_id == debt_id for debt in custodies[0].cleanup_debts())
        assert not custodies[0].close().accepted
        second = runtime.dispatch_hook_point('hook_child', _real_event(runtime, scope, tmp_path / 'calls'), 10_000)
        assert second.unified_result.status == 'success'
        assert second.unified_result.cleanup.state == 'safe'
        assert len(custodies) == 2 and custodies[1].settled
        assert custodies[1].cleanup_debts() == ()
        before = list(retries)
        assert not custodies[1].retry_cleanup(debt_id)
        assert not custodies[1].runner.retry_cleanup(debt_id)
        assert not custodies[0].retry_cleanup('foreign')
        assert retries == before
        assert (tmp_path / 'calls').read_text().splitlines() == ['child', 'child']
        hold[0] = False
        assert runtime.retry_cleanup(debt_id)
        assert any(record is held[0] for _, record in retries)
        assert custodies[0].settled and not runtime.cleanup_debts()
    finally:
        hold[0] = False
        if held:
            runtime.retry_cleanup(held[0].debt_id)
        runtime.close()
