"""Configured complete-plan compatibility adapter. Author: DawsonLin."""
import threading
import time

import pytest

from topsailai.tests.unit.test_topsailai_hooks.test_simplified_configured_runtime import _runtime, _event
from topsailai.tests.unit.test_topsailai_hooks.test_configured_registration import (
    _Runtime, _Scope, _bootstrap, _catalog,
)
from topsailai.hooks.configured_registration import ConfiguredHookRegistrar, RegistrationState


def test_configured_empty_plan_has_unified_terminal(tmp_path):
    """Preserve empty legacy outcomes while retaining the complete unified result."""
    runtime, scope = _runtime(tmp_path)
    try:
        assert runtime.register_configured('hook_before_chat', scope, scripts=[]).accepted
        report = runtime.dispatch_configured('hook_before_chat', _event(runtime, scope))
        assert report.outcomes == ()
        assert report.unified_result.status == 'success'
        assert len(report.unified_result.handlers) == 1
        assert report.unified_result.handlers[0].handler.kind == 'default_script_hook'
    finally:
        runtime.close()


def test_preparation_deadline_only_stops_own_wait():
    """Shared registration completes after a timed-out caller leaves its wait."""
    runtime = _Runtime()
    registrar = ConfiguredHookRegistrar(runtime, _Scope(), _bootstrap('hook_a'), _catalog('hook_a'))
    owner = threading.Thread(target=lambda: registrar.ensure_registered('hook_a'))
    owner.start()
    try:
        assert runtime.started.wait(1)
        result = registrar.ensure_registered('hook_a', deadline=time.monotonic() + .03,
                                             cancellation=threading.Event())
        assert result.error_category == 'deadline'
        assert registrar.state('hook_a') is RegistrationState.REGISTERING
        runtime.release.set()
        owner.join(1)
        assert not owner.is_alive()
        assert registrar.ensure_registered('hook_a').ready
        assert runtime.calls == 1
    finally:
        runtime.release.set()
        owner.join(2)
        registrar.close()


def test_first_budgeted_owner_leaves_shared_preparation_running():
    """Even the first caller can leave without abandoning the preparation owner."""
    runtime = _Runtime()
    registrar = ConfiguredHookRegistrar(runtime, _Scope(), _bootstrap('hook_a'), _catalog('hook_a'))
    try:
        result = registrar.ensure_registered('hook_a', deadline=time.monotonic() + .03)
        assert result.error_category == 'deadline'
        assert runtime.started.is_set() and runtime.calls == 1
        runtime.release.set()
        assert registrar.ensure_registered('hook_a').ready
    finally:
        runtime.release.set()
        registrar.close()


def test_cancelled_waiter_does_not_cancel_preparation():
    """Cancellation is local while another caller owns singleflight preparation."""
    runtime = _Runtime()
    registrar = ConfiguredHookRegistrar(runtime, _Scope(), _bootstrap('hook_a'), _catalog('hook_a'))
    owner = threading.Thread(target=lambda: registrar.ensure_registered('hook_a'))
    owner.start()
    signal = threading.Event()
    signal.set()
    try:
        assert runtime.started.wait(1)
        result = registrar.ensure_registered('hook_a', cancellation=signal)
        assert result.error_category == 'cancelled'
        assert registrar.state('hook_a') is RegistrationState.REGISTERING
        runtime.release.set()
        owner.join(1)
        assert registrar.ensure_registered('hook_a').ready
    finally:
        runtime.release.set()
        owner.join(2)
        registrar.close()


def test_facade_reuses_preparation_deadline(tmp_path, monkeypatch):
    """The scheduler receives exactly the deadline observed before preparation."""
    from topsailai.hooks.configured_executor import ConfiguredHookExecutor
    from topsailai.hooks.configured_bootstrap import ConfiguredHookBinding, ConfiguredHookBootstrap
    from topsailai.hooks.configured_contracts import ConfiguredTrustPolicy
    runtime, scope = _runtime(tmp_path)
    catalog = _catalog('hook_a')
    bootstrap = ConfiguredHookBootstrap(True, registration_mode='lazy', hooks=(
        ConfiguredHookBinding('hook_a', folder=tmp_path / 'sources'),), trust=ConfiguredTrustPolicy((tmp_path,)),
        trust_identity='a' * 64)
    (tmp_path / 'sources').mkdir()
    registrar = ConfiguredHookRegistrar(runtime, scope, bootstrap, catalog)
    seen = []
    original = registrar.ensure_registered
    def observe(name, **kwargs):
        """Observe the budget before registrar discovery or publication."""
        seen.append(kwargs)
        return original(name, **kwargs)
    monkeypatch.setattr(registrar, 'ensure_registered', observe)
    submit = runtime._scheduler.submit
    def schedule(*args, **kwargs):
        """Require the same absolute deadline at scheduler admission."""
        assert kwargs['deadline_seconds'] == seen[0]['deadline']
        return submit(*args, **kwargs)
    monkeypatch.setattr(runtime._scheduler, 'submit', schedule)
    try:
        facade = ConfiguredHookExecutor(runtime, scope, registrar, catalog)
        report = facade.dispatch(catalog.require('hook_a'), payload={})
        assert report.unified_result.status == 'success'
        assert seen[0]['deadline'] > time.monotonic() - 2
    finally:
        registrar.close()
        runtime.close()


@pytest.mark.parametrize("failure", [RuntimeError("prepare"), KeyboardInterrupt("prepare")])
@pytest.mark.parametrize("closed", [False, True])
def test_budgeted_owner_failure_preserves_identity_and_cell(monkeypatch, failure, closed):
    """Finish the exact shared owner without overwriting a closed cell."""
    registrar = ConfiguredHookRegistrar(_Runtime(), _Scope(), _bootstrap('hook_a'), _catalog('hook_a'))
    owners = []
    original_start = threading.Thread.start

    def start(owner):
        """Retain the exact owner thread for deterministic teardown."""
        owners.append(owner)
        return original_start(owner)

    def register(binding):
        """Raise the original host or ordinary failure from shared preparation."""
        if closed:
            registrar.close()
        raise failure

    monkeypatch.setattr(threading.Thread, 'start', start)
    monkeypatch.setattr(registrar, '_register', register)
    try:
        if closed:
            result = registrar.ensure_registered('hook_a', deadline=time.monotonic() + 1)
            assert result.state is RegistrationState.CLOSED
        else:
            with pytest.raises(type(failure)) as raised:
                registrar.ensure_registered('hook_a', deadline=time.monotonic() + 1)
            assert raised.value is failure
            assert registrar.state('hook_a') is RegistrationState.FAILED_DETERMINISTIC
            with pytest.raises(type(failure)) as cached:
                registrar.ensure_registered('hook_a')
            assert cached.value is failure
    finally:
        registrar.close()
        for owner in owners:
            owner.join(2)
            assert not owner.is_alive()
    if closed:
        assert registrar._cells['hook_a'].exception is None


def test_budgeted_thread_start_failure_finalizes_cell(monkeypatch):
    """Failure before any owner runs wakes future callers with the original error."""
    registrar = ConfiguredHookRegistrar(_Runtime(), _Scope(), _bootstrap('hook_a'), _catalog('hook_a'))
    failure = RuntimeError('cannot start preparation')

    def start(owner):
        """Reject launch before a real preparation thread exists."""
        raise failure

    monkeypatch.setattr(threading.Thread, 'start', start)
    try:
        with pytest.raises(RuntimeError) as raised:
            registrar.ensure_registered('hook_a', deadline=time.monotonic() + 1)
        assert raised.value is failure
        assert registrar.state('hook_a') is RegistrationState.FAILED_DETERMINISTIC
        with pytest.raises(RuntimeError) as cached:
            registrar.ensure_registered('hook_a')
        assert cached.value is failure
    finally:
        registrar.close()


def test_facade_rejects_invalid_cancellation_before_preparation(tmp_path):
    """A malformed cancellation signal cannot authorize preparation."""
    from topsailai.hooks.configured_executor import ConfiguredHookExecutor
    runtime, scope = _runtime(tmp_path)
    catalog = _catalog('hook_a')
    registrar = ConfiguredHookRegistrar(runtime, scope, _bootstrap('hook_a'), catalog)
    try:
        facade = ConfiguredHookExecutor(runtime, scope, registrar, catalog)
        with pytest.raises(ValueError, match='invalid cancellation signal'):
            facade.dispatch(catalog.require('hook_a'), payload={}, cancellation=object())
        assert registrar.state('hook_a') is RegistrationState.UNINITIALIZED
    finally:
        registrar.close()
        runtime.close()


def test_aggregate_cannot_retry_foreign_record(tmp_path):
    """Fresh execution journals cannot mint retry authority from a foreign ID."""
    from topsailai.hooks.configured_runtime import _ExecutionRunners
    runtime, scope = _runtime(tmp_path)
    try:
        runners = _ExecutionRunners(runtime._backend)
        assert runners.cleanup_debts() == ()
        assert runners.retry_cleanup('foreign-record') is False
    finally:
        runtime.close()


def test_cancelled_executor_retains_legacy_not_started_terminal(tmp_path, monkeypatch):
    """Cancellation before real invocation preserves unified and legacy stop facts."""
    import topsailai.hooks.configured_runtime as configured
    from topsailai.tests.unit.test_topsailai_hooks.test_simplified_configured_runtime import (
        _protocol_script, _real_runtime, _real_event,
    )
    script = _protocol_script(tmp_path / 'sources' / 'hook.py', 'never')
    runtime, scope = _real_runtime(tmp_path, (script,))
    signal = threading.Event()
    original = configured.execute_hook_point

    def execute(**kwargs):
        """Cancel after custody binding but before the first child can launch."""
        signal.set()
        return original(**kwargs)

    monkeypatch.setattr(configured, 'execute_hook_point', execute)
    log = tmp_path / 'calls'
    try:
        assert runtime.register_configured('hook_a', scope, scripts=(script,)).accepted
        report = runtime.dispatch_configured('hook_a', _real_event(runtime, scope, log), cancellation=signal)
        assert report.unified_result.handlers[-1].not_run_reason == 'cancelled'
        assert report.outcomes[0].started is False
        assert report.outcomes[0].error_category == 'cancelled'
        assert not log.exists() and runtime.cleanup_debts() == ()
    finally:
        runtime.close()
