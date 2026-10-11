"""Armed recovery custody for unpublished Hook Point capture. Author: DawsonLin."""
from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass, replace
import pickle
import weakref
import threading

from topsailai.hooks.artifact_contracts import ArtifactDisposeResult
from topsailai.hooks.hook_point_plan_contracts import HookPointPlan


class HookPointCandidate:
    """Retain physical ownership independently of immutable semantic success."""
    def __init__(self, backend):
        """Arm bounded recovery before the first capture or child launch."""
        self._backend = backend
        self._capture_owner = None
        self._plan = None
        self._probe_debts = set()
        self._closed = False
        self._transferred = False
        self._publication_owner = None
        self._transfer_lock = threading.Lock()

    @property
    def plan(self):
        """Expose only a completed live unpublished plan."""
        if self._plan is None or self._closed:
            raise RuntimeError("candidate is not live and complete")
        return self._plan

    def transfer(self, registry, version):
        """Detach validated semantics and move cleanup rights exactly once."""
        with self._transfer_lock:
            if self._transferred or self._closed or type(self._plan) is not HookPointPlan:
                raise ValueError("candidate is not transferable")
            plan = replace(self._plan)
            if plan.fingerprint != self._plan.fingerprint or self._probe_debts:
                raise ValueError("candidate authority mismatch")
            owner = HookPointOwner(registry, PublishedHookPoint(plan, version), self)
            self._publication_owner = owner
            self._transferred = True
            self._closed = True
            return owner

    def retire(self):
        """Retain the legacy candidate retirement seam without a second plan owner."""
        return self.close()

    def cleanup_debts(self):
        """Inspect only exact debts introduced by this candidate's probe calls."""
        process = () if self._backend is None else tuple(d for d in self._backend.cleanup_debts() if d.debt_id in self._probe_debts)
        artifacts = () if self._capture_owner is None else self._capture_owner.cleanup_debts()
        return process + artifacts

    def retry_cleanup(self, debt_id):
        """Reject former caller authority after transfer to publication custody."""
        if self._transferred:
            return False
        return self._retry_cleanup(debt_id)

    def _retry_cleanup(self, debt_id):
        """Settle exact process debt before permitting captured-byte disposal."""
        if debt_id in self._probe_debts:
            if not self._backend.retry_cleanup(debt_id):
                return False
            self._probe_debts.discard(debt_id)
            result = self._dispose()
            return result.accepted and not result.cleanup_pending
        if self._probe_debts or self._capture_owner is None:
            return False
        if not any(d.debt_id == debt_id for d in self._capture_owner.cleanup_debts()):
            return False
        if not self._capture_owner.retry_cleanup(debt_id):
            return False
        result = self._dispose()
        return result.accepted and not result.cleanup_pending

    def close(self):
        """Invalidate semantics but retain every owner until cleanup confirms absence."""
        if self._transferred:
            return ArtifactDisposeResult(True, True)
        return self._dispose()

    def _dispose(self):
        """Dispose through the exact transferred or unpublished resource custodian."""
        already = self._closed
        self._closed = True
        if self._probe_debts:
            return ArtifactDisposeResult(False, already, True, ("probe_cleanup_pending",))
        if self._capture_owner is not None:
            result = self._capture_owner.close()
            if not result.accepted or result.cleanup_pending:
                return result
        return ArtifactDisposeResult(True, already)

    def __enter__(self):
        """Return an already-armed candidate for caller-controlled lifetime."""
        return self

    def __exit__(self, exc_type, exc, traceback):
        """Preserve body interruption and attach custody for unresolved cleanup."""
        try:
            result = self.close()
            if result.cleanup_pending:
                if exc is None:
                    raise CandidateBuildError("candidate_cleanup_pending", self)
                exc.recovery_owner = self
        except BaseException as error:
            if exc is None or (isinstance(exc, Exception) and not isinstance(error, Exception)):
                error.recovery_owner = self
                if exc is not None:
                    _preserve_body_diagnosis(exc, error)
                raise
            exc.recovery_owner = self
        if exc is not None and self.cleanup_debts():
            exc.recovery_owner = self
        return False


def _preserve_body_diagnosis(body, cleanup):
    """Keep body evidence while removing back edges to the propagated interrupt."""
    pending, seen = [body], set()
    while pending:
        error = pending.pop()
        if id(error) in seen:
            continue
        seen.add(id(error))
        for attribute in ("__cause__", "__context__"):
            descriptor = BaseException.__dict__[attribute]
            edge = descriptor.__get__(error)
            if edge is cleanup:
                suppression = BaseException.__dict__["__suppress_context__"]
                suppressed = suppression.__get__(error)
                descriptor.__set__(error, None)
                suppression.__set__(error, suppressed)
            elif edge is not None:
                pending.append(edge)
    BaseException.__dict__["__context__"].__set__(cleanup, body)


class CandidateBuildError(ValueError):
    """Return stable failure classification plus exact retryable resource custody."""
    def __init__(self, category, recovery_owner):
        """Keep recovery reachable without describing a partial semantic candidate."""
        super().__init__(category)
        self.category = category
        self.recovery_owner = recovery_owner


def _private_publication_authority():
    """Retain canonical bytes by exact weak identity, never by instance attributes."""
    records = {}
    lock = threading.RLock()

    def arm(identity, value):
        """Bind one fresh identity without equality hooks or replacement writers."""
        key = id(identity)
        with lock:
            if key in records:
                raise ValueError("publication identity already armed")
            def forget(reference):
                """Remove only the original weak record when its observer is collected."""
                with lock:
                    current = records.get(key)
                    if current is not None and current[0] is reference:
                        del records[key]
            records[key] = (weakref.ref(identity, forget), value)

    def observe(identity):
        """Reject copied or foreign identities rather than trusting matching fields."""
        with lock:
            record = records.get(id(identity))
            if record is None or record[0]() is not identity:
                raise ValueError("unknown publication identity")
            return record[1]

    return arm, observe


_arm_publication, _observe_publication = _private_publication_authority()


class PublishedHookPoint:
    """Expose a stable observer identity over private immutable canonical bytes."""
    __slots__ = ("__weakref__",)

    def __init__(self, plan, active_version):
        """Seal detached validated semantics without retaining an exposed child graph."""
        if type(plan) is not HookPointPlan or type(active_version) is not int or active_version < 1:
            raise ValueError("invalid publication snapshot")
        detached = replace(plan)
        _arm_publication(self, (pickle.dumps(detached, protocol=5), active_version))

    def __setattr__(self, name, value):
        """Reject ordinary snapshot writes while native writes have no backing slots."""
        raise FrozenInstanceError("cannot assign to publication snapshot")

    @property
    def plan(self):
        """Rebuild observations only from internally produced canonical bytes."""
        return pickle.loads(_observe_publication(self)[0])

    @property
    def active_version(self):
        """Read the exact admitted version independently of public observation graphs."""
        return _observe_publication(self)[1]


@dataclass(frozen=True, slots=True)
class HookPointPublicationResult:
    """Describe one publication decision without granting cleanup rights implicitly."""
    accepted: bool
    changed: bool
    generation: int
    snapshot: PublishedHookPoint | None = None
    previous: object | None = None
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HookPointReader:
    """Carry one exact admission; copies carry no release authority."""
    snapshot: PublishedHookPoint
    registry: object
    owner: object


@dataclass(frozen=True, slots=True)
class HookPointCleanupToken:
    """Retain captured bytes independently of a returned execution reader."""
    registry: object
    owner: object


class HookPointOwner:
    """Retain exact readers and execution cleanup until confirmed physical absence."""
    def __init__(self, registry, snapshot, candidate):
        """Arm disposal responsibility before candidate transfer publication."""
        _arm_publication(self, snapshot)
        self._registry = registry
        self._candidate = candidate
        self._lock = threading.Lock()
        self._cleanup_lock = threading.Lock()
        self._readers = {}
        self._execution = {}
        self._retired = False
        self._settled = False

    @property
    def snapshot(self):
        """Expose the canonical frozen snapshot without a second ordinary writer."""
        return _observe_publication(self)

    @property
    def entries(self):
        """Project captured Script membership without a separate semantic writer."""
        from topsailai.hooks.hook_script_discovery import HookScriptEntry
        return tuple(HookScriptEntry(item.captured_path, item.logical_name,
            item.identity.name) for item in self.snapshot.plan.default_script_hook.scripts)

    @property
    def hook_name(self):
        """Project the immutable Hook Point name."""
        return self.snapshot.plan.hook_point_name

    @property
    def options(self):
        """Project immutable legacy execution options."""
        return self.snapshot.plan.options

    @property
    def policy(self):
        """Project immutable legacy execution policy."""
        return self.snapshot.plan.execution_policy

    @property
    def owner(self):
        """Expose the retained capture compatibility observer, never clear early."""
        candidate = self._candidate
        return None if candidate is None else candidate._capture_owner

    def acquire(self, receiver=None):
        """Arm a new exact reader while the Registry publication lock is held."""
        with self._lock:
            if self._retired:
                return None
            reader = HookPointReader(self.snapshot, self._registry, self)
            if receiver is not None:
                receiver.append(reader)
            self._readers[id(reader)] = reader
            return reader

    def retain_cleanup(self, reader, custody=None):
        """Journal cleanup responsibility only for an exact current reader."""
        with self._lock:
            if self._readers.get(id(reader)) is not reader:
                return None
            token = HookPointCleanupToken(self._registry, self)
            if custody is not None:
                custody.token = token
            self._execution[id(token)] = token
            return token

    def release(self, token, *, execution=False):
        """Consume only the exact admission and perform disposal after unlock."""
        with self._lock:
            entries = self._execution if execution else self._readers
            if entries.get(id(token)) is not token:
                return False
            del entries[id(token)]
            ready = self._retired and not self._readers and not self._execution
        if ready:
            self._dispose()
        return True

    def retire(self):
        """Revoke new admission without clearing live or pending capture ownership."""
        with self._lock:
            self._retired = True
            ready = not self._readers and not self._execution
        if not ready:
            return ArtifactDisposeResult(False, False, True, ("reader_cleanup_pending",))
        return self._dispose()

    def _dispose(self):
        """Serialize exact cleanup outside Registry and reader locks."""
        with self._cleanup_lock:
            if self._settled:
                return ArtifactDisposeResult(True, True)
            result = self._candidate._dispose()
            if result.accepted and not result.cleanup_pending:
                self._settled = True
                self._candidate = None
            return result

    @property
    def settled(self):
        """Observe confirmed retirement without performing cleanup I/O."""
        with self._cleanup_lock:
            return self._settled

    def cleanup_debts(self):
        """Keep unresolved capture/process debt inspectable after active removal."""
        with self._cleanup_lock:
            return () if self._candidate is None else self._candidate.cleanup_debts()

    def retry_cleanup(self, debt_id):
        """Retry only a retired owner with no remaining reader or execution rights."""
        with self._lock:
            if not self._retired or self._readers or self._execution:
                return False
        with self._cleanup_lock:
            if self._candidate is None:
                return False
            if not self._candidate._retry_cleanup(debt_id):
                return False
        return self._dispose().accepted
