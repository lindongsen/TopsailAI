"""Cleanup state-machine operations for isolated hook processes."""

from __future__ import annotations

import os
import signal
import subprocess
import time
import threading
from contextlib import contextmanager
from typing import Any, Iterator

from topsailai.hooks.process_state import (
    ChannelCloseState,
    CleanupDebt,
    CleanupExecutionLease,
    DebtEntry as _DebtEntry,
    LaunchRecord as _LaunchRecord,
    WorkerResult,
)


class ProcessCleanupMixin:
    """Provide interruption-safe termination, debt, and channel cleanup."""

    @contextmanager
    def _cleanup_execution_lease(
        self, record: _LaunchRecord
    ) -> Iterator[CleanupExecutionLease | None]:
        """Own acquisition, handoff, and exact release in one protected generator."""
        owner = threading.get_ident()
        prior: tuple[int | None, int, str] | None = None
        lease: CleanupExecutionLease | None = None
        mutation_complete = False
        try:
            with record.condition:
                cleanup = record.cleanup
                if cleanup.execution_owner in (None, owner):
                    prior = (
                        cleanup.execution_owner,
                        cleanup.execution_depth,
                        cleanup.state,
                    )
                    lease = CleanupExecutionLease(owner, prior[1] + 1)
                    cleanup.execution_owner = owner
                    self._after_cleanup_execution_owner_set(record)
                    cleanup.execution_depth = lease.depth
                    cleanup.state = "cleaning"
                    mutation_complete = True
            if lease is None:
                yield None
                return
            self._after_cleanup_execution_acquired(record)
            yield lease
        finally:
            if prior is not None and lease is not None:
                with record.condition:
                    cleanup = record.cleanup
                    if not mutation_complete:
                        cleanup.execution_owner = prior[0]
                        cleanup.execution_depth = prior[1]
                        cleanup.state = prior[2]
                        record.condition.notify_all()
                    elif (
                        cleanup.execution_owner == lease.owner
                        and threading.get_ident() == lease.owner
                        and cleanup.execution_depth == lease.depth
                    ):
                        cleanup.execution_depth -= 1
                        if cleanup.execution_depth == 0:
                            cleanup.execution_owner = None
                            cleanup.state = (
                                "complete"
                                if self._record_channels_closed(record)
                                else "owned"
                            )
                            record.condition.notify_all()
                    else:
                        raise RuntimeError("cleanup execution lease token is not current")

    def _finish_record(
        self,
        record: _LaunchRecord,
        status: str,
        buffers: dict[str, bytearray],
        dropped: dict[str, int],
        error_category: Any = None,
        value: Any = None,
    ) -> WorkerResult:
        """Resume the authoritative termination, debt, closure, and result transaction."""
        with self._cleanup_execution_lease(record) as lease:
            if lease is None:
                raise RuntimeError("cleanup transaction is already active")
            cleanup = record.cleanup
            if cleanup.result is not None:
                return cleanup.result
            process = record.process
            if process is None:
                raise RuntimeError("cleanup process is unavailable")

            pending: BaseException | None = None
            try:
                if not cleanup.termination_started:
                    cleanup.termination_started = True
                    try:
                        cleanup.termination_confirmed = self._terminate_owned(process)
                        self._after_record_termination(record)
                    except BaseException as exc:
                        pending = exc
                if cleanup.termination_started and not cleanup.termination_confirmed:
                    try:
                        self._ensure_record_debt(record, process)
                        self._after_record_debt(record)
                    except BaseException as exc:
                        if pending is None:
                            pending = exc
            finally:
                try:
                    self._close_record_channels(record)
                except BaseException as exc:
                    if pending is None:
                        pending = exc
                closed = self._record_channels_closed(record)
                if not closed:
                    self._ensure_record_debt(record, process)
                if cleanup.termination_confirmed and closed:
                    self._resolve_debt(record.debt_id, record)

            if pending is not None:
                raise pending
            confirmed = cleanup.termination_confirmed and self._record_channels_closed(record)
            cleanup.result = WorkerResult(
                status=status,
                value=value,
                error_category=error_category if type(error_category) is str else None,
                stdout=bytes(buffers["stdout"]),
                stderr=bytes(buffers["stderr"]),
                stdout_dropped=dropped["stdout"],
                stderr_dropped=dropped["stderr"],
                cleanup_confirmed=confirmed,
                cleanup_debt=None if confirmed else record.debt_id,
            )
            return cleanup.result

    def _ensure_record_debt(
        self, record: _LaunchRecord, process: subprocess.Popen[bytes]
    ) -> None:
        """Represent unfinished cleanup unless shared state is already settled."""
        with self._debt_lock:
            if record.cleanup.debt_state == "settled":
                return
            if record.debt_id not in self._debt_processes:
                self._debts[record.debt_id] = CleanupDebt(
                    record.debt_id,
                    "process",
                    process.pid,
                    "owned cleanup not confirmed",
                )
                self._debt_processes[record.debt_id] = _DebtEntry(process, record)
            record.cleanup.debt_state = "pending"

    def _cleanup_launch_record(self, record: _LaunchRecord, category: str) -> WorkerResult:
        """Route every published late-launch or launch-error resource through one state."""
        empty = {"stdout": bytearray(), "stderr": bytearray()}
        dropped = {"stdout": 0, "stderr": 0}
        return self._finish_record(record, "worker_lost", empty, dropped, category)

    def _close_transport_stream(self, record: _LaunchRecord, name: str) -> None:
        """Close a transport stream through the authoritative cleanup execution lease."""
        with self._cleanup_execution_lease(record) as lease:
            if lease is None:
                raise RuntimeError("cleanup transaction is already active")
            process = record.process
            if process is None:
                raise RuntimeError("cleanup process is unavailable")
            self._close_stream_channel(record, process, name)

    def _close_record_channels(self, record: _LaunchRecord) -> None:
        """Close channels while retaining every unconfirmed ownership obligation."""
        if not self._cleanup_execution_owned(record):
            raise RuntimeError("cleanup execution lease is required for channel closure")
        process = record.process
        if process is None:
            return
        pending: BaseException | None = None
        for name in ("stdin", "stdout", "stderr"):
            try:
                self._close_stream_channel(record, process, name)
            except BaseException as exc:
                if pending is None:
                    pending = exc
        try:
            self._close_result_channel(record)
        except BaseException as exc:
            if pending is None:
                pending = exc
        if pending is not None:
            raise pending

    @staticmethod
    def _cleanup_execution_owned(record: _LaunchRecord) -> bool:
        """Return whether the current thread owns this record's cleanup execution."""
        return record.cleanup.execution_owner == threading.get_ident()

    def _close_stream_channel(
        self, record: _LaunchRecord, process: subprocess.Popen[bytes], name: str
    ) -> None:
        """Close one file-object channel and retain ownership when closure is unconfirmed."""
        channel = record.cleanup.channels[name]
        owner = threading.get_ident()
        stream: Any = None
        descriptor: int | None = None
        try:
            with record.condition:
                if channel.state == "closed":
                    return
                stream = channel.resource or getattr(process, name, None)
                if stream is None:
                    channel.state = "closed"
                    return
                channel.resource = stream
                if stream.closed:
                    self._settle_stream_channel(process, name, channel)
                    return
                if channel.state in ("closing", "uncertain"):
                    state = self._classify_stream_close(channel, stream)
                    channel.state = state
                    channel.close_owner = None
                    channel.close_started = False
                    if state == "closed":
                        self._settle_stream_channel(process, name, channel)
                        return
                    if state != "open":
                        return
                descriptor = stream.fileno()
                self._prepare_channel_close(channel, descriptor, owner)
            self._before_channel_close(record, name, descriptor)
            with record.condition:
                channel.close_started = True
            stream.close()
            self._after_stream_close_before_commit(record, name, descriptor)
            with record.condition:
                self._settle_stream_channel(process, name, channel)
        except BaseException as exc:
            if stream is not None:
                self._retain_stream_close_state(record, process, name, stream, channel)
            if not isinstance(exc, Exception):
                raise
            return
        self._after_channel_close(record, name, descriptor)

    def _close_result_channel(self, record: _LaunchRecord) -> None:
        """Close the raw result descriptor without losing or duplicating ownership."""
        channel = record.cleanup.channels["result"]
        owner = threading.get_ident()
        descriptor: int | None = None
        try:
            with record.condition:
                if channel.state == "closed":
                    return
                descriptor = (
                    channel.resource if type(channel.resource) is int else record.result_fd
                )
                if descriptor is None:
                    channel.state = "closed"
                    return
                channel.resource = descriptor
                if channel.state in ("closing", "uncertain"):
                    state = self._classify_interrupted_close(channel, descriptor)
                    channel.state = state
                    channel.close_owner = None
                    channel.close_started = False
                    if state == "closed":
                        self._settle_result_channel(record, channel)
                        return
                    if state != "open":
                        return
                self._prepare_channel_close(channel, descriptor, owner)
            self._before_channel_close(record, "result", descriptor)
            with record.condition:
                channel.close_started = True
            os.close(descriptor)
            self._after_result_close_before_commit(record, descriptor)
            with record.condition:
                self._settle_result_channel(record, channel)
        except BaseException as exc:
            if descriptor is not None:
                self._retain_result_close_state(record, channel, descriptor)
            if not isinstance(exc, Exception):
                raise
            return
        self._after_channel_close(record, "result", descriptor)
        self._after_record_result_fd_close(record, descriptor)

    @staticmethod
    def _settle_stream_channel(
        process: subprocess.Popen[bytes], name: str, channel: ChannelCloseState
    ) -> None:
        """Commit one stream channel as closed and release its ownership record."""
        channel.state = "closed"
        channel.resource = None
        channel.close_owner = None
        channel.close_started = False
        setattr(process, name, None)

    @staticmethod
    def _settle_result_channel(
        record: _LaunchRecord, channel: ChannelCloseState
    ) -> None:
        """Commit the raw result channel as closed and release its ownership record."""
        channel.state = "closed"
        channel.resource = None
        channel.close_owner = None
        channel.close_started = False
        record.result_fd = None

    def _retain_stream_close_state(
        self,
        record: _LaunchRecord,
        process: subprocess.Popen[bytes],
        name: str,
        stream: Any,
        channel: ChannelCloseState,
    ) -> None:
        """Retain or settle stream ownership after an interrupted close attempt."""
        state = self._classify_stream_close(channel, stream)
        with record.condition:
            channel.state = state
            channel.close_owner = None
            channel.close_started = False
            if state == "closed":
                self._settle_stream_channel(process, name, channel)

    def _retain_result_close_state(
        self, record: _LaunchRecord, channel: ChannelCloseState, descriptor: int
    ) -> None:
        """Retain or settle raw-descriptor ownership after an interrupted close attempt."""
        state = self._classify_interrupted_close(channel, descriptor)
        with record.condition:
            channel.state = state
            channel.close_owner = None
            channel.close_started = False
            if state == "closed":
                self._settle_result_channel(record, channel)

    def _prepare_channel_close(
        self, channel: ChannelCloseState, descriptor: int, owner: int
    ) -> None:
        """Persist identity and the sole close-attempt owner before closing."""
        if channel.identity is None:
            identity = self._descriptor_identity(descriptor)
            channel.identity = identity[1]
        channel.descriptor = descriptor
        channel.close_owner = owner
        channel.close_started = False
        channel.state = "closing"

    def _classify_stream_close(self, channel: ChannelCloseState, stream: Any) -> str:
        """Classify a file-object close without acting on a potentially reused descriptor."""
        if stream.closed:
            return "closed"
        if channel.descriptor is None:
            return "uncertain"
        return self._classify_interrupted_close(channel, channel.descriptor)

    def _classify_interrupted_close(
        self, channel: ChannelCloseState, descriptor: int
    ) -> str:
        """Classify interrupted close without blindly retrying a reused descriptor."""
        status, current = self._descriptor_identity(descriptor)
        if status == "closed":
            return "closed"
        if status == "open" and channel.identity is not None:
            return "open" if current == channel.identity else "closed"
        return "uncertain"

    def _record_channels_closed(self, record: _LaunchRecord) -> bool:
        """Return whether every channel obligation is confirmed closed."""
        return all(item.state == "closed" for item in record.cleanup.channels.values())

    @staticmethod
    def _descriptor_identity(
        descriptor: int,
    ) -> tuple[str, tuple[int, int, int] | None]:
        """Classify a descriptor as open, closed, or uncertain with stable identity."""
        try:
            stat = os.fstat(descriptor)
        except OSError as exc:
            if exc.errno == 9:
                return "closed", None
            return "uncertain", None
        return "open", (descriptor, stat.st_dev, stat.st_ino)


    def _after_cleanup_execution_owner_set(self, record: _LaunchRecord) -> None:
        """Provide a deterministic seam after the first lease-state mutation."""

    def _after_cleanup_execution_acquired(self, record: _LaunchRecord) -> None:
        """Provide a deterministic seam after cleanup execution ownership publication."""

    def _before_channel_close(
        self, record: _LaunchRecord, name: str, descriptor: int
    ) -> None:
        """Provide a deterministic seam immediately before an actual close."""

    def _after_stream_close_before_commit(
        self, record: _LaunchRecord, name: str, descriptor: int
    ) -> None:
        """Provide a deterministic seam after stream close and before state commit."""

    def _after_result_close_before_commit(
        self, record: _LaunchRecord, descriptor: int
    ) -> None:
        """Provide a deterministic seam after raw close and before state commit."""

    def _after_channel_close(
        self, record: _LaunchRecord, name: str, descriptor: int
    ) -> None:
        """Provide a deterministic seam after confirmed close state is retained."""

    def _after_record_termination(self, record: _LaunchRecord) -> None:
        """Provide a deterministic seam after termination state is retained."""

    def _after_record_debt(self, record: _LaunchRecord) -> None:
        """Provide a deterministic seam after stable debt publication."""

    def _after_record_result_fd_close(self, record: _LaunchRecord, descriptor: int) -> None:
        """Provide a compatibility seam after confirmed raw descriptor closure."""

    def _terminate_owned(self, process: subprocess.Popen[bytes]) -> bool:
        """Signal only while the exact process leader still proves group ownership."""
        pgid = process.pid
        for sig in (signal.SIGTERM, signal.SIGKILL):
            authorization = self._authorize_owned_group_signal(process, pgid)
            if authorization == "exited":
                return not self._group_exists(pgid)
            if authorization != "owned":
                return False
            try:
                os.killpg(pgid, sig)
            except ProcessLookupError:
                return self._owned_group_finished(process, pgid)
            except OSError:
                return False
            end = time.monotonic() + self._cleanup_grace
            while time.monotonic() < end:
                try:
                    exited = process.poll() is not None
                except OSError:
                    return False
                if exited:
                    return not self._group_exists(pgid)
                time.sleep(0.005)
        try:
            process.wait(timeout=self._cleanup_grace)
        except (subprocess.TimeoutExpired, OSError):
            return False
        return not self._group_exists(pgid)

    @staticmethod
    def _authorize_owned_group_signal(
        process: subprocess.Popen[bytes], pgid: int
    ) -> str:
        """Classify exact live ownership before each process-group signal."""
        try:
            if process.poll() is not None:
                return "exited"
            return "owned" if os.getpgid(process.pid) == pgid else "uncertain"
        except ProcessLookupError:
            return "exited"
        except OSError:
            return "uncertain"

    def _owned_group_finished(
        self, process: subprocess.Popen[bytes], pgid: int
    ) -> bool:
        """Confirm completion after an authorized signal races with group exit."""
        try:
            exited = process.poll() is not None
        except OSError:
            return False
        return exited and not self._group_exists(pgid)

    def _record_launch_debt(self, debt_id: str) -> None:
        """Record an unsettled launch whose creator retains cleanup ownership."""
        with self._debt_lock:
            self._debts[debt_id] = CleanupDebt(debt_id, "launching", None, "late launch pending")

    def _record_process_debt(
        self,
        debt_id: str,
        process: subprocess.Popen[bytes],
        detail: str,
        record: _LaunchRecord | None = None,
    ) -> None:
        """Retain exclusive authority for one process and authoritative record."""
        if record is None:
            record = _LaunchRecord(debt_id, process=process)
            record.cleanup.termination_started = True
            for channel in record.cleanup.channels.values():
                channel.state = "closed"
        with self._debt_lock:
            self._debts[debt_id] = CleanupDebt(debt_id, "process", process.pid, detail)
            self._debt_processes[debt_id] = _DebtEntry(process, record)
            record.cleanup.debt_state = "pending"

    def _resolve_debt(self, debt_id: str, record: _LaunchRecord | None = None) -> None:
        """Mark debt terminal before removing its public table entries."""
        with self._debt_lock:
            entry = self._debt_processes.get(debt_id)
            owner = record or (entry.record if entry is not None else None)
            if owner is not None:
                owner.cleanup.debt_state = "settled"
                owner.cleanup.termination_confirmed = True
            self._debts.pop(debt_id, None)
            self._debt_processes.pop(debt_id, None)

    @staticmethod
    def _safe_close_fd(descriptor: int | None) -> None:
        """Close a setup-only descriptor that has not entered the ownership record."""
        if descriptor is None:
            return
        try:
            os.close(descriptor)
        except OSError:
            pass

    @staticmethod
    def _close_process_stream(process: subprocess.Popen[bytes], name: str) -> None:
        """Close one setup-only process stream."""
        stream = getattr(process, name)
        if stream is None:
            return
        stream.close()
        setattr(process, name, None)

    @classmethod
    def _close_channels(cls, process: subprocess.Popen[bytes], result_fd: int | None) -> None:
        """Close setup-only channels before authoritative publication."""
        for name in ("stdin", "stdout", "stderr"):
            try:
                cls._close_process_stream(process, name)
            except OSError:
                pass
        cls._safe_close_fd(result_fd)

    @staticmethod
    def _group_exists(pgid: int) -> bool:
        """Return whether the exact owned POSIX process group still exists."""
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return False
        except OSError:
            return True
        return True
