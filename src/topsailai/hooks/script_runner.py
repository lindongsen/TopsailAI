"""Owned real-process adapter for admitted hook-script entries."""

from __future__ import annotations

import asyncio
import math
import os
import re
import sys
import threading
import time
import uuid
from pathlib import Path

from topsailai.hooks.contracts import HookContext, HookStatus
from topsailai.hooks.hook_script_contracts import (
    HookScriptEntryResult,
    HookScriptExecutionOptions,
    HookScriptExecutionPolicy,
)
from topsailai.hooks.hook_script_discovery import HookScriptEntry
from topsailai.hooks.process_backend import IsolatedProcessBackend
from topsailai.hooks.process_state import CleanupDebt, LaunchRecord, WorkerResult
from topsailai.hooks.process_transport import ScriptTransportFacts, drain_script_process
from topsailai.hooks.script_protocol import (
    ScriptProtocolError,
    decode_script_result,
    encode_script_input,
)
from topsailai.hooks.temporary_storage import TemporaryStorageOwner

_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RESERVED_ENVIRONMENT = frozenset(
    {
        "TMPDIR",
        "TEMP",
        "TMP",
        "LANG",
        "LC_ALL",
        "PYTHONDONTWRITEBYTECODE",
        "TOPSAILAI_HOOK_RESULT_FD",
        "TOPSAILAI_HOOK_RESULT_SOCKET",
    }
)
_PROHIBITED_ENVIRONMENT = frozenset({"BASH_ENV", "ENV", "SHELLOPTS", "BASHOPTS"})


class _StorageCustody:
    """Retain an exact prelaunch owner before recovery publication can fail."""

    def __init__(self, owner: TemporaryStorageOwner) -> None:
        """Arm ownership without exposing healthy in-flight storage as debt."""
        self.owner = owner
        self.pending = False
        self.recovering = False
        self.record: LaunchRecord | None = None


class OwnedHookScriptRunner:
    """Execute one admission's entries through one existing backend authority."""

    def __init__(self, backend: IsolatedProcessBackend) -> None:
        """Bind recovery snapshots and storage debt to one backend authority."""
        if not isinstance(backend, IsolatedProcessBackend):
            raise TypeError("backend must be an IsolatedProcessBackend")
        self._backend = backend
        self._lock = threading.Lock()
        self._results: dict[int, HookScriptEntryResult] = {}
        self._storage: dict[str, TemporaryStorageOwner] = {}
        self._process_storage: dict[str, TemporaryStorageOwner] = {}
        self._prelaunch_storage: dict[int, _StorageCustody] = {}
        self._nonretained_observed_bytes = 0

    def execute_entry(
        self,
        *,
        entry_index: int,
        entry: HookScriptEntry,
        context: HookContext,
        options: HookScriptExecutionOptions,
        policy: HookScriptExecutionPolicy,
        execution_deadline: float,
        cleanup_deadline: float,
        output_remaining_bytes: int,
        cancellation: threading.Event,
    ) -> HookScriptEntryResult:
        """Launch one literal executable and settle process, channels, and storage."""
        initial = HookScriptEntryResult(
            entry_index if type(entry_index) is int else -1,
            entry.basename if type(entry) is HookScriptEntry else "",
            HookStatus.ERROR,
            False,
            error_category="hook_script_startup_failed",
        )
        if not self._reserve_snapshot(initial):
            return initial
        with self._lock:
            effective_remaining = max(
                0, output_remaining_bytes - self._nonretained_observed_bytes
            ) if type(output_remaining_bytes) is int else output_remaining_bytes
        preflight = self._preflight(
            initial,
            entry_index,
            entry,
            context,
            options,
            policy,
            execution_deadline,
            cleanup_deadline,
            effective_remaining,
            cancellation,
        )
        if preflight is not None:
            return preflight

        storage = TemporaryStorageOwner(Path(self._backend.script_temp_root))
        custody = _StorageCustody(storage)
        with self._lock:
            self._prelaunch_storage[id(storage)] = custody
        lease = None
        record = None
        recovery_complete = False
        recovered = None
        try:
            if not storage.allocate():
                return self._publish(initial, HookStatus.ERROR, "hook_script_startup_failed")
            invocation_id = uuid.uuid4().hex
            try:
                request = encode_script_input(
                    context=context,
                    invocation_id=invocation_id,
                    entry_index=entry_index,
                    max_bytes=policy.stdin_limit_bytes,
                )
                argv = (str(entry.source_path), *options.argv)
                cwd = _execution_cwd(entry, options)
                environment = _execution_environment(storage.path, options)
            except (OSError, ValueError, ScriptProtocolError):
                return self._finish_storage(initial, storage)

            started = time.monotonic()
            record = LaunchRecord(
                uuid.uuid4().hex,
                cleanup_deadline=cleanup_deadline,
                termination_grace=policy.terminate_grace_ms / 1_000,
            )
            custody.record = record
            lease = None
            try:
                spawned = self._backend.launch_script(
                    argv=argv,
                    cwd=str(cwd),
                    environment=environment,
                    argument_environment_limit_bytes=(
                        policy.argument_environment_limit_bytes
                    ),
                    deadline=execution_deadline,
                    record=record,
                )
                if isinstance(spawned, WorkerResult):
                    return self._finish_launch_failure(initial, storage, spawned)
                lease = spawned
                process, result_fd = lease.resources()
                lease.release_to_caller()
                current = HookScriptEntryResult(
                    entry_index,
                    entry.basename,
                    HookStatus.ERROR,
                    True,
                    error_category="hook_script_execution_error",
                )
                self._set_result(current)
                facts = drain_script_process(
                    process,
                    result_fd,
                    request,
                    policy,
                    execution_deadline,
                    effective_remaining,
                    cancellation,
                    lambda: self._backend._close_transport_stream(record, "stdin"),
                )
                with self._lock:
                    self._nonretained_observed_bytes += (
                        facts.result_observed_bytes
                        + facts.stdout_dropped
                        + facts.stderr_dropped
                    )
                current = _classify_result(
                    current, facts, context, invocation_id, policy, started
                )
                worker = lease.finish(
                    current.status.value,
                    {"stdout": facts.stdout, "stderr": facts.stderr},
                    {
                        "stdout": facts.stdout_dropped,
                        "stderr": facts.stderr_dropped,
                    },
                    current.error_category,
                )
                current = _settled_result(current, facts, worker, started)
                current = self._settle_storage(current, storage)
                self._set_result(current)
                return current
            except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
                try:
                    if lease is not None:
                        try:
                            custody.recovering = True
                            custody.pending = True
                            recovered = self._preserve_interrupted(initial, record, storage, started)
                            custody.pending = not recovered.cleanup_confirmed
                            recovery_complete = True
                        finally:
                            custody.recovering = False
                except BaseException:
                    # Abandoned recovery must preserve the primary and release exclusion.
                    custody.recovering = False
                    if recovered is not None and recovered.cleanup_confirmed:
                        custody.pending = False
                        recovery_complete = True
                raise
            except Exception:
                if lease is None:
                    return self._finish_storage(initial, storage)
                current = self._preserve_interrupted(initial, record, storage, started)
                self._set_result(current)
                return current
        except BaseException:
            if lease is not None or (record is not None and record.process is not None):
                # Retain exact ordered recovery even when the inner publication failed.
                if not recovery_complete:
                    custody.pending = True
                raise
            custody.pending = True
            try:
                self._remember_storage(storage)
            except BaseException:
                # The pre-armed exact owner survives failed debt publication.
                pass
            try:
                if storage.cleanup():
                    self._forget_storage(storage)
                    custody.pending = False
            except BaseException:
                # Preserve the primary interruption and exact retryable custody.
                pass
            raise
        finally:
            if not custody.pending:  # pragma: no branch - pending propagates the primary exception
                self._prelaunch_storage.pop(id(storage), None)

    def current_result(self, entry_index: int) -> HookScriptEntryResult:
        """Return the latest immutable recovery snapshot for this admission."""
        with self._lock:
            result = self._results.get(entry_index)
        if result is None:
            raise KeyError("hook-script entry has no recovery snapshot")
        return result

    def _storage_ready(self, custody: _StorageCustody) -> bool:
        """Require exact process settlement before granting storage removal authority."""
        record = custody.record
        return record is None or record.process is None or (
            record.cleanup.debt_state == "settled"
            and record.cleanup.termination_confirmed
            and self._backend._record_channels_closed(record)
        )

    def cleanup_debts(self) -> tuple[object, ...]:
        """Return exact process obligations before independently removable storage."""
        process = {debt.debt_id: debt for debt in self._backend.cleanup_debts()}
        with self._lock:
            owners = {id(storage): storage for storage in self._storage.values()}
            for owner_id, custody in self._prelaunch_storage.items():
                if not custody.pending or custody.recovering:
                    owners.pop(owner_id, None)
                    continue
                if self._storage_ready(custody):
                    owners[owner_id] = custody.owner
                else:
                    owners.pop(owner_id, None)
                    record = custody.record
                    process.setdefault(record.debt_id, CleanupDebt(
                        record.debt_id, "process", record.process.pid,
                        "exact process recovery precedes storage removal",
                    ))
            storage = tuple(
                debt for owner_id in sorted(owners)
                for debt in owners[owner_id].cleanup_debts()
            )
        return (*process.values(), *storage)

    def retry_cleanup(self, debt_id: str) -> bool:
        """Retry exact process custody before allowing its storage to be removed."""
        with self._lock:
            if any(c.recovering and c.record is not None and c.record.debt_id == debt_id
                   for c in self._prelaunch_storage.values()):
                return False
            pending = tuple(c for c in self._prelaunch_storage.values() if c.pending and not c.recovering)
            process_custody = next((c for c in pending if c.record is not None
                                    and c.record.debt_id == debt_id), None)
            storage = self._storage.get(debt_id)
            if any(c.recovering and c.owner is storage
                   for c in self._prelaunch_storage.values()):
                storage = None
            for custody in pending:
                if not self._storage_ready(custody):
                    if storage is custody.owner:
                        storage = None
                    continue
                if any(debt.debt_id == debt_id for debt in custody.owner.cleanup_debts()):
                    storage = custody.owner
        if storage is not None:
            settled = storage.retry_cleanup(debt_id)
            if settled:
                self._forget_storage(storage)
            return settled
        if process_custody is not None:
            record = process_custody.record
            if not self._storage_ready(process_custody):
                if not self._backend.retry_cleanup(debt_id):
                    return False
                if not self._storage_ready(process_custody):
                    self._backend._finish_record(
                        record, "worker_lost", {"stdout": bytearray(), "stderr": bytearray()},
                        {"stdout": 0, "stderr": 0}, "host_interrupted",
                    )
                if not self._storage_ready(process_custody):
                    return False
            storage = process_custody.owner
            if not storage.cleanup():
                return False
            self._forget_storage(storage)
            return True
        if not self._backend.retry_cleanup(debt_id):
            return False
        with self._lock:
            storage = self._process_storage.get(debt_id)
        if storage is None:
            return True
        self._remember_storage(storage)
        if not storage.cleanup():
            return False
        self._forget_storage(storage)
        return True

    def _preflight(
        self,
        initial: HookScriptEntryResult,
        entry_index: object,
        entry: object,
        context: object,
        options: object,
        policy: object,
        execution_deadline: object,
        cleanup_deadline: object,
        output_remaining: object,
        cancellation: object,
    ) -> HookScriptEntryResult | None:
        """Reject malformed or exhausted calls before allocating resources."""
        if not _supported_platform():
            return self._publish(
                initial, HookStatus.ERROR, "hook_script_unsupported_backend"
            )
        if not _valid_call(
            entry_index,
            entry,
            context,
            options,
            policy,
            execution_deadline,
            cleanup_deadline,
            output_remaining,
            cancellation,
        ):
            return self._publish(
                initial, HookStatus.ERROR, "hook_script_startup_failed"
            )
        if cancellation.is_set():
            return self._publish(
                initial, HookStatus.CANCELLED, "hook_script_cancelled"
            )
        if time.monotonic() >= execution_deadline:
            return self._publish(
                initial, HookStatus.SKIPPED_DEADLINE, "hook_script_deadline"
            )
        if output_remaining == 0:
            return self._publish(
                initial, HookStatus.INVALID_OUTPUT, "hook_script_output_limit"
            )
        return None

    def _finish_launch_failure(
        self,
        initial: HookScriptEntryResult,
        storage: TemporaryStorageOwner,
        worker: WorkerResult,
    ) -> HookScriptEntryResult:
        """Map backend launch failure and preserve any cleanup ownership."""
        if not worker.cleanup_confirmed and worker.cleanup_debt is not None:
            self._remember_process_storage(worker.cleanup_debt, storage)
            result = _replace_cleanup_pending(initial, worker.cleanup_debt)
            self._set_result(result)
            return result
        return self._finish_storage(initial, storage)

    def _preserve_interrupted(
        self,
        initial: HookScriptEntryResult,
        record: LaunchRecord,
        storage: TemporaryStorageOwner,
        started: float,
    ) -> HookScriptEntryResult:
        """Preserve exact process and storage ownership before propagation."""
        worker = self._backend._finish_record(
            record,
            "worker_lost",
            {"stdout": bytearray(), "stderr": bytearray()},
            {"stdout": 0, "stderr": 0},
            "host_interrupted",
        )
        result = HookScriptEntryResult(
            initial.entry_index,
            initial.basename,
            HookStatus.WORKER_LOST,
            True,
            record.process.poll() if record.process is not None else None,
            _duration_ms(started),
            "host_interrupted",
            worker.stdout,
            worker.stderr,
            worker.stdout_dropped,
            worker.stderr_dropped,
            worker.cleanup_confirmed,
            worker.cleanup_debt,
        )
        result = self._settle_storage(result, storage)
        self._set_result(result)
        return result

    def _finish_storage(
        self, result: HookScriptEntryResult, storage: TemporaryStorageOwner
    ) -> HookScriptEntryResult:
        """Settle prelaunch storage or publish its exact removal debt."""
        if storage.cleanup():
            return self._publish(
                result, HookStatus.ERROR, "hook_script_startup_failed"
            )
        self._remember_storage(storage)
        debt = storage.cleanup_debts()[0]
        current = _replace_cleanup_pending(result, debt.debt_id)
        self._set_result(current)
        return current

    def _settle_storage(
        self, result: HookScriptEntryResult, storage: TemporaryStorageOwner
    ) -> HookScriptEntryResult:
        """Remove storage only after process cleanup or retain ordered debt."""
        if not result.cleanup_confirmed and result.cleanup_debt is not None:
            self._remember_process_storage(result.cleanup_debt, storage)
            return _replace_cleanup_pending(result, result.cleanup_debt)
        if storage.cleanup():
            return result
        self._remember_storage(storage)
        return _replace_cleanup_pending(result, storage.cleanup_debts()[0].debt_id)

    def _publish(
        self,
        result: HookScriptEntryResult,
        status: HookStatus,
        category: str,
    ) -> HookScriptEntryResult:
        """Publish one prelaunch result snapshot."""
        current = _replace_classification(result, status, category)
        self._set_result(current)
        return current

    def _reserve_snapshot(self, result: HookScriptEntryResult) -> bool:
        """Reserve one admission-local entry index exactly once."""
        with self._lock:
            if result.entry_index in self._results:
                return False
            self._results[result.entry_index] = result
        return True

    def _remember_storage(self, storage: TemporaryStorageOwner) -> None:
        """Retain one exact storage owner under its stable debt identity."""
        storage.retain_cleanup_debt()
        debts = storage.cleanup_debts()
        if debts:
            with self._lock:
                self._storage[debts[0].debt_id] = storage

    def _forget_storage(self, storage: TemporaryStorageOwner) -> None:
        """Release every lookup only after this exact storage owner settles."""
        with self._lock:
            self._storage = {
                debt_id: owner
                for debt_id, owner in self._storage.items()
                if owner is not storage
            }
            self._process_storage = {
                debt_id: owner
                for debt_id, owner in self._process_storage.items()
                if owner is not storage
            }
            self._prelaunch_storage.pop(id(storage), None)

    def _remember_process_storage(
        self, debt_id: str, storage: TemporaryStorageOwner
    ) -> None:
        """Keep invocation storage until corresponding process debt settles."""
        storage.retain_cleanup_debt()
        with self._lock:
            self._process_storage[debt_id] = storage

    def _set_result(self, result: HookScriptEntryResult) -> None:
        """Replace one immutable recovery snapshot under the admission lock."""
        with self._lock:
            self._results[result.entry_index] = result


def _classify_result(
    base: HookScriptEntryResult,
    facts: ScriptTransportFacts,
    context: HookContext,
    invocation_id: str,
    policy: HookScriptExecutionPolicy,
    started: float,
) -> HookScriptEntryResult:
    """Apply frozen C05 precedence to independently observed execution facts."""
    status, category = HookStatus.ERROR, "hook_script_execution_error"
    decoded = False
    if facts.cancelled:
        status, category = HookStatus.CANCELLED, "hook_script_cancelled"
    elif facts.deadline:
        status, category = HookStatus.TIMEOUT, "hook_script_timeout"
    elif facts.overflow:
        status, category = HookStatus.INVALID_OUTPUT, "hook_script_output_limit"
    elif facts.exit_code is not None and facts.exit_code < 0:
        status, category = HookStatus.WORKER_LOST, "hook_script_signal_exit"
    elif facts.exit_code not in (None, 0):
        status, category = HookStatus.ERROR, "hook_script_nonzero_exit"
    elif facts.exit_code == 0 and "result" in facts.eof and not facts.result:
        status, category = HookStatus.INVALID_OUTPUT, "hook_script_missing_result"
    elif facts.invalid_result:
        status, category = HookStatus.INVALID_OUTPUT, "hook_script_invalid_result"
    elif (
        facts.exit_code == 0
        and facts.result
        and _result_ready_for_decode(facts, policy.result_limit_bytes)
    ):
        try:
            decode_script_result(
                bytes(facts.result),
                delivery_id=context.delivery_id,
                invocation_id=invocation_id,
                entry_index=base.entry_index,
                result_limit_bytes=policy.result_limit_bytes,
            )
        except ScriptProtocolError:
            status, category = HookStatus.INVALID_OUTPUT, "hook_script_invalid_result"
        else:
            decoded = True
    if decoded:
        if facts.transport_error:
            status, category = HookStatus.WORKER_LOST, "hook_script_transport_error"
        elif facts.settled:
            status, category = HookStatus.SUCCESS, None
    elif category == "hook_script_execution_error" and facts.transport_error:
        status, category = HookStatus.WORKER_LOST, "hook_script_transport_error"
    return HookScriptEntryResult(
        base.entry_index,
        base.basename,
        status,
        True,
        facts.exit_code,
        _duration_ms(started),
        category,
        bytes(facts.stdout),
        bytes(facts.stderr),
        facts.stdout_dropped,
        facts.stderr_dropped,
        True,
        None,
    )


def _result_ready_for_decode(
    facts: ScriptTransportFacts, result_limit_bytes: int
) -> bool:
    """Return whether EOF or a complete bounded frame makes decoding conclusive."""
    if "result" in facts.eof:
        return True
    if len(facts.result) < 4:
        return False
    body_size = int.from_bytes(facts.result[:4], "big")
    return 1 <= body_size <= result_limit_bytes and len(facts.result) >= 4 + body_size

def _settled_result(
    result: HookScriptEntryResult,
    facts: ScriptTransportFacts,
    worker: WorkerResult,
    started: float,
) -> HookScriptEntryResult:
    """Merge authoritative cleanup facts without replacing observed evidence."""
    current = HookScriptEntryResult(
        result.entry_index,
        result.basename,
        result.status,
        True,
        facts.exit_code,
        _duration_ms(started),
        result.error_category,
        worker.stdout,
        worker.stderr,
        worker.stdout_dropped,
        worker.stderr_dropped,
        worker.cleanup_confirmed,
        worker.cleanup_debt,
    )
    if worker.cleanup_confirmed:
        return current
    return _replace_cleanup_pending(current, worker.cleanup_debt or "cleanup-pending")


def _valid_call(
    entry_index: object,
    entry: object,
    context: object,
    options: object,
    policy: object,
    execution_deadline: object,
    cleanup_deadline: object,
    output_remaining: object,
    cancellation: object,
) -> bool:
    """Validate runner-bound values before allocating process resources."""
    return (
        type(entry_index) is int
        and entry_index >= 0
        and type(entry) is HookScriptEntry
        and type(context) is HookContext
        and type(options) is HookScriptExecutionOptions
        and type(policy) is HookScriptExecutionPolicy
        and type(execution_deadline) in (int, float)
        and math.isfinite(execution_deadline)
        and type(cleanup_deadline) in (int, float)
        and math.isfinite(cleanup_deadline)
        and execution_deadline <= cleanup_deadline
        and type(output_remaining) is int
        and output_remaining >= 0
        and type(cancellation) is threading.Event
        and entry.source_path.is_absolute()
        and entry.basename == entry.source_path.name
    )


def _execution_cwd(entry: HookScriptEntry, options: HookScriptExecutionOptions) -> Path:
    """Resolve only the admitted target directory as execution cwd."""
    target_parent = entry.source_path.parent.resolve(strict=True)
    if options.cwd is None:
        return target_parent
    explicit = options.cwd.resolve(strict=True)
    if explicit != target_parent:
        raise ValueError("cwd is outside admitted target directory")
    return explicit


def _execution_environment(
    invocation_root: Path, options: HookScriptExecutionOptions
) -> dict[str, str]:
    """Build deterministic baseline and validated explicit environment data."""
    values = {
        "TMPDIR": str(invocation_root),
        "TEMP": str(invocation_root),
        "TMP": str(invocation_root),
        "LANG": "C",
        "LC_ALL": "C",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    names: set[str] = set()
    for name, value in options.environment:
        if (
            name in names
            or not _ENVIRONMENT_NAME.fullmatch(name)
            or name in _RESERVED_ENVIRONMENT
            or name in _PROHIBITED_ENVIRONMENT
            or name.startswith(("PYTHON", "LD_", "DYLD_"))
            or "\x00" in value
        ):
            raise ValueError("unsafe script environment")
        name.encode("utf-8")
        value.encode("utf-8")
        names.add(name)
        values[name] = value
    return values




def _supported_platform() -> bool:
    """Restrict descriptor transport to verified Linux POSIX hosts."""
    return (
        os.name == "posix"
        and sys.platform.startswith("linux")
        and hasattr(os, "killpg")
        and hasattr(os, "set_blocking")
    )


def _replace_classification(
    result: HookScriptEntryResult, status: HookStatus, category: str | None
) -> HookScriptEntryResult:
    """Replace classification while retaining observed evidence."""
    return HookScriptEntryResult(
        result.entry_index,
        result.basename,
        status,
        result.started,
        result.exit_code,
        result.duration_ms,
        category,
        result.stdout,
        result.stderr,
        result.stdout_dropped,
        result.stderr_dropped,
        result.cleanup_confirmed,
        result.cleanup_debt,
    )


def _replace_cleanup_pending(
    result: HookScriptEntryResult, debt_id: str
) -> HookScriptEntryResult:
    """Override business classification with unresolved cleanup ownership."""
    return HookScriptEntryResult(
        result.entry_index,
        result.basename,
        HookStatus.WORKER_LOST,
        result.started,
        result.exit_code,
        result.duration_ms,
        "hook_script_cleanup_pending",
        result.stdout,
        result.stderr,
        result.stdout_dropped,
        result.stderr_dropped,
        False,
        debt_id,
    )


def _duration_ms(started: float) -> int:
    """Return nonnegative observed elapsed milliseconds."""
    return max(0, int((time.monotonic() - started) * 1_000))
