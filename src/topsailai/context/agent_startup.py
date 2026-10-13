"""Coordinate startup completion between an agent and auxiliary workers."""

from __future__ import annotations

import threading


class AgentStartupState:
    """Publish one terminal startup result to a waiting worker."""

    def __init__(self) -> None:
        """Initialize a pending startup state."""
        self._lock = threading.Lock()
        self._settled = threading.Event()
        self._state = "pending"

    @property
    def started(self) -> bool:
        """Return whether startup completed successfully."""
        with self._lock:
            return self._state == "started"

    def mark_started(self) -> None:
        """Publish successful startup completion."""
        with self._lock:
            if self._state != "pending":
                return
            self._state = "started"
            self._settled.set()

    def cancel(self) -> None:
        """Cancel a startup that cannot complete."""
        with self._lock:
            if self._state != "pending":
                return
            self._state = "cancelled"
            self._settled.set()

    def wait(self, timeout: float = 300.0) -> bool:
        """Wait for startup completion and return true only when started."""
        self._settled.wait(timeout)
        return self.started
