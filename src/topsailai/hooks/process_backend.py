"""Platform-qualified supervision for one isolated hook delivery."""

from __future__ import annotations

import os
import secrets
import selectors
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from typing import Any

from topsailai.hooks.contracts import HookContext, JsonValue, ValidationError
from topsailai.hooks.worker_protocol import (
    ProtocolLimits,
    build_request,
    decode_frame,
    encode_frame,
    expected_frame_size,
    validate_response,
)


from topsailai.hooks.process_cleanup import ProcessCleanupMixin
from topsailai.hooks.process_state import (
    CleanupDebt,
    DebtEntry as _DebtEntry,
    LaunchRecord as _LaunchRecord,
    WorkerResult,
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
    ) -> WorkerResult:
        """Complete or resume the one cleanup transaction and build its result."""
        return self._backend._finish_record(
            self._record, status, buffers, dropped, error_category, value
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

class IsolatedProcessBackend(ProcessCleanupMixin):
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
    ) -> None:
        """Configure explicit finite process, protocol, output, and cleanup limits."""
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

    def cleanup_debts(self) -> tuple[CleanupDebt, ...]:
        """Return a stable snapshot of cleanup obligations not yet confirmed settled."""
        with self._debt_lock:
            return tuple(self._debts[key] for key in sorted(self._debts))

    def retry_cleanup(self, debt_id: str) -> bool:
        """Independently retry process and channel cleanup under one exact lease."""
        entry: _DebtEntry | None = None
        debt_restore_required = False
        try:
            with self._debt_lock:
                entry = self._debt_processes.get(debt_id)
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
                interruption: BaseException | None = None
                try:
                    if not confirmed:
                        exited = entry.process.poll() is not None
                        if exited:
                            confirmed = not self._group_exists(entry.process.pid)
                        else:
                            confirmed = self._terminate_owned(entry.process)
                        if confirmed:
                            entry.record.cleanup.termination_confirmed = True
                except BaseException as exc:
                    interruption = self._retain_cleanup_error(
                        exc, ordinary_errors, interruption
                    )
                try:
                    self._close_record_channels(entry.record)
                except BaseException as exc:
                    interruption = self._retain_cleanup_error(
                        exc, ordinary_errors, interruption
                    )
                closed = self._record_channels_closed(entry.record)
                if confirmed and closed:
                    self._resolve_debt(debt_id, entry.record)
                if interruption is not None:
                    self._raise_cleanup_errors(ordinary_errors, interruption)
                return not ordinary_errors and confirmed and closed
        finally:
            if debt_restore_required and entry is not None:
                with self._debt_lock:
                    current = self._debt_processes.get(debt_id)
                    if current is entry and entry.state == "cleaning":
                        entry.state = "pending"

    def _after_cleanup_debt_claimed(self, entry: _DebtEntry) -> None:
        """Provide a deterministic seam after the first debt-state mutation."""

    def execute(self, handler_ref: str, context: HookContext, timeout_ms: int) -> WorkerResult:
        """Execute one delivery under one absolute startup/import/invoke/read deadline."""
        unsupported = self._preflight(timeout_ms)
        if unsupported is not None:
            return unsupported
        interpreter = self._resolve_interpreter()
        if interpreter is None:
            return WorkerResult("unsupported_backend", error_category="missing_interpreter")
        try:
            os.makedirs(self._temp_root, exist_ok=True)
        except OSError:
            return WorkerResult("unsupported_backend", error_category="invalid_temp_root")

        deadline = time.monotonic() + timeout_ms / 1_000
        correlation_id = uuid.uuid4().hex
        channel_token = secrets.token_urlsafe(32)
        request = build_request(
            correlation_id=correlation_id,
            channel_token=channel_token,
            handler_ref=handler_ref,
            context=context,
        )
        try:
            request_frame = encode_frame(request, self._limits.request_bytes)
        except ValidationError:
            return WorkerResult("invalid_request", error_category="invalid_request")

        record = _LaunchRecord(uuid.uuid4().hex)
        lease: _LaunchLease | None = None
        try:
            spawned = self._spawn(interpreter, deadline, record)
            if isinstance(spawned, WorkerResult):
                return spawned
            lease = spawned
            process, result_fd = lease.resources()
            buffers = {"result": bytearray(), "stdout": bytearray(), "stderr": bytearray()}
            dropped = {"stdout": 0, "stderr": 0}
            transferred = False
            try:
                self._before_launch_lease_release(record)
                lease.release_to_caller()
                transferred = True
                read_status = self._exchange(
                    record, process, result_fd, request_frame, buffers, dropped, deadline
                )
                if read_status != "result":
                    if read_status == "timeout":
                        status, category = "timeout", "deadline"
                    elif read_status in ("invalid_output", "worker_lost"):
                        status, category = read_status, "protocol_error"
                    else:
                        status, category = "worker_lost", "transport_error"
                    return lease.finish(status, buffers, dropped, category)
                try:
                    response = decode_frame(bytes(buffers["result"]), self._limits.response_bytes)
                    terminal = self._validate_terminal(
                        response,
                        correlation_id=correlation_id,
                        channel_token=channel_token,
                        delivery_id=context.delivery_id,
                    )
                except ValidationError:
                    return lease.finish(
                        "invalid_output", buffers, dropped, "protocol_error"
                    )
                if self._deadline_expired(deadline):
                    return lease.finish("timeout", buffers, dropped, "deadline")
                return lease.finish(
                    str(terminal["status"]),
                    buffers,
                    dropped,
                    terminal["error_category"],
                    terminal["value"],
                )
            finally:
                if transferred:
                    try:
                        lease.finish(
                            "worker_lost", buffers, dropped, "host_interrupted"
                        )
                    finally:
                        lease.close_after_finish()
        except BaseException:
            if lease is not None:
                lease.cleanup()
            else:
                self._abandon_launch(record)
            raise

    def _preflight(self, timeout_ms: int) -> WorkerResult | None:
        """Reject platforms outside the currently verified Linux capability scope."""
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

        thread = threading.Thread(target=launch, name="hook-worker-launch", daemon=True)
        try:
            thread.start()
            self._after_launch_thread_start(record)
            with record.condition:
                while record.state == "launching":
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        record.state = "abandoned"
                        self._record_launch_debt(record.debt_id)
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
                self._record_launch_debt(record.debt_id)
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
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": os.pathsep.join(filter(None, sys.path)),
            "PYTHONDONTWRITEBYTECODE": "1",
            "TMPDIR": self._temp_root,
            "TEMP": self._temp_root,
            "TMP": self._temp_root,
            "TOPSAILAI_HOOK_WORKER": "1",
        }
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
                if remaining <= 0:
                    return "timeout"
                try:
                    events = selector.select(remaining)
                except OSError:
                    return "transport_error"
                if not events:
                    return "timeout"
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
