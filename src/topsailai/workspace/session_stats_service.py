"""Process-owned best-effort statistics queue. Author: DawsonLin."""

import os
import threading
import weakref
from collections import deque
from dataclasses import dataclass
from uuid import uuid4

from topsailai.workspace.session_stats_projection import UINT, capture, encode
from topsailai.workspace.session_stats_writer import StatsWriter, StorageConfig


_model_ids = weakref.WeakKeyDictionary()
_model_ids_lock = threading.Lock()


def register_model(model):
    """Allocate lifetime identity outside checkpoints without changing model classes."""
    with _model_ids_lock:
        key = _model_ids.get(model)
        if key is None:
            key = uuid4().hex
            _model_ids[model] = key
        return key


@dataclass(frozen=True)
class ServiceConfig:
    """Explicit application-boundary limits; environment loading is deferred."""

    max_records: int = 64
    max_bytes: int = 262144
    max_bindings: int = 64

    def __post_init__(self):
        """Use safe defaults for malformed or unbounded capacity requests."""
        for key, default in (('max_records', 64), ('max_bytes', 262144), ('max_bindings', 64)):
            value = getattr(self, key)
            if type(value) is not int or not 1 <= value <= default:
                object.__setattr__(self, key, default)


class Attempt:
    """Execution-thread-owned one-shot observation, not a retry ticket."""

    def __init__(self, binding, sequence):
        """Initialize the admitted sequence outside delivery."""
        self.binding = binding
        self.sequence = sequence
        self.outcome = 'success'
        self.observed = False

    def determine(self, outcome):
        """Latch the first non-success outcome against later completion hooks."""
        if outcome not in ('success', 'failure', 'back', 'interrupt'):
            raise ValueError('invalid stats outcome')
        if not self.observed and self.outcome == 'success':
            self.outcome = outcome

    def deliver(self):
        """Mark before delivery so rejection or failure never causes duplicates."""
        if self.observed:
            return False
        self.observed = True
        return self.binding.offer(self.sequence, self.outcome)


class Binding:
    """Weak Agent ownership; queued data does not retain this token."""

    def __init__(self, service, agent, session, writer, execution_thread_exclusive=False):
        """Allocate immutable destination and identity outside checkpoints."""
        self.service = service
        self.agent_ref = weakref.ref(agent)
        self.agent_id = uuid4().hex
        self.session = session or 'topsailai'
        self.writer = writer
        self.closed = False
        self.sequence = 0
        self.owner_thread = threading.get_ident()
        self.exclusive = execution_thread_exclusive is True
        self.capture_lock = threading.Lock()
        self.models = []
        self.prepare()

    def authorized(self, agent):
        """Require explicit single-thread identity ownership, never infer atomicity."""
        return (self.exclusive and not self.closed and agent is not None
                and agent is self.agent_ref()
                and threading.get_ident() == self.owner_thread)

    def settle_authorized(self, agent):
        """Require Agent/thread ownership without promising model exclusivity."""
        return (not self.closed and agent is not None
                and agent is self.agent_ref()
                and threading.get_ident() == self.owner_thread)

    def prepare(self):
        """Register a pinned model reference outside the settlement checkpoint.

        Concurrent replacement or rename does not alter the pinned object identity.
        This does not grant the strict model-exclusivity authorization.
        """
        agent = self.agent_ref()
        if not self.settle_authorized(agent):
            return False
        model = agent.runtime.llm_model
        self.models[:] = [(ref, key) for ref, key in self.models if ref() is not None]
        if model is None or self.model_id(model) is not None:
            return True
        if len(self.models) >= 64:
            return False
        self.models.append((weakref.ref(model), register_model(model)))
        return True

    def model_id(self, model):
        """Find a registered weak model identity under a fixed 64-entry budget."""
        for ref, key in self.models:
            if ref() is model:
                return key
        return None

    def begin(self):
        """Admit a sequence, including attempts whose observations are dropped."""
        if self.closed or self.sequence == UINT:
            self.closed = True
            return None
        self.sequence += 1
        return Attempt(self, self.sequence)

    def offer(self, sequence, outcome):
        """Capture on the execution thread without I/O, logging or waiting."""
        service = self.service
        if self.closed or os.getpid() != service.pid:
            return False
        agent = self.agent_ref()
        if agent is None:
            self.closed = True
            return False
        try:
            record = capture(self, session_id=self.session, writer_id=service.writer_id,
                             agent_id=self.agent_id, sequence=sequence, outcome=outcome,
                             settle=True)
            line = encode(record)
        except Exception:
            return False
        return service.offer(self.writer, line) if line is not None else False

    def close(self):
        """Release this token without waiting or stopping the process worker."""
        self.closed = True
        self.service.reclaim()


_owner_ref = None
_owner_pid = os.getpid()
_owner_lock = threading.Lock()


class StatsService:
    """One daemon serializes B writes; use process_service for production sharing."""

    def __new__(cls, **kwargs):
        """Reject a second live writer, including direct constructor bypasses."""
        global _owner_ref, _owner_pid, _owner_lock
        pid = os.getpid()
        if _owner_pid != pid:
            _owner_pid, _owner_ref = pid, None
            _owner_lock = threading.Lock()
        with _owner_lock:
            owner = _owner_ref() if _owner_ref is not None else None
            if owner is not None and getattr(owner, 'pid', pid) == pid:
                worker = getattr(owner, 'worker', None)
                if owner.state != 'retired' or (worker is not None and worker.is_alive()):
                    raise RuntimeError('stats writer already owned by this process')
            instance = super().__new__(cls)
            instance.state = 'starting'
            _owner_ref = weakref.ref(instance)
            return instance

    def __init__(self, *, diagnostic, directory=None, config=ServiceConfig(),
                 storage=StorageConfig(), writer_factory=StatsWriter):
        """Bootstrap the worker explicitly outside any observation checkpoint."""
        try:
            self._initialize(diagnostic, directory, config, storage, writer_factory)
        except BaseException:
            with _owner_lock:
                self.stopping = True
                self.state = 'retired'
            raise

    def _initialize(self, diagnostic, directory, config, storage, writer_factory):
        """Construct outside the owner lock while retaining starting authority."""
        self.pid = os.getpid()
        self.writer_id = uuid4().hex
        self.config = config
        self.storage = storage
        self.directory = directory
        self.diagnostic = diagnostic
        self.writer_factory = writer_factory
        self.lock = threading.Lock()
        self.queue = deque()
        self.queued_bytes = 0
        self.bindings = []
        self.stopping = False
        self.worker = threading.Thread(target=self._run, daemon=True, name='session-stats')
        self.worker.start()

    def _reclaim_locked(self):
        """Bound reclamation by the live token table, even if worker is stalled."""
        self.bindings[:] = [b for b in self.bindings if not b.closed and b.agent_ref() is not None]

    def reclaim(self):
        """Try cleanup only; a busy close is reclaimed by later admission."""
        if os.getpid() != self.pid or not self.lock.acquire(blocking=False):
            return
        try:
            self._reclaim_locked()
        finally:
            self.lock.release()

    def bind(self, agent, session_id='', *, execution_thread_exclusive=False):
        """Bind outside execution; reject foreign inherited service authority."""
        if os.getpid() != self.pid:
            return None
        writer = self.writer_factory(session_id, diagnostic=self.diagnostic,
                                     directory=self.directory, config=self.storage)
        with self.lock:
            self._reclaim_locked()
            if self.stopping or len(self.bindings) >= self.config.max_bindings:
                return None
            binding = Binding(self, agent, session_id, writer, execution_thread_exclusive)
            self.bindings.append(binding)
            return binding

    def offer(self, writer, line):
        """Use a try-lock, not Queue.put_nowait's potentially waiting mutex."""
        if os.getpid() != self.pid or not self.lock.acquire(blocking=False):
            return False
        try:
            if self.stopping or len(self.queue) >= self.config.max_records:
                return False
            if self.queued_bytes + len(line) > self.config.max_bytes:
                return False
            self.queue.append((writer, line))
            self.queued_bytes += len(line)
            return True
        finally:
            self.lock.release()

    def _take(self):
        """Pop without holding any queue authority over storage or diagnostics."""
        with self.lock:
            if not self.queue:
                return None
            writer, line = self.queue.popleft()
            self.queued_bytes -= len(line)
            return writer, line

    def _run(self):
        """Authorize a launched worker; failed startup can never write later."""
        with _owner_lock:
            if self.state != 'starting':
                self.state = 'retired'
                return
            self.state = 'running'
        try:
            self._work()
        finally:
            with _owner_lock:
                self.state = 'retired'

    def _work(self):
        """Poll independently; blocked storage cannot own an admission lock."""
        idle = threading.Event()
        while not self.stopping:
            item = self._take()
            if item is None:
                idle.wait(0.01)
                continue
            writer, line = item
            try:
                writer.append(line)
            except Exception:
                try:
                    self.diagnostic('storage_failure', writer.path.name[:128])
                except Exception:
                    pass  # The independent diagnostic channel is itself best effort.

    def stop(self):
        """Request process-service retirement without drain, join or finalizer."""
        with _owner_lock:
            self.stopping = True
            if self.state != 'retired':
                self.state = 'stopping'


_service = None
_bootstrap_lock = threading.Lock()


def process_service(*, diagnostic, directory=None, config=ServiceConfig(), storage=StorageConfig()):
    """Bootstrap once per process outside checkpoints; fork rebuilds authority."""
    global _service, _bootstrap_lock
    if _service is not None and _service.pid != os.getpid():
        _service = None
        _bootstrap_lock = threading.Lock()
    with _bootstrap_lock:
        if _service is not None and _service.stopping and _service.worker.is_alive():
            raise RuntimeError('previous stats worker has not retired')
        if _service is None or _service.stopping:
            _service = StatsService(diagnostic=diagnostic, directory=directory,
                                    config=config, storage=storage)
        return _service
