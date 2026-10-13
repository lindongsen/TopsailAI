"""RED regressions for bounded asynchronous Hooks dispatch ownership."""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from topsailai.tests.unit.test_topsailai_hooks.red_runtime_helpers import (
    BlockingBackend,
    binding,
    definition,
    event,
    runtime_and_scope,
)


async def _wait_for_queue(runtime: Any, items: int, timeout: float = 1.0) -> None:
    """Observe scheduler reservation under its real condition lock."""
    def wait() -> bool:
        deadline = time.monotonic() + timeout
        with runtime._scheduler._changed:
            while runtime._scheduler._queued_items != items:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                runtime._scheduler._changed.wait(min(remaining, 0.02))
            return True

    assert await asyncio.to_thread(wait), f"queue never reached {items} reserved item(s)"


async def _cleanup_exercise(
    runtime: Any,
    backend: BlockingBackend,
    tasks: list[asyncio.Task[Any]],
    *,
    closer: threading.Thread | None = None,
    allow_cancelled: bool = False,
) -> None:
    """Run every owned cleanup phase and aggregate independent failures."""
    failures: list[str] = []
    backend.release.set()

    done, pending = await asyncio.wait(tasks, timeout=1.0) if tasks else (set(), set())
    if pending:
        failures.append(f"owned tasks did not settle: {len(pending)}")
    for task in done:
        if task.cancelled():
            if not allow_cancelled:
                failures.append("owned task was unexpectedly cancelled")
            continue
        exception = task.exception()
        if exception is not None:
            failures.append(f"owned task failed: {exception!r}")

    if backend.started.is_set() and not await asyncio.to_thread(backend.wait_idle, 1):
        failures.append("backend remained active after release")
    started, active, completed = backend.snapshot()
    if active != 0:
        failures.append(f"backend active count remained {active}")
    if completed != started:
        failures.append(
            f"backend completion mismatch: started={started}, completed={completed}"
        )

    if closer is not None and closer.ident is not None:
        closer.join(1)
        if closer.is_alive():
            failures.append("closer thread did not terminate")

    with runtime._scheduler._lock:
        if runtime._scheduler._work:
            failures.append("scheduler ownership did not reach zero")
        if runtime._scheduler._queued_items != 0:
            failures.append("queue item reservations did not reach zero")
        if runtime._scheduler._queued_bytes != 0:
            failures.append("queue byte reservations did not reach zero")
    assert failures == []


def test_adispatch_uses_bounded_queue_item_admission(tmp_path: Path) -> None:
    """Async dispatch must queue one waiter and reject the next item overflow."""
    backend = BlockingBackend()
    runtime, scope = runtime_and_scope(
        tmp_path, backend=backend, queue_items=1, queue_bytes=65_536
    )
    assert runtime.register(definition(), binding(), scope).accepted

    async def exercise() -> None:
        tasks: list[asyncio.Task[Any]] = []
        try:
            first = asyncio.create_task(runtime.adispatch(event(runtime, scope, 1)))
            tasks.append(first)
            assert await asyncio.to_thread(backend.started.wait, 1)
            second = asyncio.create_task(runtime.adispatch(event(runtime, scope, 2)))
            tasks.append(second)
            await _wait_for_queue(runtime, 1)
            third = await runtime.adispatch(event(runtime, scope, 3))
            assert third.rejection_reason == "rejected_capacity"
        finally:
            await _cleanup_exercise(runtime, backend, tasks)

    try:
        asyncio.run(exercise())
    finally:
        backend.release.set()
        runtime.close(deadline_ms=100)


def test_adispatch_uses_bounded_queue_byte_admission(tmp_path: Path) -> None:
    """Async dispatch must reject byte overflow independently of item capacity."""
    backend = BlockingBackend()
    runtime, scope = runtime_and_scope(
        tmp_path, backend=backend, queue_items=8, queue_bytes=512
    )
    assert runtime.register(definition(), binding(), scope).accepted

    async def exercise() -> None:
        tasks: list[asyncio.Task[Any]] = []
        second_size = 0
        try:
            first = asyncio.create_task(runtime.adispatch(event(runtime, scope, 1)))
            tasks.append(first)
            assert await asyncio.to_thread(backend.started.wait, 1)
            second_event = event(runtime, scope, 2)
            admission, rejection = runtime._prepare_admission(second_event, None)
            assert rejection is None and admission is not None
            second_size = admission.size_bytes
            assert second_size <= 512 < second_size * 2
            second = asyncio.create_task(runtime.adispatch(second_event))
            tasks.append(second)
            await _wait_for_queue(runtime, 1)
            with runtime._scheduler._lock:
                assert runtime._scheduler._queued_bytes == second_size
            overflow = await runtime.adispatch(event(runtime, scope, 3))
            assert overflow.rejection_reason == "rejected_capacity"
        finally:
            await _cleanup_exercise(runtime, backend, tasks)

    try:
        asyncio.run(exercise())
    finally:
        backend.release.set()
        runtime.close(deadline_ms=100)


def test_close_retains_observable_adispatch_ownership_until_settlement(tmp_path: Path) -> None:
    """A bounded close must retain blocked async work as pending ownership."""
    backend = BlockingBackend()
    runtime, scope = runtime_and_scope(tmp_path, backend=backend, shutdown_timeout_ms=30)
    assert runtime.register(definition(), binding(), scope).accepted
    close_returned = threading.Event()
    close_errors: list[BaseException] = []
    closer: threading.Thread | None = None

    async def exercise() -> None:
        nonlocal closer
        task = asyncio.create_task(runtime.adispatch(event(runtime, scope)))
        try:
            assert await asyncio.to_thread(backend.started.wait, 1)

            def close() -> None:
                """Capture close failure without losing the owned thread."""
                try:
                    runtime.close(deadline_ms=30)
                except BaseException as exc:
                    close_errors.append(exc)
                finally:
                    close_returned.set()

            closer = threading.Thread(target=close)
            closer.start()
            assert await asyncio.to_thread(close_returned.wait, 1)
            assert runtime._scheduler._work, "close forgot blocked adispatch ownership"
            assert any(
                record.get("kind") == "shutdown_debt"
                for record in runtime.drain_diagnostics(50)
            )
        finally:
            await _cleanup_exercise(runtime, backend, [task], closer=closer)
            assert close_errors == []

    try:
        asyncio.run(exercise())
    finally:
        backend.release.set()
        if closer is not None and closer.ident is not None:
            closer.join(1)
        runtime.close(deadline_ms=100)


def test_queued_adispatch_expires_without_late_backend_start(tmp_path: Path) -> None:
    """A proven queued deadline must release capacity and never start late."""
    backend = BlockingBackend()
    runtime, scope = runtime_and_scope(tmp_path, backend=backend, dispatch_timeout_ms=500)
    assert runtime.register(definition(), binding(), scope).accepted

    async def exercise() -> None:
        tasks: list[asyncio.Task[Any]] = []
        try:
            first = asyncio.create_task(runtime.adispatch(event(runtime, scope, 1)))
            tasks.append(first)
            assert await asyncio.to_thread(backend.started.wait, 1)
            second = asyncio.create_task(
                runtime.adispatch(event(runtime, scope, 2), {"timeout_ms": 60})
            )
            tasks.append(second)
            await _wait_for_queue(runtime, 1)
            assert backend.calls == 1
            await asyncio.sleep(0.02)
            assert backend.calls == 1
            report = await asyncio.wait_for(asyncio.shield(second), 0.5)
            assert report.outcomes[0].status.value == "skipped_deadline"
            assert runtime._scheduler._queued_items == 0
            assert runtime._scheduler._queued_bytes == 0
            backend.release.set()
            await asyncio.wait_for(asyncio.shield(first), 0.5)
            assert not backend.second_started.wait(0.05)
            assert backend.calls == 1
        finally:
            await _cleanup_exercise(runtime, backend, tasks)

    try:
        asyncio.run(exercise())
    finally:
        backend.release.set()
        runtime.close(deadline_ms=100)


def test_repeated_cancellation_retains_observable_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repeated cancellation must not forget blocked backend ownership."""
    backend = BlockingBackend()
    runtime, scope = runtime_and_scope(
        tmp_path, backend=backend, dispatch_timeout_ms=1_000, shutdown_timeout_ms=200
    )
    assert runtime.register(definition(), binding(), scope).accepted
    settlement_started = threading.Event()
    original_publish = runtime._diagnostics.publish

    def observe_publish(kind: str, **fields: object) -> None:
        """Observe the existing first-cancellation settlement checkpoint."""
        original_publish(kind, **fields)
        if kind == "dispatch_cancel_requested":
            settlement_started.set()

    monkeypatch.setattr(runtime._diagnostics, "publish", observe_publish)

    async def exercise() -> None:
        task = asyncio.create_task(runtime.adispatch(event(runtime, scope)))
        try:
            assert await asyncio.to_thread(backend.started.wait, 1)
            task.cancel()
            assert await asyncio.to_thread(settlement_started.wait, 1)
            task.cancel()
            done, pending = await asyncio.wait({task}, timeout=0.4)
            assert done == {task}, "cancellation exceeded the loose anti-hang bound"
            assert pending == set()
            with pytest.raises(asyncio.CancelledError):
                task.result()
            assert runtime._scheduler._work, "bounded cancellation forgot pending work"
            _, active, _ = backend.snapshot()
            assert active == 1, "bounded return did not retain backend ownership"
        finally:
            await _cleanup_exercise(
                runtime, backend, [task], allow_cancelled=True
            )
            started, active, completed = backend.snapshot()
            assert (started, active, completed) == (1, 0, 1)

    try:
        asyncio.run(exercise())
    finally:
        backend.release.set()
        runtime.close(deadline_ms=100)


@pytest.mark.parametrize("repeated", [False, True])
def test_configured_async_cancellation_signals_owned_work(tmp_path, monkeypatch, repeated):
    """Cancellation reaches the exact scheduler work before releasing its reader."""
    from topsailai.tests.unit.test_topsailai_hooks.test_simplified_configured_runtime import _runtime, _event
    import topsailai.hooks.configured_runtime as configured
    runtime, scope = _runtime(tmp_path)
    started = threading.Event()
    release = threading.Event()
    observed = []
    original = configured._execute_configured

    def execute(owner, admission):
        """Pause with the real reader retained and observe its exact signal."""
        observed.append(admission)
        started.set()
        assert release.wait(2)
        return original(owner, admission)

    monkeypatch.setattr(configured, "_execute_configured", execute)
    async def exercise():
        """Leave cancellation pending while verifying host-loop progress."""
        task = asyncio.create_task(runtime.adispatch_configured("hook_before_chat", _event(runtime, scope)))
        try:
            assert await asyncio.to_thread(started.wait, 1)
            task.cancel()
            await asyncio.sleep(.01)
            assert observed[0].cancellation.is_set()
            assert not observed[0].released
            if repeated:
                task.cancel()
                await asyncio.sleep(.01)
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert observed[0].released
            assert not runtime._scheduler._work
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
    try:
        assert runtime.register_configured("hook_before_chat", scope, scripts=[]).accepted
        asyncio.run(exercise())
    finally:
        release.set()
        runtime.close()


@pytest.mark.parametrize("invalid_signal", [False, True])
def test_configured_async_rejection(tmp_path, invalid_signal):
    """Invalid cancellation and unknown plans never allocate execution resources."""
    from topsailai.tests.unit.test_topsailai_hooks.test_simplified_configured_runtime import _runtime, _event
    runtime, scope = _runtime(tmp_path)
    async def exercise():
        """Exercise both pre-admission error boundaries."""
        if invalid_signal:
            with pytest.raises(ValueError, match="invalid cancellation"):
                await runtime.adispatch_configured("hook_unknown", _event(runtime, scope), cancellation=object())
        else:
            report = await runtime.adispatch_configured("hook_unknown", _event(runtime, scope))
            assert report.rejection_reason == "unknown_configured_hook"
        assert not runtime._scheduler._work
    try:
        asyncio.run(exercise())
    finally:
        runtime.close()


def test_configured_async_real_child_cancellation(tmp_path, monkeypatch):
    """Host cancellation terminates the exact owned child and settles reader custody."""
    import sys
    from topsailai.tests.unit.test_topsailai_hooks.test_simplified_configured_runtime import (
        _real_runtime, _real_event,
    )
    source_root = tmp_path / "sources"
    source_root.mkdir(mode=0o700)
    script = source_root / "sleeper"
    script.write_text("#!" + str(Path(sys.executable).resolve()) + "\nimport time\ntime.sleep(20)\n")
    script.chmod(0o700)
    runtime, scope = _real_runtime(tmp_path, (script,))
    processes = []
    started = threading.Event()
    launch = runtime._backend.launch_script
    def observe(*args, **kwargs):
        """Observe published Script process without transferring its armed lease."""
        lease = launch(*args, **kwargs)
        process = kwargs["record"].process
        assert process is not None
        processes.append(process)
        started.set()
        return lease
    monkeypatch.setattr(runtime._backend, "launch_script", observe)
    async def exercise():
        """Cancel only the task that owns this captured execution."""
        task = asyncio.create_task(runtime.adispatch_configured("hook_before_chat", _real_event(runtime, scope, tmp_path)))
        observed = await asyncio.to_thread(started.wait, 1)
        if not observed:
            outcome = await task
            pytest.fail(f"Script child was not observed: {outcome!r}")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert processes and all(process.poll() is not None for process in processes)
        assert not runtime._scheduler._work
        assert not runtime.cleanup_debts()
    try:
        registration = runtime.register_configured("hook_before_chat", scope, scripts=[script])
        assert registration.accepted, registration
        asyncio.run(exercise())
    finally:
        runtime.close()


def test_configured_async_expired_absolute_deadline(tmp_path, monkeypatch):
    """An expired caller budget cannot restart at configured async admission."""
    from topsailai.tests.unit.test_topsailai_hooks.test_simplified_configured_runtime import _runtime, _event
    import topsailai.hooks.configured_runtime as configured
    runtime, scope = _runtime(tmp_path)
    executed = []
    def execute(*args, **kwargs):
        """Reject business Script execution after the supplied budget expired."""
        executed.append(True)
        pytest.fail("Script execution reached after absolute deadline")
    monkeypatch.setattr(configured, "execute_configured_hook_script", execute)
    async def exercise():
        """Observe terminal deadline and exact scheduler ownership convergence."""
        report = await runtime.adispatch_configured(
            "hook_before_chat", _event(runtime, scope), deadline=time.monotonic() - 1)
        if report.unified_result is None:
            assert report.rejection_reason == "deadline", report
            assert report.deadline_exhausted, report
        else:
            assert report.rejection_reason is None, report
            result = report.unified_result
            assert result.status == "timeout", report
            assert report.deadline_exhausted, report
            assert result.handlers, report
            assert all(handler.status == "not_run" and handler.not_run_reason == "deadline"
                       for handler in result.handlers), report
            assert result.cleanup.state == "safe", report
        assert not executed
        assert not runtime._scheduler._work
        assert not runtime.cleanup_debts()
    try:
        assert runtime.register_configured("hook_before_chat", scope, scripts=[]).accepted
        asyncio.run(exercise())
    finally:
        runtime.close()
