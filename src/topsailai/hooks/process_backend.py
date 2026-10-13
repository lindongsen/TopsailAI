"""Platform-qualified supervision for one isolated hook delivery."""

from __future__ import annotations

import os
import selectors
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from typing import Any

from topsailai.hooks.cleanup_backend_profile import CleanupBackendProfileMixin
from topsailai.hooks.contracts import HookContext, JsonValue, ValidationError
from topsailai.hooks.process_cleanup import ProcessCleanupMixin
from topsailai.hooks.process_execution import ProcessExecutionMixin
from topsailai.hooks.process_launch import build_script_environment
from topsailai.hooks.process_setup import ProcessSetupMixin
from topsailai.hooks.process_state import (
    CleanupDebt,
    DebtEntry as _DebtEntry,
    LaunchRecord as _LaunchRecord,
    WorkerResult,
)
from topsailai.hooks.process_termination import terminate_unpublished_process
from topsailai.hooks.worker_protocol import (
    ProtocolLimits,
    expected_frame_size,
    validate_response,
)


class _LaunchLease:
    """Keep the sole authoritative cleanup state from launch through completion."""

    def __init__(self, backend: "IsolatedProcessBackend", record: _LaunchRecord) -> None:
        self._backend = backend
        self._record = record

    def resources(self) -> tuple[subprocess.Popen[bytes], int]:
        """Return borrowed resources without transferring cleanup authority."""
        with self._record.condition:
            if self._record.process is None or self._record.result_fd is None:
                raise RuntimeError("launch resources are unavailable")
            return self._record.process, self._record.result_fd

    def release_to_caller(self) -> None:
        """Mark handoff without moving resources out of the authoritative record."""
        with self._record.condition:
            if self._record.process is None or self._record.result_fd is None:
                raise RuntimeError("launch resources are unavailable")
            self._record.state = "received"

    def finish(
        self,
        status: str,
        buffers: dict[str, bytearray],
        dropped: dict[str, int],
        error_category: Any = None,
        value: Any = None,
        **metadata: Any,
    ) -> WorkerResult:
        """Complete or resume the one cleanup transaction and build its result."""
        return self._backend._finish_record(
            self._record, status, buffers, dropped, error_category, value, **metadata
        )

    def close_after_finish(self) -> None:
        """Resume protected channel closure without repeating process termination."""
        with self._backend._cleanup_execution_lease(self._record) as lease:
            if lease is None:
                raise RuntimeError("cleanup transaction is already active")
            self._backend._close_record_channels(self._record)

    def cleanup(self) -> None:
        """Complete launch cleanup while preserving state before propagating interrupts."""
        empty = {"stdout": bytearray(), "stderr": bytearray()}
        dropped = {"stdout": 0, "stderr": 0}
        self._backend._finish_record(
            self._record, "worker_lost", empty, dropped, "host_interrupted"
        )

class IsolatedProcessBackend(CleanupBackendProfileMixin, ProcessSetupMixin, ProcessCleanupMixin, ProcessExecutionMixin):
    """Execute each handler in a fresh, owned Linux process group."""

    def __init__(
        self,
        *,
        temp_root: str,
        protocol_limits: ProtocolLimits = ProtocolLimits(),
        output_limit_bytes: int = 16_384,
        cleanup_grace_ms: int = 100,
        interpreter: str | None = None,
        worker_module: str = "topsailai.hooks.worker",
        cleanup_profile: str = "legacy",
    ) -> None:
        """Configure explicit finite process, protocol, output, and cleanup limits."""
        self._initialize_cleanup_profile(cleanup_profile)
        if type(temp_root) is not str or not os.path.isabs(temp_root):
            raise ValueError("temp_root must be an absolute path")
        if type(output_limit_bytes) is not int or output_limit_bytes < 0:
            raise ValueError("output_limit_bytes must be a non-negative integer")
        if type(cleanup_grace_ms) is not int or cleanup_grace_ms <= 0:
            raise ValueError("cleanup_grace_ms must be a positive integer")
        self._temp_root = temp_root
        self._limits = protocol_limits
        self._output_limit = output_limit_bytes
        self._cleanup_grace = cleanup_grace_ms / 1_000
        self._interpreter = interpreter
        self._worker_module = worker_module
        self._debt_lock = threading.Lock()
        self._debts: dict[str, CleanupDebt] = {}
        self._debt_processes: dict[str, _DebtEntry] = {}
        self._launch_debt_records: dict[str, _LaunchRecord] = {}

    @property
    def script_temp_root(self) -> str:
        """Expose the host-owned root to admission-scoped script storage owners."""
        self._require_legacy_cleanup_profile()
        return self._temp_root

    def cleanup_debts(self) -> tuple[CleanupDebt, ...]:
        """Return a stable snapshot of cleanup obligations not yet confirmed settled."""
        self._require_legacy_cleanup_profile()
        with self._debt_lock:
            return tuple(self._debts[key] for key in sorted(self._debts))

    def cleanup_debts_for_record(self, record: _LaunchRecord) -> tuple[CleanupDebt, ...]:
        """Query only the debt still owned by this exact launch record."""
        self._require_legacy_cleanup_profile()
        with self._debt_lock:
            entry = self._debt_processes.get(record.debt_id)
            owner = self._launch_debt_records.get(record.debt_id) if entry is None else entry.record
            if owner is not record:
                return ()
            debt = self._debts.get(record.debt_id)
            return () if debt is None else (debt,)

    def retry_cleanup(self, debt_id: str, *, record: _LaunchRecord | None = None) -> bool:
        """Independently retry process and channel cleanup under one exact lease."""
        self._require_legacy_cleanup_profile()
        entry: _DebtEntry | None = None
        debt_restore_required = False
        try:
            with self._debt_lock:
                entry = self._debt_processes.get(debt_id)
                if record is not None and (record.debt_id != debt_id or (
                        entry is not None and entry.record is not record)):
                    return False
                if entry is None:
                    return debt_id not in self._debts
                if entry.state != "pending":
                    return False
                debt_restore_required = True
                entry.state = "cleaning"
                self._after_cleanup_debt_claimed(entry)
            with self._cleanup_execution_lease(entry.record) as lease:
                if lease is None:
                    return False
                confirmed = entry.record.cleanup.termination_confirmed
                ordinary_errors: list[Exception] = []
                interruptions: list[BaseException] = []
                try:
                    if not confirmed and entry.process is not None:
                        confirmed = self._terminate_record(entry.record, entry.process)
                        if confirmed:
                            entry.record.cleanup.termination_confirmed = True
                except BaseException as exc:
                    self._retain_cleanup_error(exc, ordinary_errors, interruptions)
                try:
                    self._close_record_channels(entry.record)
                except BaseException as exc:
                    self._retain_cleanup_error(exc, ordinary_errors, interruptions)
                closed = self._record_channels_closed(entry.record)
                if confirmed and closed:
                    self._resolve_debt(debt_id, entry.record)
                self._raise_cleanup_errors(ordinary_errors, interruptions)
                return confirmed and closed
        finally:
            if debt_restore_required and entry is not None:
                with self._debt_lock:
                    current = self._debt_processes.get(debt_id)
                    if current is entry and entry.state == "cleaning":
                        entry.state = "pending"

    def _after_cleanup_debt_claimed(self, entry: _DebtEntry) -> None:
        """Provide a deterministic seam after the first debt-state mutation."""

    def execute(self, handler_ref: str, context: HookContext, timeout_ms: int) -> WorkerResult:
        """Execute the unchanged legacy context handler protocol."""
        return self._execute_delivery(handler_ref, context, timeout_ms)

    def execute_module(self, handler_ref: str, context: HookContext, timeout_ms: int,
                       *, args=(), kwargs=None) -> WorkerResult:
        """Execute safe explicit Module arguments only in an owned child process."""
        return self._execute_delivery(handler_ref, context, timeout_ms,
                                      module=True, args=args, kwargs=kwargs)

    def execute_captured_module(self, module, context: HookContext, timeout_ms: int,
                                *, record_receiver=None, deadline=None, cancellation=None) -> WorkerResult:
        """Invoke a detached captured record using the existing process cleanup lease."""
        from topsailai.hooks.hook_point_plan_contracts import CapturedModule
        from topsailai.hooks.captured_module_protocol import CapturedModuleLocator
        if type(module) is not CapturedModule:
            return WorkerResult("invalid_request", error_category="invalid_request")
        locator = CapturedModuleLocator(str(module.captured_path), module.source.logical_name,
                                        module.source.kind, module.content_sha256)
        from topsailai.hooks.contracts import _thaw_frozen_json
        return self._execute_delivery(
            module.source.handler_ref, context, timeout_ms, module=True,
            args=_thaw_frozen_json(module.invocation.args),
            kwargs=_thaw_frozen_json(module.invocation.kwargs), captured=locator,
            inject_hook_context=module.invocation.inject_hook_context,
            record_receiver=record_receiver, deadline=deadline, cancellation=cancellation,
        )

    def _preflight(self, timeout_ms: int) -> WorkerResult | None:
        """Reject platforms outside the currently verified Linux capability scope."""
        rejection = self._profile_rejection()
        if rejection is not None:
            return rejection
        if (
            os.name != "posix"
            or not sys.platform.startswith("linux")
            or not hasattr(os, "killpg")
            or not hasattr(os, "set_blocking")
        ):
            return WorkerResult(
                "unsupported_backend", error_category="unsupported_platform", cleanup_confirmed=True
            )
        if type(timeout_ms) is not int or timeout_ms <= 0:
            return WorkerResult("invalid_request", error_category="invalid_timeout")
        return None

    def _validate_terminal(self, response: Any, **expected: str) -> dict[str, JsonValue]:
        """Validate a terminal response through an observable test seam."""
        return validate_response(response, **expected)

    def _execution_stop(self, deadline, cancellation):
        """Give local cancellation precedence over the unchanged absolute deadline."""
        if cancellation is not None and cancellation.is_set():
            return "cancelled"
        if time.monotonic() >= deadline:
            return "timeout"
        return None

    def _deadline_expired(self, deadline: float) -> bool:
        """Check terminal acceptance against the absolute monotonic deadline."""
        return time.monotonic() >= deadline

    def _resolve_interpreter(self) -> str | None:
        """Resolve only a validated Python interpreter executable."""
        candidates = [self._interpreter] if self._interpreter is not None else []
        if self._interpreter is None:
            candidates.extend((getattr(sys, "executable", ""), getattr(sys, "_base_executable", "")))
            candidates.extend((shutil.which("python3"), shutil.which("python")))
        for candidate in candidates:
            if not candidate:
                continue
            path = os.path.realpath(candidate)
            if os.path.isfile(path) and os.access(path, os.X_OK) and os.path.basename(path).lower().startswith(
                "python"
            ):
                return path
        return None

    def _spawn(
        self, interpreter: str, deadline: float, record: _LaunchRecord
    ) -> _LaunchLease | WorkerResult:
        """Publish resources under a lease that remains armed across return."""
        rejection = self._profile_rejection()
        if rejection is not None:
            return rejection

        def launch() -> None:
            result_read: int | None = None
            result_write: int | None = None
            process: subprocess.Popen[bytes] | None = None
            try:
                result_read, result_write = os.pipe()
                process = subprocess.Popen(
                    [
                        interpreter,
                        "-m",
                        self._worker_module,
                        "--result-fd",
                        str(result_write),
                        "--request-limit",
                        str(self._limits.request_bytes),
                        "--response-limit",
                        str(self._limits.response_bytes),
                    ],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=self._temp_root,
                    env=self._worker_environment(),
                    pass_fds=(result_write,),
                    start_new_session=True,
                    bufsize=0,
                )
                self._safe_close_fd(result_write)
                result_write = None
                self._before_publish_process(record)
                with record.condition:
                    record.process = process
                    record.result_fd = result_read
                    result_read = None
                    if record.state == "abandoned":
                        owns_cleanup = True
                    else:
                        record.state = "published"
                        record.condition.notify_all()
                        owns_cleanup = False
                if owns_cleanup:
                    self._cleanup_launch_record(record, "late_launch_cleanup")
            except BaseException as exc:
                if process is not None:
                    with record.condition:
                        if record.process is None:
                            record.process = process
                            record.result_fd = result_read
                            result_read = None
                    try:
                        self._cleanup_launch_record(record, "launch_exception_cleanup")
                    except BaseException:
                        pass
                self._safe_close_fd(result_read)
                self._safe_close_fd(result_write)
                with record.condition:
                    if record.state == "abandoned":
                        if process is None:
                            self._resolve_debt(record.debt_id, record)
                        return
                    record.error = exc
                    if process is None:
                        record.cleanup.termination_confirmed = True
                        for channel in record.cleanup.channels.values():
                            channel.state = "closed"
                    record.cleanup_confirmed = (
                        record.cleanup.termination_confirmed
                        and self._record_channels_closed(record)
                    )
                    record.cleanup_debt = (
                        None if record.cleanup_confirmed else record.debt_id
                    )
                    record.state = "failed"
                    record.condition.notify_all()

        stop = self._execution_stop(deadline, record.cancellation)
        if stop is not None:
            with record.condition:
                record.state = "failed"
                record.cleanup.termination_confirmed = True
                for channel in record.cleanup.channels.values():
                    channel.state = "closed"
                record.condition.notify_all()
            return WorkerResult(stop, error_category=stop)
        thread = threading.Thread(target=launch, name="hook-worker-launch", daemon=True)
        try:
            thread.start()
            self._after_launch_thread_start(record)
            with record.condition:
                while record.state == "launching":
                    remaining = deadline - time.monotonic()
                    stop = self._execution_stop(deadline, record.cancellation)
                    if stop is not None:
                        record.state = "abandoned"
                        self._record_launch_debt(record.debt_id, record)
                        return WorkerResult(
                            stop,
                            error_category="startup_timeout" if stop == "timeout" else "cancelled",
                            cleanup_confirmed=False,
                            cleanup_debt=record.debt_id,
                        )
                    self._wait_for_launch(record, min(remaining, 0.05) if record.cancellation is not None else remaining)
                if record.state == "failed":
                    return WorkerResult(
                        "worker_lost",
                        error_category="startup_failure",
                        cleanup_confirmed=record.cleanup_confirmed,
                        cleanup_debt=record.cleanup_debt,
                    )
                if record.process is None or record.result_fd is None:
                    return WorkerResult("worker_lost", error_category="startup_failure")
                self._after_launch_published(record)
                return _LaunchLease(self, record)
        except BaseException:
            self._abandon_launch(record)
            raise

    def launch_script(
        self,
        *,
        argv: tuple[str, ...],
        cwd: str,
        environment: dict[str, str],
        argument_environment_limit_bytes: int,
        deadline: float,
        record: _LaunchRecord,
    ) -> _LaunchLease | WorkerResult:
        """Launch one literal script under the backend's armed ownership handoff."""
        rejection = self._profile_rejection()
        if rejection is not None:
            return rejection

        def launch() -> None:
            process: subprocess.Popen[bytes] | None = None
            try:
                result_read, result_write = os.pipe()
                self._adopt_setup_pipe(record, result_read, result_write)
                child_environment = build_script_environment(
                    argv,
                    environment,
                    result_write,
                    argument_environment_limit_bytes,
                )
                if child_environment is None:
                    raise ValueError("script argument/environment limit exceeded")
                process = subprocess.Popen(
                    argv,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=cwd,
                    env=child_environment,
                    close_fds=True,
                    pass_fds=(result_write,),
                    start_new_session=True,
                    bufsize=0,
                )
                self._close_setup_channel(record, "result_write")
                if record.cleanup.setup_channels["result_write"].state != "closed":
                    raise OSError("parent result write descriptor close is unconfirmed")
                record.group_authorized = os.getpgid(process.pid) == process.pid
                if not record.group_authorized:
                    raise RuntimeError("script process group ownership is unavailable")
                self._before_publish_process(record)
                with record.condition:
                    record.process = process
                    self._transfer_setup_result_read(record)
                    if record.state == "abandoned":
                        owns_cleanup = True
                    else:
                        record.state = "published"
                        record.condition.notify_all()
                        owns_cleanup = False
                if owns_cleanup:
                    self._cleanup_launch_record(record, "late_launch_cleanup")
            except BaseException as exc:
                if process is not None:
                    with record.condition:
                        if record.process is None:
                            record.process = process
                    if not record.group_authorized:
                        cleanup_deadline = record.cleanup_deadline or deadline
                        record.cleanup.termination_started = True
                        try:
                            record.cleanup.termination_confirmed = (
                                terminate_unpublished_process(
                                    self,
                                    process,
                                    cleanup_deadline,
                                    record.termination_grace or self._cleanup_grace,
                                )
                            )
                        except BaseException:
                            record.cleanup.termination_confirmed = False
                    try:
                        self._cleanup_launch_record(record, "launch_exception_cleanup")
                    except BaseException:
                        self._ensure_record_debt(record, process)
                else:
                    record.cleanup.termination_started = True
                    record.cleanup.termination_confirmed = True
                    for channel in record.cleanup.channels.values():
                        channel.state = "closed"
                    try:
                        with self._cleanup_execution_lease(record) as cleanup_lease:
                            if cleanup_lease is not None:
                                self._close_record_channels(record)
                    except BaseException:
                        pass
                    if not self._record_channels_closed(record):
                        self._ensure_record_debt(record, None)
                with record.condition:
                    if record.state == "abandoned":
                        if (
                            record.cleanup.termination_confirmed
                            and self._record_channels_closed(record)
                        ):
                            self._resolve_debt(record.debt_id, record)
                        return
                    record.error = exc
                    record.cleanup_confirmed = (
                        record.cleanup.termination_confirmed
                        and self._record_channels_closed(record)
                    )
                    record.cleanup_debt = (
                        None if record.cleanup_confirmed else record.debt_id
                    )
                    record.state = "failed"
                    record.condition.notify_all()
        thread = threading.Thread(target=launch, name="hook-script-launch", daemon=True)
        try:
            thread.start()
            self._after_launch_thread_start(record)
            with record.condition:
                while record.state == "launching":
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        record.state = "abandoned"
                        self._record_launch_debt(record.debt_id, record)
                        return WorkerResult(
                            "timeout",
                            error_category="startup_timeout",
                            cleanup_confirmed=False,
                            cleanup_debt=record.debt_id,
                        )
                    self._wait_for_launch(record, remaining)
                if record.state == "failed":
                    return WorkerResult(
                        "worker_lost",
                        error_category="startup_failure",
                        cleanup_confirmed=record.cleanup_confirmed,
                        cleanup_debt=record.cleanup_debt,
                    )
                if record.process is None or record.result_fd is None:
                    return WorkerResult("worker_lost", error_category="startup_failure")
                self._after_launch_published(record)
                return _LaunchLease(self, record)
        except BaseException:
            self._abandon_launch(record)
            raise

    def _abandon_launch(self, record: _LaunchRecord) -> None:
        """Leave launch cleanup with exactly one owner after host interruption."""
        lease: _LaunchLease | None = None
        with record.condition:
            if record.state == "launching":
                record.state = "abandoned"
                self._record_launch_debt(record.debt_id, record)
            elif record.state == "published":
                lease = _LaunchLease(self, record)
        if lease is not None:
            lease.cleanup()

    def _wait_for_launch(self, record: _LaunchRecord, remaining: float) -> None:
        """Wait for launch state publication while the caller owns the condition."""
        record.condition.wait(remaining)

    def _after_launch_thread_start(self, record: _LaunchRecord) -> None:
        """Provide a deterministic test seam after the launcher thread starts."""

    def _before_publish_process(self, record: _LaunchRecord) -> None:
        """Provide a deterministic test seam immediately before ownership publication."""

    def _after_launch_published(self, record: _LaunchRecord) -> None:
        """Provide a deterministic test seam before returning the armed lease."""

    def _before_launch_lease_release(self, record: _LaunchRecord) -> None:
        """Provide a deterministic test seam before execute accepts cleanup ownership."""

    def _worker_environment(self) -> dict[str, str]:
        """Build a minimal explicit environment for the controlled worker."""
        environment = {
            "HOME": self._temp_root,
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": os.pathsep.join(filter(None, sys.path)),
            "PYTHONDONTWRITEBYTECODE": "1",
            "TEMP": self._temp_root,
            "TMP": self._temp_root,
            "TMPDIR": self._temp_root,
            "TOPSAILAI_HOME": self._temp_root,
            "TOPSAILAI_HOOK_WORKER": "1",
        }
        for name in (
            "TOPSAILAI_EVENTS_ENABLED", "TOPSAILAI_EVENTS_BUFFER_SIZE",
            "TOPSAILAI_EVENTS_FLUSH_INTERVAL_MS", "TOPSAILAI_EVENTS_BACKEND",
            "TOPSAILAI_EVENTS_FILE_PATH", "TOPSAILAI_EVENTS_FILE_RETENTION_DAYS",
            "TOPSAILAI_EVENTS_FILE_MAX_COUNT", "TOPSAILAI_EVENTS_FILE_DELETE_ON_EXIT",
            "TOPSAILAI_EVENTS_FILE_FSYNC",
        ):
            if name in os.environ:
                environment[name] = os.environ[name]
        for name in ("LANG", "LC_ALL", "SYSTEMROOT", "WINDIR"):
            if name in os.environ:
                environment[name] = os.environ[name]
        return environment

    def _exchange(
        self,
        record: _LaunchRecord,
        process: subprocess.Popen[bytes],
        result_fd: int,
        request: bytes,
        buffers: dict[str, bytearray],
        dropped: dict[str, int],
        deadline: float,
    ) -> str:
        """Send input and drain all output using one non-blocking selector lifecycle."""
        if process.stdin is None:
            return "worker_lost"
        selector: selectors.BaseSelector | None = None
        try:
            selector = selectors.DefaultSelector()
            streams: list[Any] = [process.stdin, process.stdout, process.stderr]
            for stream in streams:
                if stream is not None:
                    os.set_blocking(stream.fileno(), False)
            os.set_blocking(result_fd, False)
            selector.register(process.stdin.fileno(), selectors.EVENT_WRITE, "stdin")
            selector.register(result_fd, selectors.EVENT_READ, "result")
            for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
                if stream is not None:
                    selector.register(stream.fileno(), selectors.EVENT_READ, name)
            offset = 0
            expected: int | None = None
            while selector.get_map():
                remaining = deadline - time.monotonic()
                stop = self._execution_stop(deadline, record.cancellation)
                if stop is not None:
                    return stop
                try:
                    events = selector.select(min(remaining, 0.05) if record.cancellation is not None else remaining)
                except OSError:
                    return self._execution_stop(deadline, record.cancellation) or "transport_error"
                stop = self._execution_stop(deadline, record.cancellation)
                if stop is not None:
                    return stop
                if not events:
                    continue
                for key, mask in events:
                    name = key.data
                    if name == "stdin" and mask & selectors.EVENT_WRITE:
                        try:
                            written = os.write(
                                key.fd, request[offset : offset + self._request_write_chunk_size()]
                            )
                        except BlockingIOError:
                            continue
                        except OSError:
                            selector.unregister(key.fd)
                            return "transport_error"
                        offset += written
                        if offset == len(request):
                            selector.unregister(key.fd)
                            self._close_transport_stream(record, "stdin")
                        continue
                    try:
                        chunk = self._read_channel(key.fd, 65_536)
                    except BlockingIOError:
                        continue
                    except OSError:
                        return "transport_error"
                    if not chunk:
                        selector.unregister(key.fd)
                        if name == "result":
                            return "invalid_output" if buffers["result"] else "worker_lost"
                        continue
                    if name == "result":
                        buffers[name].extend(chunk)
                        try:
                            expected = expected_frame_size(
                                bytes(buffers[name]), self._limits.response_bytes
                            )
                        except ValidationError:
                            return "invalid_output"
                        if expected is not None and len(buffers[name]) >= expected:
                            if len(buffers[name]) != expected:
                                return "invalid_output"
                            return "result"
                    else:
                        available = max(0, self._output_limit - len(buffers[name]))
                        buffers[name].extend(chunk[:available])
                        dropped[name] += len(chunk) - available
            return "invalid_output" if buffers["result"] else "worker_lost"
        except OSError:
            return "transport_error"
        finally:
            if selector is not None:
                selector.close()

    def _request_write_chunk_size(self) -> int:
        """Return the bounded request-write chunk size, with a test seam for segmentation."""
        return 65_536

    def _read_channel(self, descriptor: int, size: int) -> bytes:
        """Read one channel chunk through a deterministic transport test seam."""
        return os.read(descriptor, size)
