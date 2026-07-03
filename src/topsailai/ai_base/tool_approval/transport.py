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
    from collections.abc import Callable

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
    decision maker.

    When a custom agent-runtime input-with-timeout function is registered in
    thread-local storage (for example, the workspace pipe reader installed by
    ``pre_run_set_agent_runtime_input``), ``send_request()`` uses that function
    even in non-TTY environments. This ensures approval prompts can be answered
    through the same session pipe or other input mechanism that the agent chat
    loop uses.
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

    def _read_stdin_input(
        self,
        instance: "ToolApprovalInstance",
        *,
        input_func: "Callable[[str, float | None], str] | None" = None,
    ) -> None:
        """
        Background worker that reads one line of input and resolves the instance.

        This delegates to the agent-runtime input-with-timeout function when one
        is registered in thread-local storage; otherwise it falls back to
        :func:`topsailai.utils.input_tool.input_with_timeout` so the terminal is
        configured for visible echo and the read can time out without blocking
        forever.

        Args:
            instance: The approval instance to resolve.
            input_func: Optional input callable to use. When omitted, the
                thread-local ``agent_runtime_input_with_timeout`` function is
                used if available, otherwise ``input_with_timeout`` is used.
        """
        from topsailai.utils.input_tool import input_with_timeout
        from topsailai.utils.thread_local_tool import get_agent_runtime_input_with_timeout

        prompt = (
            f"\n[APPROVAL REQUEST] {instance.id}\n"
            f"  Tool: {instance.tool_name}\n"
            f"  Args: {instance.tool_args}\n"
            f"  Timeout: {instance.timeout}s\n"
            "  Type 'approve'(yes) or 'deny'(no): "
        )

        if input_func is None:
            input_func = get_agent_runtime_input_with_timeout()

        try:
            if input_func is not None:
                line = input_func(prompt, instance.timeout)
            else:
                line = input_with_timeout(
                    prompt=prompt,
                    timeout=instance.timeout,
                    stream=sys.stdin,
                    output=sys.stdout,
                )
        except EOFError:
            # Pipe closed or EOF marker reached without usable input; exit the
            # reader so the instance remains unresolved and wait_response()
            # can apply the configured timeout policy.
            return
        except TimeoutError:
            # Propagate the timeout so callers can detect it. The transport's
            # wait_response() will also expire and mark the instance as timed
            # out, but tests and custom callers may rely on the exception.
            raise

        if line is None:
            return

        decision = line.strip().lower()
        print(f"> {decision}")
        if decision in ("approve", "yes", "y"):
            instance.approve(by="user")
        elif decision in ("deny", "no", "n"):
            instance.deny(by="user")
        else:
            logger.warning("Unrecognized approval input '%s', treating as deny", decision)
            instance.deny(by="user")

    def send_request(self, instance: "ToolApprovalInstance") -> None:
        """Enqueue the instance for the decision maker and optionally prompt for input."""
        from topsailai.utils.thread_local_tool import get_agent_runtime_input_with_timeout

        event = threading.Event()
        with self._events_lock:
            self._response_events[instance.id] = event
        self._request_queue.put(instance)

        # Start an input reader when either:
        #   1. stdin is a TTY (classic interactive CLI approval), or
        #   2. a custom agent-runtime input-with-timeout function is registered
        #      (e.g. the workspace pipe reader). This is the path used by the
        #      agent chat loop when TOPSAILAI_INPUT_PIPE_ENABLED is active.
        input_func = get_agent_runtime_input_with_timeout()
        if sys.stdin.isatty() or input_func is not None:
            thread = threading.Thread(
                target=self._read_stdin_input,
                args=(instance,),
                kwargs={"input_func": input_func},
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
