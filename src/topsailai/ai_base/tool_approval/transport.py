"""
Tool approval transport abstractions.

Transports move approval requests from the agent process to a decision maker
and back. The default implementation is an in-process queue suitable for
single-process agents and tests.
"""

from __future__ import annotations

import logging
import queue
import sys
import threading
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from topsailai.ai_base.tool_approval.instance import ToolApprovalInstance


logger = logging.getLogger(__name__)


class ApprovalTransport(ABC):
    """Abstract transport for tool approval requests."""

    @abstractmethod
    def send_request(self, instance: "ToolApprovalInstance") -> None:
        """Send a request to the decision maker."""

    @abstractmethod
    def wait_response(
        self, instance: "ToolApprovalInstance", *, timeout: float | None = None
    ) -> str:
        """Wait for the decision maker to resolve the request."""

    @abstractmethod
    def on_resolved(self, instance: "ToolApprovalInstance") -> None:
        """
        Called when an instance is resolved.

        Subclasses may override this to wake waiters or notify observers.
        """

    @abstractmethod
    def supports_external_resolution(self) -> bool:
        """
        Return True if this transport allows an external system to call
        instance.approve()/deny() while wait_response() is in progress.
        """


class LocalApprovalTransport(ApprovalTransport):
    """
    In-process approval transport backed by a queue.

    This transport is intended for single-process agents and tests. The
    decision maker polls ``get_request()`` and calls ``resolve()`` with the
    instance ID and decision.

    In addition, when running in an interactive terminal, ``send_request()``
    starts a short-lived background thread that reads a line from stdin and
    resolves the instance as ``approved`` or ``denied``. This makes the local
    transport usable for real CLI approval without requiring an external
    decision maker. In non-interactive environments the stdin thread is not
    started and the transport behaves as a pure queue.
    """

    _instance: "LocalApprovalTransport | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._request_queue: "queue.Queue[ToolApprovalInstance]" = queue.Queue()
        self._response_events: dict[str, threading.Event] = {}
        self._response_status: dict[str, str] = {}
        self._events_lock = threading.Lock()
        self._input_threads: dict[str, threading.Thread] = {}

    @classmethod
    def get_instance(cls) -> "LocalApprovalTransport":
        """Return the singleton local transport."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton. Useful for tests."""
        with cls._lock:
            cls._instance = None

    def _read_stdin_input(self, instance: "ToolApprovalInstance") -> None:
        """Background worker that reads one line from stdin and resolves the instance."""
        try:
            prompt = (
                f"\n[APPROVAL REQUEST] {instance.id}\n"
                f"  Tool: {instance.tool_name}\n"
                f"  Args: {instance.tool_args}\n"
                f"  Timeout: {instance.timeout}s\n"
                "  Type 'approve' or 'deny': "
            )
            sys.stdout.write(prompt)
            sys.stdout.flush()
            line = sys.stdin.readline()
        except Exception as exc:  # pragma: no cover - stdin may be unavailable
            logger.debug("Stdin read failed for approval %s: %s", instance.id, exc)
            return

        decision = line.strip().lower()
        if decision in ("approve", "yes", "y"):
            instance.approve(by="user")
        elif decision in ("deny", "no", "n"):
            instance.deny(by="user")
        else:
            logger.warning("Unrecognized approval input '%s', treating as deny", decision)
            instance.deny(by="user")

    def send_request(self, instance: "ToolApprovalInstance") -> None:
        """Enqueue the instance for the decision maker and optionally prompt stdin."""
        event = threading.Event()
        with self._events_lock:
            self._response_events[instance.id] = event
        self._request_queue.put(instance)

        if sys.stdin.isatty():
            thread = threading.Thread(
                target=self._read_stdin_input,
                args=(instance,),
                daemon=True,
                name=f"approval-stdin-{instance.id}",
            )
            with self._events_lock:
                self._input_threads[instance.id] = thread
            thread.start()

    def wait_response(
        self, instance: "ToolApprovalInstance", *, timeout: float | None = None
    ) -> str:
        """Block until the instance is resolved or the timeout expires."""
        with self._events_lock:
            event = self._response_events.get(instance.id)
        if event is None:
            return instance.status

        if timeout is None:
            event.wait()
        else:
            resolved = event.wait(timeout=timeout)
            if not resolved:
                instance.mark_timeout()
                return instance.STATUS_TIMEOUT

        with self._events_lock:
            status = self._response_status.pop(instance.id, instance.status)
        return status

    def on_resolved(self, instance: "ToolApprovalInstance") -> None:
        """Record the resolved status and wake any waiter."""
        with self._events_lock:
            self._response_status[instance.id] = instance.status
            event = self._response_events.pop(instance.id, None)
            self._input_threads.pop(instance.id, None)
        if event is not None:
            event.set()

    def get_request(self, *, timeout: float | None = None) -> "ToolApprovalInstance | None":
        """Return the next pending instance, or None if the queue is empty."""
        try:
            return self._request_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def resolve(self, instance_id: str, approved: bool) -> bool:
        """Resolve a pending instance by ID via the registry."""
        from topsailai.ai_base.tool_approval.registry import (
            get_pending_approval,
        )

        instance = get_pending_approval(instance_id)
        if instance is None:
            return False
        if approved:
            instance.approve()
        else:
            instance.deny()
        return True

    def supports_external_resolution(self) -> bool:
        """Local transport supports external resolution via instance.approve()/deny()."""
        return True
