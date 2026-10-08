"""Public-runtime harness for bounded Unified Hooks lifecycle behavior."""

from __future__ import annotations

import asyncio
import os
import selectors
import signal
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

from topsailai.hooks import Binding, EventDefinition, HookLimits, HookRuntime, HookSettings

_EVENT_NAME = "bdd.host.lifecycle"
_HANDLER_REF = "bdd_lifecycle_worker:stall"
_STATES = {"timeout", "cancellation", "bounded-close"}
_CLOSE_ELAPSED_LIMIT_SECONDS = 1.0
_SETTLEMENT_LIMIT_SECONDS = 2.0


class UnifiedHooksLifecycleScenario:
    """Own one real-process lifecycle scenario under a B01 temporary directory."""

    def __init__(self, scenario_path: Path, lifecycle_state: str) -> None:
        """Create the public Runtime and deterministic cross-process synchronization."""
        if lifecycle_state not in _STATES:
            raise ValueError(f"unsupported lifecycle_state: {lifecycle_state}")
        self.lifecycle_state = lifecycle_state
        self.runtime_root = scenario_path / "lifecycle-runtime"
        self.worker_ledger = self.runtime_root / "worker-launches.log"
        self.handler_ledger = self.runtime_root / "handler-calls.log"
        self.ready_fifo = self.runtime_root / "ready.fifo"
        self.release_fifo = self.runtime_root / "release.fifo"
        self._ready_fd = -1
        self._release_fd = -1
        self._runtime_path = str(self.runtime_root.resolve())
        self.runtime: HookRuntime | None = None
        self.scope = None
        self.host_markers: list[str] = []
        self.report = None
        self.dispatch_error: BaseException | None = None
        self.cancelled = False
        self.cancellation_elapsed_seconds: float | None = None
        self.worker_alive_after_cancellation = False
        self.worker_released_cooperatively = False
        self.close_report = None
        self.close_elapsed_seconds: float | None = None
        self.second_close_report = None
        self.second_close_elapsed_seconds: float | None = None
        self.later_report = None
        self.diagnostics: tuple[dict[str, object], ...] = ()
        self.observed_workers: tuple[tuple[int, str], ...] = ()
        self._dispatch_thread: threading.Thread | None = None
        self.closed = False
        try:
            self._initialize_runtime()
        except BaseException as initialization_error:
            cleanup_error: BaseException | None = None
            try:
                self.close()
            except BaseException as exc:
                cleanup_error = exc
            if cleanup_error is None:
                raise
            if not isinstance(initialization_error, Exception):
                initialization_error.add_note(
                    f"cleanup also failed: {cleanup_error!r}"
                )
                raise initialization_error
            if not isinstance(cleanup_error, Exception):
                cleanup_error.add_note(
                    f"initialization also failed: {initialization_error!r}"
                )
                raise cleanup_error
            raise ExceptionGroup(
                "lifecycle scenario initialization and cleanup failed",
                (initialization_error, cleanup_error),
            )

    def _initialize_runtime(self) -> None:
        """Initialize owned files, descriptors, imports, and the public Runtime."""
        self.runtime_root.mkdir()
        os.mkfifo(self.ready_fifo, 0o600)
        os.mkfifo(self.release_fifo, 0o600)
        self._ready_fd = os.open(self.ready_fifo, os.O_RDONLY | os.O_NONBLOCK)
        self._release_fd = os.open(self.release_fifo, os.O_RDWR | os.O_NONBLOCK)
        self._write_worker_modules()
        sys.path.insert(0, self._runtime_path)
        timeout_ms = 1_000 if self.lifecycle_state == "timeout" else 5_000
        limits = replace(
            HookLimits(),
            workers=1,
            queue_items=8,
            queue_bytes=65_536,
            handler_timeout_ms=timeout_ms,
            dispatch_timeout_ms=timeout_ms,
            shutdown_timeout_ms=120,
        )
        self.runtime = HookRuntime(HookSettings(limits=limits), temp_root=self._runtime_path)
        self.scope = self.runtime.open_scope(metadata={"owner_id": "bdd-host"})
        self.definition = EventDefinition(
            _EVENT_NAME,
            1,
            {
                "type": "object",
                "properties": {
                    "ready_fifo": {"type": "string"},
                    "release_fifo": {"type": "string"},
                    "handler_ledger": {"type": "string"},
                },
                "required": ["ready_fifo", "release_fifo", "handler_ledger"],
            },
        )
        for binding in self._bindings():
            result = self.runtime.register(self.definition, binding, self.scope)
            if not result.accepted:
                raise RuntimeError(f"BDD lifecycle registration failed: {result.errors}")
        self.event = self.runtime.make_event(
            self.scope,
            _EVENT_NAME,
            1,
            {
                "ready_fifo": str(self.ready_fifo),
                "release_fifo": str(self.release_fifo),
                "handler_ledger": str(self.handler_ledger),
            },
            operation_id="bdd-lifecycle",
            layer="bdd-host",
            purpose=self.lifecycle_state,
        )

    def _write_worker_modules(self) -> None:
        """Write startup and handler observers loaded by real worker processes."""
        startup = f'''import os
from pathlib import Path

if os.environ.get("TOPSAILAI_HOOK_WORKER") == "1":
    fields = Path("/proc/self/stat").read_text(encoding="utf-8").split()
    descriptor = os.open({str(self.worker_ledger)!r}, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, f"{{os.getpid()}}:{{fields[21]}}\\n".encode("utf-8"))
    finally:
        os.close(descriptor)
'''
        handler = '''import os
from pathlib import Path


def stall(context):
    fields = Path("/proc/self/stat").read_text(encoding="utf-8").split()
    identity = f"{os.getpid()}:{fields[21]}"
    descriptor = os.open(context.event.payload["handler_ledger"], os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, f"{context.binding_id},{identity}\\n".encode("utf-8"))
    finally:
        os.close(descriptor)
    ready = os.open(context.event.payload["ready_fifo"], os.O_WRONLY)
    try:
        os.write(ready, b"1")
    finally:
        os.close(ready)
    release = os.open(context.event.payload["release_fifo"], os.O_RDONLY)
    try:
        os.read(release, 1)
    finally:
        os.close(release)
    return {"binding": context.binding_id}
'''
        (self.runtime_root / "sitecustomize.py").write_text(startup, encoding="utf-8")
        (self.runtime_root / "bdd_lifecycle_worker.py").write_text(handler, encoding="utf-8")

    def _bindings(self) -> tuple[Binding, ...]:
        """Return a stalled first binding and a successor that must not start."""
        first = replace(
            Binding("stalled", _EVENT_NAME, 1, _HANDLER_REF),
            priority=10,
            timeout_ms=1_000 if self.lifecycle_state == "timeout" else 5_000,
        )
        successor = replace(
            Binding("successor", _EVENT_NAME, 1, _HANDLER_REF),
            priority=20,
            timeout_ms=5_000,
        )
        return first, successor

    def _wait_ready(self, timeout_seconds: float = 2.0) -> None:
        """Wait on the owned FIFO rather than sleeping for worker readiness."""
        selector = selectors.DefaultSelector()
        try:
            selector.register(self._ready_fd, selectors.EVENT_READ)
            assert selector.select(timeout_seconds), "real worker did not signal readiness"
            assert os.read(self._ready_fd, 1) == b"1"
        finally:
            selector.close()

    def _release_worker(self) -> None:
        """Cooperatively release the exact scenario-owned FIFO stall."""
        if self._release_fd < 0:
            return
        try:
            os.write(self._release_fd, b"1")
        except BrokenPipeError:
            pass

    def run_timeout(self) -> None:
        """Dispatch synchronously and observe the real worker deadline."""
        assert self.runtime is not None
        self.host_markers.append("host-before")
        self.report = self.runtime.dispatch(self.event)
        self.host_markers.append("host-after")

    def _start_thread_dispatch(self) -> None:
        """Start one host dispatch whose ownership remains observable."""
        assert self.runtime is not None

        def dispatch() -> None:
            try:
                self.host_markers.append("host-before")
                self.report = self.runtime.dispatch(self.event)
                self.host_markers.append("host-after")
            except BaseException as exc:
                self.dispatch_error = exc

        self._dispatch_thread = threading.Thread(
            target=dispatch, name="bdd-hook-host-dispatch"
        )
        self._dispatch_thread.start()
        self._wait_ready()

    def run_cancellation(self) -> None:
        """Observe bounded cancellation before cooperatively releasing real work."""
        assert self.runtime is not None

        async def exercise() -> None:
            self.host_markers.append("host-before")
            task = asyncio.create_task(self.runtime.adispatch(self.event))
            await asyncio.to_thread(self._wait_ready)
            started = time.monotonic()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                self.cancelled = True
            self.cancellation_elapsed_seconds = time.monotonic() - started
            self._capture_workers()
            self.worker_alive_after_cancellation = any(
                not self._identity_is_gone(pid, start)
                for pid, start in self.observed_workers
            )
            self.host_markers.append("host-after")
            self._release_worker()
            self.worker_released_cooperatively = True

        asyncio.run(exercise())

    def run_bounded_close(self) -> None:
        """Measure bounded and repeated close around real owned execution."""
        assert self.runtime is not None
        self._start_thread_dispatch()
        started = time.monotonic()
        self.close_report = self.runtime.close(deadline_ms=30)
        self.close_elapsed_seconds = time.monotonic() - started
        self.diagnostics = self.runtime.drain_diagnostics(100)
        started = time.monotonic()
        self.second_close_report = self.runtime.close(deadline_ms=5_000)
        self.second_close_elapsed_seconds = time.monotonic() - started
        self.later_report = self.runtime.dispatch(self.event)
        self._release_worker()
        self._join_dispatch_thread()
        if self.dispatch_error is not None:
            raise self.dispatch_error

    def _join_dispatch_thread(self) -> None:
        """Bound waiting for the exact scenario-owned host dispatch thread."""
        if self._dispatch_thread is None:
            return
        self._dispatch_thread.join(_SETTLEMENT_LIMIT_SECONDS)
        if self._dispatch_thread.is_alive():
            raise AssertionError("scenario-owned dispatch thread did not settle")

    @staticmethod
    def _run_cleanup_steps(*steps) -> None:
        """Attempt every cleanup step while preserving host interruption identity."""
        errors: list[Exception] = []
        interruption: BaseException | None = None
        for step in steps:
            try:
                step()
            except Exception as exc:
                errors.append(exc)
            except BaseException as exc:
                if interruption is None:
                    interruption = exc
                else:
                    interruption.add_note(f"additional host interruption: {exc!r}")
        if interruption is not None:
            for error in errors:
                interruption.add_note(f"cleanup also failed: {error!r}")
            raise interruption
        if errors:
            raise ExceptionGroup("lifecycle scenario cleanup failed", errors)

    def _close_runtime(self) -> None:
        """Close the public Runtime once while retaining its report."""
        if self.runtime is not None and self.close_report is None:
            self.close_report = self.runtime.close()

    def _settle_owned_execution(self) -> None:
        """Settle exact owned execution, escalating only exact live worker identities."""
        initial_failure: BaseException | None = None
        try:
            self._run_cleanup_steps(
                self._close_runtime,
                self._release_worker,
                self._join_dispatch_thread,
                self._capture_workers,
                self._wait_for_workers_gone,
            )
        except BaseException as exc:
            initial_failure = exc
        final_failure: BaseException | None = None
        try:
            self._run_cleanup_steps(
                self._capture_workers,
                self._terminate_observed_workers,
                self._join_dispatch_thread,
                self._assert_owned_execution_settled,
            )
        except BaseException as exc:
            final_failure = exc
        if initial_failure is not None and not isinstance(initial_failure, Exception):
            if final_failure is not None:
                initial_failure.add_note(f"final settlement also failed: {final_failure!r}")
            raise initial_failure
        if final_failure is not None:
            if initial_failure is not None:
                final_failure.add_note(f"initial settlement also failed: {initial_failure!r}")
            raise final_failure
        self.closed = True
        if initial_failure is not None:
            raise initial_failure

    def close_after_settlement(self) -> None:
        """Close publicly, then independently confirm exact worker settlement."""
        if self.runtime is None:
            self._close_local_resources()
            return
        self._run_cleanup_steps(
            self._settle_owned_execution,
            self._close_local_resources,
        )

    @staticmethod
    def _read_lines(path: Path) -> list[str]:
        """Read an optional scenario-owned ledger."""
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def _capture_workers(self) -> None:
        """Capture exact observed Linux process identities."""
        records = []
        for identity in self._read_lines(self.worker_ledger):
            pid_text, start_time = identity.split(":", 1)
            records.append((int(pid_text), start_time))
        self.observed_workers = tuple(records)

    @staticmethod
    def _identity_is_gone(pid: int, start_time: str) -> bool:
        """Return whether one exact observed process identity has exited."""
        try:
            fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()
        except FileNotFoundError:
            return True
        return fields[21] != start_time

    def _wait_for_workers_gone(self) -> None:
        """Bound exact process-identity observation after public closure."""
        deadline = time.monotonic() + _SETTLEMENT_LIMIT_SECONDS
        while not all(
            self._identity_is_gone(pid, start) for pid, start in self.observed_workers
        ):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError("observed worker process did not exit")
            threading.Event().wait(min(remaining, 0.01))

    @staticmethod
    def _open_verified_worker_pidfd(pid: int, start_time: str) -> int | None:
        """Open a stable handle and verify that its numeric PID retains ownership."""
        if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
            raise RuntimeError("safe pidfd worker signaling is unavailable")
        try:
            descriptor = os.pidfd_open(pid, 0)
        except ProcessLookupError:
            return None
        try:
            fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()
            if fields[21] != start_time:
                raise AssertionError("observed worker identity changed before signaling")
            return descriptor
        except FileNotFoundError:
            os.close(descriptor)
            return None
        except BaseException:
            os.close(descriptor)
            raise

    def _signal_observed_workers(self, signal_number: int) -> None:
        """Signal verified workers only through stable Linux process handles."""
        for pid, start_time in self.observed_workers:
            descriptor = self._open_verified_worker_pidfd(pid, start_time)
            if descriptor is None:
                continue
            try:
                signal.pidfd_send_signal(descriptor, signal_number, None, 0)
            except ProcessLookupError:
                continue
            finally:
                os.close(descriptor)

    def _terminate_observed_workers(self) -> None:
        """Bound cooperative settlement, then escalate exact owned worker PIDs."""
        if all(
            self._identity_is_gone(pid, start) for pid, start in self.observed_workers
        ):
            return
        self._signal_observed_workers(signal.SIGTERM)
        try:
            self._wait_for_workers_gone()
            return
        except AssertionError:
            pass
        self._signal_observed_workers(signal.SIGKILL)
        self._wait_for_workers_gone()

    def _assert_owned_execution_settled(self) -> None:
        """Require both exact host thread and observed worker identities to be gone."""
        if self._dispatch_thread is not None and self._dispatch_thread.is_alive():
            raise AssertionError("scenario-owned dispatch thread remains alive")
        if not all(
            self._identity_is_gone(pid, start) for pid, start in self.observed_workers
        ):
            raise AssertionError("observed worker process remains alive")

    def assert_timeout(self) -> None:
        """Assert timeout and non-start of the later binding."""
        assert self.host_markers == ["host-before", "host-after"]
        assert self.report is not None
        actual = tuple(
            (item.binding_id, item.status.value, item.error_category, item.started)
            for item in self.report.outcomes
        )
        assert actual == (
            ("stalled", "timeout", "deadline", True),
            ("successor", "skipped_deadline", "deadline", False),
        )
        assert self.report.deadline_exhausted
        self._assert_one_stalled_call()

    def assert_cancellation(self) -> None:
        """Assert bounded propagation while real work remained until release."""
        assert self.cancelled
        assert self.cancellation_elapsed_seconds is not None
        assert self.cancellation_elapsed_seconds < _CLOSE_ELAPSED_LIMIT_SECONDS
        assert self.worker_alive_after_cancellation
        assert self.worker_released_cooperatively
        assert self.host_markers == ["host-before", "host-after"]
        self._assert_one_stalled_call()

    def _assert_one_stalled_call(self) -> None:
        """Assert one real worker start and one first-handler invocation."""
        workers = self._read_lines(self.worker_ledger)
        handlers = self._read_lines(self.handler_ledger)
        assert len(workers) == 1
        assert len(set(workers)) == 1
        assert len(handlers) == 1
        binding_id, identity = handlers[0].split(",", 1)
        assert binding_id == "stalled"
        assert identity == workers[0]

    def assert_bounded_close(self) -> None:
        """Assert measured close bounds and public diagnostics."""
        assert self.close_report is not None
        assert self.close_elapsed_seconds is not None
        assert self.close_elapsed_seconds < _CLOSE_ELAPSED_LIMIT_SECONDS
        assert any(item.get("kind") == "shutdown_debt" for item in self.diagnostics)
        assert self.scope is not None
        assert self.scope.scope_id in self.close_report.closed_scope_ids
        assert self.second_close_report is not None
        assert self.second_close_report.already_closed
        assert self.second_close_elapsed_seconds is not None
        assert self.second_close_elapsed_seconds < _CLOSE_ELAPSED_LIMIT_SECONDS
        assert self.later_report is not None
        assert self.later_report.rejection_reason == "closed"

    def assert_original_settled(self) -> None:
        """Assert close did not start the successor and host flow completed."""
        assert self.host_markers == ["host-before", "host-after"]
        assert self.report is not None
        assert tuple(item.binding_id for item in self.report.outcomes) == (
            "stalled",
            "successor",
        )
        assert self.report.outcomes[0].status.value == "cancelled"
        assert self.report.outcomes[1].status.value == "cancelled"
        assert not self.report.outcomes[1].started
        self._assert_one_stalled_call()

    def assert_closed(self) -> None:
        """Assert public closure and independently observed process exit."""
        assert self.closed
        assert self.close_report is not None
        assert self.scope is not None
        assert self.scope.closed
        assert self.close_report.cleanup_debts == ()
        assert self.runtime is not None
        assert self.runtime.cleanup_debts() == ()
        assert all(
            self._identity_is_gone(pid, start) for pid, start in self.observed_workers
        )

    def _close_descriptor(self, descriptor_name: str) -> None:
        """Close one owned descriptor without leaving it eligible for a retry."""
        descriptor = getattr(self, descriptor_name, -1)
        if descriptor < 0:
            return
        setattr(self, descriptor_name, -1)
        os.close(descriptor)

    def _remove_runtime_path(self) -> None:
        """Remove only this scenario's import-path entry."""
        if self._runtime_path in sys.path:
            sys.path.remove(self._runtime_path)

    def _close_local_resources(self) -> None:
        """Best-effort close every local resource and retain ordinary failures."""
        self._run_cleanup_steps(
            lambda: self._close_descriptor("_ready_fd"),
            lambda: self._close_descriptor("_release_fd"),
            self._remove_runtime_path,
        )

    def close(self) -> None:
        """Attempt all bounded settlement and local cleanup phases."""
        if self.closed:
            self._close_local_resources()
            return
        self._run_cleanup_steps(
            self._settle_owned_execution,
            self._close_local_resources,
        )
