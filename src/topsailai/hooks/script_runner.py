"""Owned real-process adapter for admitted hook-script entries."""

from __future__ import annotations

import asyncio
import math
import os
import re
import sys
import threading
import types
import time
import uuid
import weakref
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
    """Expose read-only custody while exact weak identity owns canonical snapshots."""

    __slots__ = ("__weakref__",)

    def __init__(self, owner: TemporaryStorageOwner) -> None:
        """Arm all canonical fields through the single exact-snapshot transition."""
        _initialize_retry_owner(self)
        self._write_state(owner=owner, pending=False, recovering=False,
                          proof=None, execution_owner=None, execution_lease=(None,),
                          storage_alias=None, release_complete=False,
                          storage_settled=False, reconciliation_pending=False, record=None)

    @property
    def __dict__(self):
        """Expose a read-only current snapshot rather than writable instance storage."""
        return _observe_retry_owner(self)

    def __getattr__(self, name):
        """Read only known canonical fields without admitting compatibility shadows."""
        state = _observe_retry_owner(self)
        if name not in state:
            raise AttributeError(name)
        return state[name]

    def _write_state(self, _retire=(), **changes):
        """Publish all legal custody changes through the same expected-identity writer."""
        if "execution_lease" in changes:
            changes["execution_lease"] = _immutable_lease(changes["execution_lease"])
        if not _transition_retry_owner(self, _observe_retry_owner(self), tuple(changes.items()), _retire):
            raise RuntimeError("custody transition lost exact snapshot authority")

    @property
    def retry_owner(self):
        """Observe exact token identity independently of compatibility shadows."""
        return _observe_retry_owner(self)["token"]

    def _write_retry_owner(self, token):
        """Publish token ownership through the sole exact-snapshot transition."""
        _commit_retry_owner(self, token)

    def _observe_handback(self):
        """Read proof from the same private canonical custody snapshot."""
        return _observe_retry_owner(self)

    def _transition_handback(self, expected, changes):
        """Delegate the trusted proof seam to the sole custody transition."""
        return _transition_retry_owner(self, expected, changes)

    @property
    def retry_handback(self):
        """Expose exact proof identity without permitting compatibility attribute writes."""
        return _observe_retry_owner(self)["proof"]

    def _write_handback(self, proof):
        """Publish proof through the sole exact-snapshot authority transition."""
        self._write_state(proof=proof)


def _immutable_lease(value):
    """Detach bounded native containers before any canonical publication."""
    active = set()
    budget = [4096]

    def freeze(member, depth):
        """Reject cycles and aggregate excess without foreign conversion hooks."""
        budget[0] -= 1
        if budget[0] < 0 or depth > 32:
            raise ValueError("lease snapshot exceeds immutable bounds")
        kind = type(member)
        if kind not in (type([]), tuple, type({}), set, types.MappingProxyType):
            return member
        identity = id(member)
        if identity in active:
            raise ValueError("lease snapshot contains a container cycle")
        active.add(identity)
        try:
            if kind in (type({}), types.MappingProxyType):
                return types.MappingProxyType({key: freeze(item, depth + 1)
                                               for key, item in member.items()})
            members = tuple(freeze(item, depth + 1) for item in member)
            if kind is set:
                return frozenset(members)
            return member if kind is tuple and all(a is b for a, b in zip(member, members)) else members
        finally:
            active.remove(identity)

    return freeze(value, 0)


def _valid_execution_lease(lease: object) -> bool:
    """Accept only the bounded native invocation lease and its exact token shape."""
    return (type(lease) is tuple and len(lease) == 1
            and (lease[0] is None or type(lease[0]) is object))


def _execution_lease_inactive(custody: _StorageCustody) -> bool:
    """Fail closed on missing or malformed authority without invoking user methods."""
    lease = _observe_retry_owner(custody).get("execution_lease")
    return _valid_execution_lease(lease) and lease[0] is None


def _observed_storage_debt(owner: TemporaryStorageOwner) -> CleanupDebt | None:
    """Read only a proven native debt observation without granting settlement authority."""
    try:
        state = object.__getattribute__(owner, "__dict__")
        if type(state) is not type({}):
            return None
        debt = state.get("_debt")
        return debt if isinstance(debt, CleanupDebt) else None
    except BaseException:
        return None


class _RetryInterruptionNote(str):
    """Identify runner-owned text without retaining secondary exception objects."""


def _note_retry_interruption(primary: BaseException, phase: str,
                             secondary: BaseException) -> None:
    """Bound best-effort runner notes while preserving caller state and failure identity."""
    try:
        notes = getattr(primary, "__notes__", [])
        if type(notes) is not list or any(not isinstance(note, str) for note in notes):
            return
        message = "Retry " + phase + " interrupted: " + type(secondary).__name__[:64]
        owned = [note for note in notes if type(note) is _RetryInterruptionNote]
        if message in owned or len(owned) >= 4:
            return
        BaseException.add_note(primary, _RetryInterruptionNote(message))
    except BaseException:
        # Diagnostics must never replace the already captured cleanup exception.
        pass


class _RetryFailure:
    """Carry an exact captured failure across normal generator termination."""

    __slots__ = ("primary", "traceback")

    def __init__(self, primary: BaseException, traceback: types.TracebackType) -> None:
        """Retain native exception identity and source without exception graph edges."""
        self.primary = primary
        self.traceback = traceback


class _RetryLockScope:
    """Journal one exact native acquisition before its fallible entry."""

    def __init__(self, lock, invocation):
        """Bind release authority to a thread and an immutable invocation identity."""
        self.lock = lock
        self.invocation = invocation
        self.thread = threading.get_ident()

    def __enter__(self):
        """Arm local responsibility before entering native exclusion."""
        self.lock._acquire_scope(self)
        return self

    def recover(self):
        """Release only this exact thread-local ticket at native depth one."""
        lock = self.lock
        if self.thread != threading.get_ident():
            return False
        if getattr(lock._local, "ticket", None) is not self:
            return True
        if lock._native._is_owned():
            if lock._native._recursion_count() != 1:
                return False
            lock._native.release()
        lock._local.ticket = None
        return True

    def finish(self):
        """Recover finite release faults before delivering the first exact interruption."""
        failure = None
        traceback = None
        while True:
            try:
                if not self.recover():
                    return False
                break
            except BaseException as interrupted:
                if failure is None:
                    failure = interrupted
                    traceback = BaseException.__traceback__.__get__(interrupted)
        if failure is not None:
            raise BaseException.with_traceback(failure, traceback) from None
        return True

    def __exit__(self, kind, error, traceback):
        """Keep the exact ticket reachable if native exit is interrupted."""
        if not self.recover():
            raise RuntimeError("retry lock release has no exact owner")


class _RecoverableRunnerLock:
    """Provide nonrecursive exclusion with thread-isolated release responsibility."""

    def __init__(self):
        """Use native owner/depth facts rather than a global locked-state inference."""
        self._native = threading.RLock()
        self._local = threading.local()

    def _acquire_scope(self, scope, blocking=True, timeout=-1):
        """Publish the exact ticket before native acquire can complete."""
        if (type(scope) is not _RetryLockScope or scope.lock is not self
                or scope.thread != threading.get_ident()):
            raise RuntimeError("runner lock acquire has no exact owner")
        if getattr(self._local, "ticket", None) is not None or self._native._is_owned():
            raise RuntimeError("runner lock is nonrecursive")
        self._local.ticket = scope
        try:
            acquired = self._native.acquire(blocking, timeout)
            if not acquired:
                scope.recover()
            return acquired
        except BaseException:
            scope.recover()
            raise

    def acquire(self, blocking=True, timeout=-1):
        """Preserve the native lock acquisition interface for ordinary callers."""
        return self._acquire_scope(_RetryLockScope(self, None), blocking, timeout)

    def release(self):
        """Reject foreign-thread release without touching native exclusion."""
        scope = getattr(self._local, "ticket", None)
        if scope is None or not scope.recover():
            raise RuntimeError("runner lock release has no exact owner")

    def locked(self):
        """Observe exclusion without using that observation as release authority."""
        if self._native._is_owned():
            return True
        if not self._native.acquire(False):
            return True
        self._native.release()
        return False

    def __enter__(self):
        """Acquire ordinary runner exclusion."""
        self.acquire()
        return self

    def __exit__(self, kind, error, traceback):
        """Release only the calling thread's ordinary ticket."""
        self.release()


def _retry_lock_scope(lock, invocation, journal):
    """Publish invocation release custody while preserving injected lock seams."""
    if type(lock) is not _RecoverableRunnerLock:
        return lock
    scope = _RetryLockScope(lock, invocation)
    journal[0] = scope
    return scope


def _private_mapping_authority():
    """Keep canonical snapshots and exact writer capability inside private closures."""
    snapshot = types.MappingProxyType({})
    capability = object()
    lock = _RecoverableRunnerLock()

    def observe():
        """Return the immutable canonical snapshot without exposing its backing map."""
        return snapshot

    def transition(key, expected, scope, changes=(), retire=()):
        """Publish one replacement only for the exact capability and current snapshot."""
        nonlocal snapshot
        if key is not capability:
            return False
        try:
            if not lock._acquire_scope(scope, False):
                return False
            if snapshot is not expected:
                return False
            replacement = type({})(snapshot)
            replacement.update(changes)
            for identity in retire:
                replacement.pop(identity, None)
            snapshot = types.MappingProxyType(replacement)
            return True
        finally:
            scope.finish()

    def controlled_transition(expected, changes=(), retire=()):
        """Expose the legal execution-frame seam without exporting its capability."""
        scope = _RetryLockScope(lock, capability)
        try:
            return transition(capability, expected, scope, changes, retire)
        finally:
            # Retain exact responsibility across the inner native-finally return gap.
            scope.finish()

    return observe, controlled_transition


def _private_retry_owner_authority():
    """Index exact weak custody identities without invoking equality or hashing hooks."""
    authorities = {}

    def initialize(custody):
        """Create one authority and retire only its exact weak reference on collection."""
        identity = id(custody)
        current = authorities.get(identity)
        if current is not None and current[0]() is custody:
            raise RuntimeError("retry token authority already initialized")
        observe, transition = _private_mapping_authority()
        if not transition(observe(), (("token", None),)):
            raise RuntimeError("retry token initialization lost snapshot authority")

        def retire(reference):
            """Never remove a replacement authority occupying a reused historical identity."""
            entry = authorities.get(identity)
            if entry is not None and entry[0] is reference:
                authorities.pop(identity, None)

        authorities[identity] = (weakref.ref(custody, retire), observe, transition)

    def exact(custody):
        """Require referent identity before granting snapshot or transition access."""
        entry = authorities.get(id(custody))
        if entry is None or entry[0]() is not custody:
            raise RuntimeError("retry token authority has no exact custody")
        return entry

    def observe(custody):
        """Return the immutable snapshot associated with the exact live custody."""
        return exact(custody)[1]()

    def transition(custody, expected, changes, retire=()):
        """Delegate every legal token writer to the same private snapshot transition."""
        return exact(custody)[2](expected, changes, retire)

    return initialize, observe, transition


_initialize_retry_owner, _observe_retry_owner, _transition_retry_owner = _private_retry_owner_authority()


def _commit_retry_owner(custody, token):
    """Use the single canonical transition for normal and interrupted fallback writers."""
    if not _transition_retry_owner(custody, _observe_retry_owner(custody), (("token", token),)):
        raise RuntimeError("retry token transition lost exact snapshot authority")



def _private_runner_authority():
    """Keep runner observer and writer custody outside mutable instance attributes."""
    authorities = {}

    def initialize(runner):
        """Register exact weak runner identity without equality or hashing callbacks."""
        identity = id(runner)
        current = authorities.get(identity)
        if current is not None and current[0]() is runner:
            raise RuntimeError("runner authority already initialized")

        def retire(reference):
            """Remove only the exact historical reference, never a replacement entry."""
            current = authorities.get(identity)
            if current is not None and current[0] is reference:
                authorities.pop(identity, None)

        authorities[identity] = (weakref.ref(runner, retire),
                                 _private_mapping_authority(), _private_mapping_authority())

    def access(runner, receipt):
        """Return authority only for the exact live runner referent."""
        entry = authorities.get(id(runner))
        if entry is None or entry[0]() is not runner:
            raise RuntimeError("runner authority has no exact owner")
        return entry[2 if receipt else 1]

    return initialize, access


_initialize_runner_authority, _access_runner_authority = _private_runner_authority()


class OwnedHookScriptRunner:
    """Execute one admission's entries through one existing backend authority."""

    def __init__(self, backend: IsolatedProcessBackend) -> None:
        """Bind recovery snapshots and storage debt to one backend authority."""
        if not isinstance(backend, IsolatedProcessBackend):
            raise TypeError("backend must be an IsolatedProcessBackend")
        self._backend = backend
        self._lock = _RecoverableRunnerLock()
        self._results: dict[int, HookScriptEntryResult] = {}
        self._storage: dict[str, TemporaryStorageOwner] = {}
        self._process_storage: dict[str, TemporaryStorageOwner] = {}
        _initialize_runner_authority(self)
        self._nonretained_observed_bytes = 0

    @property
    def _observe_prelaunch_storage(self):
        """Expose a read-only observer bound to exact private runner identity."""
        return _access_runner_authority(self, False)[0]

    @property
    def _transition_prelaunch_storage(self):
        """Expose the sole registry writer without a replaceable instance accessor."""
        return _access_runner_authority(self, False)[1]

    @property
    def _observe_retry_receipts(self):
        """Expose a read-only receipt observer from private canonical authority."""
        return _access_runner_authority(self, True)[0]

    @property
    def _transition_retry_receipts(self):
        """Expose the sole receipt writer without a compatibility second writer."""
        return _access_runner_authority(self, True)[1]

    @property
    def _retry_receipts(self):
        """Expose only the exact immutable receipt snapshot for compatibility reads."""
        return self._observe_retry_receipts()

    def _write_retry_receipts(self, changes=(), retire=()):
        """Route all receipt publication and retirement through the single writer."""
        if not self._transition_retry_receipts(self._retry_receipts, changes, retire):
            raise RuntimeError("retry receipt transition lost exact snapshot authority")

    @property
    def _prelaunch_storage(self):
        """Expose the exact immutable registry snapshot without a compatibility writer."""
        return self._observe_prelaunch_storage()

    def _write_prelaunch_storage(self, changes=(), retire=()):
        """Publish and retire registry identities through the sole canonical writer."""
        if not self._transition_prelaunch_storage(self._prelaunch_storage, changes, retire):
            raise RuntimeError("prelaunch registry transition lost exact snapshot authority")

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
        owner_state = object.__getattribute__(storage, "__dict__")
        execution_token = object()
        execution_lease = (execution_token,)
        custody._write_state(execution_lease=execution_lease)
        with self._lock:
            self._write_prelaunch_storage(((id(storage), custody),))
        lease = None
        record = None
        recovery_complete = False
        recovered = None
        primary = None
        primary_traceback = None
        try:
            allocated = storage.allocate()
            if allocated is not True:
                # A false allocation result is settled only with complete exact owner evidence.
                no_resource = (allocated is False and all(
                    name in owner_state and dict.get(owner_state, name) is None
                    for name in ("_candidate_path", "_path", "_uncertain_path", "_debt")
                ))
                if no_resource:
                    custody._write_state(storage_settled=True)
                else:
                    custody._write_state(pending=True, storage_alias=dict.get(owner_state, "_debt"))
                    self._remember_storage(storage)
                return self._publish(initial, HookStatus.ERROR, "hook_script_startup_failed")
            custody._write_state(storage_alias=owner_state["_debt"])
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
            custody._write_state(record=record)
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
            except (KeyboardInterrupt, SystemExit, asyncio.CancelledError) as interrupted:
                primary = interrupted
                primary_traceback = BaseException.__traceback__.__get__(interrupted)
                try:
                    if lease is not None:
                        try:
                            custody._write_state(recovering=True)
                            custody._write_state(pending=True)
                            recovered = self._preserve_interrupted(initial, record, storage, started)
                            custody._write_state(pending=not recovered.cleanup_confirmed)
                            recovery_complete = True
                        finally:
                            custody._write_state(recovering=False)
                except BaseException:
                    # Abandoned recovery must preserve the primary and release exclusion.
                    custody._write_state(recovering=False)
                    if custody.storage_settled:
                        custody._write_state(pending=False)
                        recovery_complete = True
                raise
            except Exception:
                if lease is None:
                    return self._finish_storage(initial, storage)
                current = self._preserve_interrupted(initial, record, storage, started)
                self._set_result(current)
                return current
        except BaseException as interrupted:
            if primary is not None and lease is not None:
                try:
                    custody._write_state(recovering=False)
                    if all(owner_state[name] is None for name in ("_path", "_uncertain_path", "_debt")):
                        custody._write_state(storage_settled=True)
                    custody._write_state(pending=not custody.storage_settled)
                    if owner_state["_debt"] is not None:
                        custody._write_state(reconciliation_pending=False)
                except BaseException:
                    try:
                        for attempt in range(3):
                            try:
                                # Read prebound native authority without retrying the failed observer.
                                custody._write_state(recovering=False)
                                if (owner_state["_path"] is None
                                        and owner_state["_uncertain_path"] is None
                                        and owner_state["_debt"] is None):
                                    custody._write_state(storage_settled=True)
                                custody._write_state(pending=not custody.storage_settled)
                                if owner_state["_debt"] is not None:
                                    custody._write_state(reconciliation_pending=False)
                                break
                            except BaseException:
                                # Exact responsibility remains armed until publication completes.
                                continue
                    finally:
                        try:
                            self._reconcile_custody(custody)
                        finally:
                            raise BaseException.with_traceback(primary, primary_traceback) from None
                raise BaseException.with_traceback(primary, primary_traceback) from None
            if lease is not None or (record is not None and record.process is not None):
                # Retain exact ordered recovery even when the inner publication failed.
                if not recovery_complete:
                    custody._write_state(pending=True)
                raise
            primary = interrupted
            primary_traceback = BaseException.__traceback__.__get__(interrupted)
            with self._lock:
                # Publish responsibility before interruptible recovery authority writes.
                try:
                    custody._write_state(pending=True)
                    custody._write_state(execution_owner=execution_token)
                    custody._write_state(storage_alias=owner_state.get("_debt") or custody.storage_alias)
                except BaseException:
                    # Complete this invocation's handoff without repeating failed overrides.
                    try:
                        custody._write_state(pending=True, execution_owner=execution_token, storage_alias=dict.get(owner_state, "_debt") or _observe_retry_owner(custody).get("storage_alias"))
                    except BaseException:
                        raise BaseException.with_traceback(primary, primary_traceback) from None
            try:
                self._remember_storage(storage)
            except BaseException:
                # The pre-armed exact owner survives failed debt publication.
                pass
            try:
                if storage.cleanup():
                    self._forget_storage(storage)
                    custody._write_state(pending=False)
            except BaseException:
                # Preserve the primary interruption and exact retryable custody.
                pass
            raise
        finally:
            try:
                try:
                    with self._lock:
                        # Unpublished responsibility is not proof of exact owner settlement.
                        if primary is not None and not all(
                            name in owner_state and dict.get(owner_state, name) is None
                            for name in ("_path", "_uncertain_path", "_debt")
                        ):
                            custody._write_state(pending=True, storage_alias=dict.get(owner_state, "_debt") or _observe_retry_owner(custody).get("storage_alias"))
                        if custody.execution_owner is execution_token:
                            if custody.release_complete:
                                custody._write_state(pending=False)
                            custody._write_state(execution_owner=None)
                except BaseException:
                    # Withdraw only native authority owned by this recovery invocation.
                    with self._lock:
                        if _observe_retry_owner(custody).get("execution_owner") is execution_token:
                            custody._write_state(execution_owner=None)
                        if _observe_retry_owner(custody).get("release_complete"):
                            custody._write_state(pending=False)
                    if primary is None:
                        raise
            finally:
                terminal_error = None
                terminal_traceback = None
                # Withdraw only the independently preregistered invocation lease.
                with self._lock:
                    lease_owned = (_observe_retry_owner(custody).get("execution_lease") is execution_lease
                                   and _valid_execution_lease(execution_lease)
                                   and execution_lease[0] is execution_token)
                    if lease_owned:
                        try:
                            custody._write_state(execution_lease=(None,))
                        except BaseException as interrupted:
                            # Settle exact responsibility before propagating teardown failure.
                            if custody.execution_lease is execution_lease and execution_lease[0] is execution_token:
                                custody._write_state(execution_lease=(None,))
                            if primary is None:
                                terminal_error = interrupted
                                terminal_traceback = BaseException.__traceback__.__get__(interrupted)
                    release_verified = (lease_owned and _execution_lease_inactive(custody)
                                        and (_observe_retry_owner(custody).get("release_complete") is True
                                             or _observe_retry_owner(custody).get("storage_settled") is True))
                    try:
                        if release_verified and not custody.pending and self._prelaunch_storage.get(id(storage)) is custody:
                            self._write_prelaunch_storage(retire=(id(storage),))
                    except BaseException as interrupted:
                        if primary is None and terminal_error is None:
                            terminal_error = interrupted
                            terminal_traceback = BaseException.__traceback__.__get__(interrupted)
                        try:
                            if release_verified and not custody.pending and self._prelaunch_storage.get(id(storage)) is custody:
                                self._write_prelaunch_storage(retire=(id(storage),))
                        except BaseException:
                            # Bypass failed registry overrides, retaining exact identity authority.
                            registry = self._prelaunch_storage
                            if release_verified and not custody.pending and registry.get(id(storage)) is custody:
                                self._write_prelaunch_storage(retire=(id(storage),))
                        if primary is not None:
                            raise BaseException.with_traceback(primary, primary_traceback) from None
                if terminal_error is not None:
                    raise BaseException.with_traceback(terminal_error, terminal_traceback) from None

    def _reconcile_custody(self, custody: _StorageCustody) -> None:
        """Publish exact completion or an enumerable observation obligation once."""
        state = custody
        custody._write_state(reconciliation_pending=True)
        custody._write_state(recovering=False)
        custody._write_state(pending=True)
        owner = custody.owner.__dict__
        names = ("_path", "_uncertain_path", "_debt")
        if any(name not in owner for name in names):
            return
        if any(owner[name] is not None for name in names):
            custody._write_state(reconciliation_pending=False)
            return
        custody._write_state(storage_settled=True)
        custody._write_state(pending=False)
        custody._write_state(reconciliation_pending=False)

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
                if not custody.pending or custody.recovering or custody.retry_owner is not None or custody.execution_owner is not None or not _execution_lease_inactive(custody):
                    owners.pop(owner_id, None)
                    continue
                if custody.reconciliation_pending and custody.record is not None:
                    record = custody.record
                    process.setdefault(record.debt_id, CleanupDebt(
                        record.debt_id, "process", None if record.process is None else record.process.pid,
                        "exact settlement observation remains unresolved",
                    ))
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
                for debt in (owners[owner_id].cleanup_debts() or (
                    (self._prelaunch_storage[owner_id].storage_alias,)
                    if owner_id in self._prelaunch_storage
                    and self._prelaunch_storage[owner_id].storage_alias is not None else ()
                ))
            )
        return (*process.values(), *storage)

    def retry_cleanup(self, debt_id: str) -> bool:
        """Drive first completion and repeated recovery from exact private custody."""
        failure_custody = [None]
        lock_custody = [None]
        invocation = self._retry_cleanup_invocation(debt_id, failure_custody, lock_custody)
        next(invocation)
        # Only handler cleanup and reentry are trusted; all preparation stays protected.
        while True:
            try:
                try:
                    scope = lock_custody[0]
                    if scope is not None:
                        if (type(scope) is not _RetryLockScope or scope.invocation is not invocation
                                or not scope.recover()):
                            raise RuntimeError("retry lock has no exact invocation custody")
                    evidence = failure_custody[0]
                    if evidence is not None:
                        if not (type(evidence) is tuple and len(evidence) == 3
                                and evidence[0] is invocation
                                and isinstance(evidence[1], BaseException)
                                and type(evidence[2]) is types.TracebackType):
                            prepared = RuntimeError("retry failure has no exact invocation custody")
                            break
                        prepared = BaseException.with_traceback(evidence[1], evidence[2])
                        break
                    try:
                        invocation.send(invocation)
                    except StopIteration as completed:
                        outcome = completed.value
                    else:
                        raise RuntimeError("retry invocation yielded unexpectedly")
                    if failure_custody[0] is not None:
                        continue
                    if type(outcome) is _RetryFailure:
                        raise RuntimeError("retry failure has no exact invocation custody")
                    return outcome
                except BaseException as interrupted:
                    # Human-approved capture/registration; never overwrite published custody.
                    if failure_custody[0] is None:
                        failure_custody[0] = (
                            invocation, interrupted,
                            BaseException.__traceback__.__get__(interrupted),
                        )
                    evidence = failure_custody[0]
                    if (type(evidence) is tuple and len(evidence) == 3
                            and evidence[0] is invocation
                            and isinstance(evidence[1], BaseException)
                            and type(evidence[2]) is types.TracebackType
                            and interrupted is not evidence[1]):
                        _note_retry_interruption(evidence[1], "failure delivery", interrupted)
            except BaseException:
                # No required bookkeeping: trusted stack cleanup exits directly to reentry.
                pass
        # Retirement and native departure form the approved final trusted transition.
        failure_custody[0] = None
        raise prepared from None

    def _retry_cleanup_invocation(self, debt_id: str, failure_custody=None, lock_custody=None):
        """Own exact retry exclusion until cleanup and identity release complete."""
        lock_custody = [None] if lock_custody is None else lock_custody
        invocation = yield
        if type(invocation) is not types.GeneratorType or invocation.gi_frame is not sys._getframe():
            raise ValueError("retry lifecycle must be this exact invocation")
        token = object()
        selected = None
        primary = None
        primary_traceback = None
        try:
            with _retry_lock_scope(self._lock, invocation, lock_custody):
                for custody in self._prelaunch_storage.values():
                    state = object.__getattribute__(custody, "__dict__")
                    proof = custody.retry_handback
                    alias = state.get("storage_alias")
                    record = state.get("record")
                    exact = ((isinstance(alias, CleanupDebt) and alias.debt_id == debt_id)
                             or (isinstance(record, LaunchRecord) and record.debt_id == debt_id))
                    if not exact:
                        debt = _observed_storage_debt(custody.owner)
                        exact = isinstance(debt, CleanupDebt) and debt.debt_id == debt_id
                    if (exact and type(proof) is tuple and len(proof) == 3
                            and self._retry_receipts.get(id(custody)) is proof
                            and proof[0] is custody and type(proof[1]) is object
                            and custody.retry_owner is proof[1]
                            and type(proof[2]) is types.GeneratorType
                            and proof[2].gi_code is OwnedHookScriptRunner._retry_cleanup_invocation.__code__
                            and proof[2].gi_frame is None
                            and state.get("execution_owner") is None
                            and _execution_lease_inactive(custody)
                            and self._prelaunch_storage.get(id(custody.owner)) is custody):
                        _commit_retry_owner(custody, None)
                if any((c.recovering or c.retry_owner is not None or c.execution_owner is not None or not _execution_lease_inactive(c)) and c.record is not None and c.record.debt_id == debt_id
                       for c in self._prelaunch_storage.values()):
                    return False
                for custody in self._prelaunch_storage.values():
                    if not custody.recovering and custody.retry_owner is None and custody.execution_owner is None and _execution_lease_inactive(custody):
                        continue
                    alias = custody.storage_alias
                    if isinstance(alias, CleanupDebt) and alias.debt_id == debt_id:
                        return False
                    debt = _observed_storage_debt(custody.owner)
                    if isinstance(debt, CleanupDebt) and debt.debt_id == debt_id:
                        return False
                pending = tuple(c for c in self._prelaunch_storage.values() if c.pending and not c.recovering and c.retry_owner is None and c.execution_owner is None and _execution_lease_inactive(c))
                process_custody = next((c for c in pending if c.record is not None
                                        and (c.record.debt_id == debt_id or (
                                            c.reconciliation_pending and c.storage_alias is not None
                                            and c.storage_alias.debt_id == debt_id))), None)
                storage = self._storage.get(debt_id)
                if any((c.recovering or c.retry_owner is not None or c.execution_owner is not None or not _execution_lease_inactive(c)) and c.owner is storage
                       for c in self._prelaunch_storage.values()):
                    return False
                for custody in pending:
                    if custody.reconciliation_pending and custody.record is not None:
                        continue
                    if not self._storage_ready(custody):
                        if storage is custody.owner:
                            storage = None
                        continue
                    if (any(debt.debt_id == debt_id for debt in custody.owner.cleanup_debts())
                            or (custody.record is None and custody.storage_alias is not None
                                and custody.storage_alias.debt_id == debt_id)):
                        storage = custody.owner
                selected = process_custody
                if storage is not None:
                    selected = next((c for c in pending if c.owner is storage), selected)
                if selected is not None:
                    debt = _observed_storage_debt(selected.owner)
                    if isinstance(debt, CleanupDebt):
                        selected._write_state(storage_alias=debt)
                    # Publish recovery proof before exposing interruptible retry authority.
                    receipt = (selected, token, invocation)
                    self._write_retry_receipts(((id(selected), receipt),))
                    selected._write_handback(receipt)
                    selected._write_retry_owner(token)
                    selected._write_state(reconciliation_pending=True)
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
                self._reconcile_custody(process_custody)
                if process_custody.reconciliation_pending:
                    return False
                if process_custody.storage_settled:
                    self._forget_storage(storage)
                    return True
                process_custody._write_state(reconciliation_pending=True)
                if not storage.cleanup():
                    return False
                self._forget_storage(storage)
                return True
            if not self._backend.retry_cleanup(debt_id):
                return False
            with _retry_lock_scope(self._lock, invocation, lock_custody):
                storage = self._process_storage.get(debt_id)
            if storage is None:
                return True
            self._remember_storage(storage)
            if not storage.cleanup():
                return False
            self._forget_storage(storage)
            return True
        except BaseException as interrupted:
            primary = interrupted
            primary_traceback = BaseException.__traceback__.__get__(interrupted)
            if failure_custody is not None:
                failure_custody[0] = (invocation, primary, primary_traceback)
            raise
        finally:
            try:
                if selected is not None:
                    released = False
                    try:
                        with _retry_lock_scope(self._lock, invocation, lock_custody):
                            if (self._prelaunch_storage.get(id(selected.owner)) is selected
                                    and selected.retry_owner is token):
                                owner_state = selected.owner.__dict__
                                if "_debt" in owner_state and owner_state["_debt"] is not None:
                                    selected._write_state(reconciliation_pending=False)
                                selected._write_state(pending=True)
                                selected._write_retry_owner(None)
                                if (selected.release_complete is True
                                        and selected.execution_owner is None
                                        and _execution_lease_inactive(selected)
                                        and self._prelaunch_storage.get(id(selected.owner)) is selected):
                                    selected._write_handback(None)
                                    self._write_retry_receipts(retire=(id(selected),))
                                    self._write_prelaunch_storage(retire=(id(selected.owner),))
                                    released = True
                    finally:
                        # Only this invocation may withdraw its exact retry authority.
                        state = object.__getattribute__(selected, "__dict__")
                        if (self._prelaunch_storage.get(id(selected.owner)) is selected
                                and selected.retry_owner is token):
                            _commit_retry_owner(selected, None)
                        # Never replace a cleanup/finalizer exception with a completion value.
                        if sys.exc_info()[0] is None and not released:
                            return False
            except BaseException as interrupted:
                if primary is None:
                    primary = interrupted
                    primary_traceback = BaseException.__traceback__.__get__(interrupted)
                    if failure_custody is not None:
                        failure_custody[0] = (invocation, primary, primary_traceback)
                else:
                    # Text diagnostics do not create primary/secondary exception graph edges.
                    _note_retry_interruption(primary, "finalizer", interrupted)
            finally:
                # Retain exact invocation withdrawal after both fallible disarm paths.
                if selected is not None:
                    try:
                        terminal_state = object.__getattribute__(selected, "__dict__")
                        if (self._prelaunch_storage.get(id(selected.owner)) is selected
                                and selected.retry_owner is token):
                            _commit_retry_owner(selected, None)
                    except BaseException as terminal_interruption:
                        if primary is None:
                            # Publish before the fallible generator completion carrier.
                            terminal_traceback = BaseException.__traceback__.__get__(terminal_interruption)
                            if failure_custody is not None:
                                failure_custody[0] = (invocation, terminal_interruption, terminal_traceback)
                            return _RetryFailure(
                                terminal_interruption,
                                BaseException.__traceback__.__get__(terminal_interruption),
                            )
                        _note_retry_interruption(primary, "terminal handback", terminal_interruption)
            if primary is not None:
                return _RetryFailure(primary, primary_traceback)

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
            self._forget_storage(storage)
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
        custody = self._prelaunch_storage.get(id(storage))
        owner_state = object.__getattribute__(storage, "__dict__")
        journal = custody
        if journal is not None:
            custody._write_state(reconciliation_pending=True)
        try:
            if storage.cleanup():
                if custody is not None:
                    custody._write_state(storage_settled=True)
                return result
        finally:
            # The exact owner's revoked authority survives an interrupted cleanup return.
            if journal is not None and all(
                owner_state[name] is None for name in ("_path", "_uncertain_path", "_debt")
            ):
                custody._write_state(storage_settled=True)
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
            custody = self._prelaunch_storage.get(id(storage))
            if custody is not None and (custody.retry_owner is not None or custody.execution_owner is not None
                                        or not _execution_lease_inactive(custody)):
                custody._write_state(release_complete=True)
            else:
                if custody is not None:
                    custody._write_handback(None)
                    self._write_retry_receipts(retire=(id(custody),))
                self._write_prelaunch_storage(retire=(id(storage),))

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
