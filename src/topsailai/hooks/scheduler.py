"""Bounded delivery scheduling for the unified hooks dispatcher."""

from __future__ import annotations

from collections import deque
import threading
import time
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Callable, Generic, TypeVar

from topsailai.hooks.process_state import WorkerResult

_ResultT = TypeVar("_ResultT")


@dataclass(slots=True)
class ScheduledWork(Generic[_ResultT]):
    """Track one admitted host operation and its finite queue ownership."""

    work_id: int
    scope_id: str
    size_bytes: int
    future: Future[_ResultT]
    operation: Callable[[], _ResultT]
    cancellation_result: Callable[[], _ResultT]
    state: str = "queued"
    slot_released: bool = False
    deadline_timer: threading.Timer | None = None


class HookScheduler:
    """Run blocking isolated deliveries behind reconfigurable finite limits."""

    def __init__(
        self,
        workers: int,
        queue_items: int,
        queue_bytes: int,
        *,
        enabled: bool = True,
    ) -> None:
        """Create finite delivery and host-queue capacity without plugin workers."""
        limits = (workers, queue_items, queue_bytes)
        if any(type(value) is not int or value <= 0 for value in limits):
            raise ValueError("scheduler limits must be positive integers")
        if type(enabled) is not bool:
            raise ValueError("scheduler enabled must be a boolean")
        self._worker_limit = workers
        self._executor: tuple[threading.Thread, ...] | None = () if enabled else None
        self._binding_active: dict[tuple[str, str], int] = {}
        self._binding_slots: set[tuple[str, str]] = set()
        self._quarantined_debts: set[str] = set()
        self._active_deliveries = 0
        self._running_work = 0
        self._queue_items = queue_items
        self._queue_bytes = queue_bytes
        self._queued_items = 0
        self._queued_bytes = 0
        self._next_work_id = 0
        self._work: dict[int, ScheduledWork[object]] = {}
        self._waiting: deque[int] = deque()
        self._lock = threading.RLock()
        self._changed = threading.Condition(self._lock)
        self._closed = False
        self._admission_enabled = enabled

    def reconfigure(
        self,
        *,
        enabled: bool,
        workers: int,
        queue_items: int,
        queue_bytes: int,
    ) -> bool:
        """Publish limits transactionally and lazily grow workers only for queued work."""
        with self._lock:
            if self._closed:
                raise RuntimeError("scheduler is closed")
            previous = (
                self._admission_enabled,
                self._worker_limit,
                self._queue_items,
                self._queue_bytes,
            )
            self._admission_enabled = enabled
            self._worker_limit = workers
            self._queue_items = queue_items
            self._queue_bytes = queue_bytes
            if enabled and self._waiting and not self._ensure_workers_locked():
                (
                    self._admission_enabled,
                    self._worker_limit,
                    self._queue_items,
                    self._queue_bytes,
                ) = previous
                self._changed.notify_all()
                return False
            self._changed.notify_all()
            return True

    def reconcile_cleanup_debts(self, active_debt_ids: set[str]) -> None:
        """Release quarantined capacity only after exact cleanup debt disappears."""
        with self._lock:
            self._quarantined_debts.intersection_update(active_debt_ids)
            self._changed.notify_all()

    def execute(
        self,
        scope_id: str,
        binding_id: str,
        max_concurrency: int,
        operation: Callable[[], WorkerResult],
    ) -> WorkerResult:
        """Execute one admitted delivery within dynamic worker and binding capacity."""
        key = (scope_id, binding_id)
        with self._lock:
            if self._closed:
                return WorkerResult("cancelled", error_category="runtime_closed")
            if self._active_deliveries + len(self._quarantined_debts) >= self._worker_limit:
                return WorkerResult("rejected_capacity", error_category="global_capacity")
            active_for_binding = self._binding_active.get(key, 0)
            if active_for_binding >= max_concurrency:
                return WorkerResult("rejected_capacity", error_category="binding_capacity")
            self._active_deliveries += 1
            self._binding_active[key] = active_for_binding + 1
            self._binding_slots.add(key)
        debt_id: str | None = None
        try:
            result = operation()
            if not result.cleanup_confirmed:
                debt_id = result.cleanup_debt or f"untracked:{id(result)}"
            return result
        finally:
            with self._lock:
                self._active_deliveries -= 1
                remaining = self._binding_active.get(key, 1) - 1
                if remaining:
                    self._binding_active[key] = remaining
                else:
                    self._binding_active.pop(key, None)
                if debt_id is not None:
                    self._quarantined_debts.add(debt_id)
                self._changed.notify_all()

    def submit(
        self,
        scope_id: str,
        size_bytes: int,
        operation: Callable[[], _ResultT],
        *,
        cancellation_result: Callable[[], _ResultT],
        deadline_seconds: float | None = None,
        deadline_result: Callable[[], _ResultT] | None = None,
    ) -> ScheduledWork[_ResultT] | None:
        """Admit one bounded host operation into the removable owner queue."""
        if type(size_bytes) is not int or size_bytes <= 0:
            return None
        with self._lock:
            if (
                self._closed
                or not self._admission_enabled
                or self._queued_items >= self._queue_items
                or self._queued_bytes + size_bytes > self._queue_bytes
            ):
                return None
            if self._executor is None:
                self._executor = ()
            self._queued_items += 1
            self._queued_bytes += size_bytes
            self._next_work_id += 1
            work_id = self._next_work_id
            result_future: Future[_ResultT] = Future()
            work: ScheduledWork[_ResultT] = ScheduledWork(
                work_id,
                scope_id,
                size_bytes,
                result_future,
                operation,
                cancellation_result,
            )
            self._work[work_id] = work
            self._waiting.append(work_id)
            if not self._ensure_workers_locked():
                self._remove_waiting(work_id)
                self._work.pop(work_id, None)
                work.state = "cancelled"
                self._release_queue_slot(work)
                self._changed.notify_all()
                return None
            if deadline_seconds is not None and deadline_result is not None:
                delay = max(0.0, deadline_seconds - time.monotonic())
                work.deadline_timer = threading.Timer(
                    delay, self._expire_work, args=(work_id, deadline_result)
                )
                work.deadline_timer.daemon = True
                work.deadline_timer.start()
            result_future.add_done_callback(
                lambda completed: self._finish_work(work_id, completed)
            )
            self._changed.notify_all()
            return work

    def cancel_scope(self, scope_id: str) -> int:
        """Cancel queued operations owned by one scope and return their count."""
        with self._lock:
            candidates = [work for work in self._work.values() if work.scope_id == scope_id]
            cancelled = sum(1 for work in candidates if self._cancel_queued(work))
            self._changed.notify_all()
            return cancelled

    def release_scope(self, scope_id: str) -> None:
        """Release idle per-binding state after the owning scope closes."""
        with self._lock:
            keys = [key for key in self._binding_slots if key[0] == scope_id]
            for key in keys:
                self._binding_slots.discard(key)

    def close(self, timeout_seconds: float) -> tuple[ScheduledWork[object], ...]:
        """Stop admission, cancel queued work, and boundedly await running operations."""
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        with self._lock:
            self._closed = True
            self._admission_enabled = False
            for work in tuple(self._work.values()):
                self._cancel_queued(work)
            self._changed.notify_all()
            while self._work:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._changed.wait(remaining)
            return tuple(self._work.values())

    def _ensure_workers_locked(self) -> bool:
        """Lazily grow workers and retain ownership only for successfully started threads."""
        if self._executor is None or not self._admission_enabled or self._closed:
            return False
        current = len(self._executor)
        if current >= self._worker_limit:
            return True
        for index in range(current, self._worker_limit):
            thread = threading.Thread(
                target=self._worker_loop,
                name=f"hook-delivery-{index}",
                daemon=True,
            )
            try:
                thread.start()
            except RuntimeError:
                return False
            self._executor += (thread,)
        return True

    def _worker_loop(self) -> None:
        """Take live queue entries only while dynamic execution capacity permits."""
        while True:
            with self._lock:
                while not self._closed and (
                    not self._waiting or self._running_work >= self._worker_limit
                ):
                    self._changed.wait()
                if self._closed and not self._waiting:
                    return
                if not self._waiting:
                    continue
                work_id = self._waiting.popleft()
                work = self._work.get(work_id)
                if work is None or work.state != "queued":
                    continue
                work.state = "running"
                self._running_work += 1
                self._release_queue_slot(work)
                if work.deadline_timer is not None:
                    work.deadline_timer.cancel()
            try:
                self._run_work(work)
            finally:
                with self._lock:
                    self._running_work -= 1
                    self._changed.notify_all()

    @staticmethod
    def _run_work(work: ScheduledWork[_ResultT]) -> None:
        """Execute one running operation and publish its terminal result."""
        try:
            result = work.operation()
        except BaseException as exc:
            if not work.future.done():
                work.future.set_exception(exc)
        else:
            if not work.future.done():
                work.future.set_result(result)

    def _expire_work(
        self, work_id: int, deadline_result: Callable[[], _ResultT]
    ) -> None:
        """Remove and complete one still-queued operation at its immutable deadline."""
        with self._lock:
            work = self._work.get(work_id)
            if work is None or work.state != "queued":
                return
            self._remove_waiting(work_id)
            work.state = "expired"
            self._release_queue_slot(work)
        try:
            result = deadline_result()
        except BaseException as exc:
            work.future.set_exception(exc)
        else:
            work.future.set_result(result)

    def _cancel_queued(self, work: ScheduledWork[object]) -> bool:
        """Remove queued work and complete it with a structured cancellation result."""
        if work.state != "queued":
            return False
        self._remove_waiting(work.work_id)
        work.state = "cancelled"
        self._release_queue_slot(work)
        try:
            result = work.cancellation_result()
        except BaseException as exc:
            work.future.set_exception(exc)
        else:
            work.future.set_result(result)
        return True

    def _remove_waiting(self, work_id: int) -> None:
        """Remove one exact retained queue reference while holding the lock."""
        try:
            self._waiting.remove(work_id)
        except ValueError:
            pass

    def _finish_work(self, work_id: int, future: Future[object]) -> None:
        """Release completed host work and notify bounded close waiters."""
        del future
        with self._lock:
            work = self._work.pop(work_id, None)
            if work is not None:
                self._remove_waiting(work_id)
                if work.deadline_timer is not None:
                    work.deadline_timer.cancel()
                work.state = "done"
                self._release_queue_slot(work)
            self._changed.notify_all()

    def _release_queue_slot(self, work: ScheduledWork[object]) -> None:
        """Release one queue reservation exactly once while holding the lock."""
        if work.slot_released:
            return
        work.slot_released = True
        self._queued_items -= 1
        self._queued_bytes -= work.size_bytes
