"""Bound one analysis execution to its original input owner.

Author: DawsonLin
"""

import logging
import threading

logger = logging.getLogger(__name__)


class InputMonitor:
    """Watch a detached target identity without launching another agent."""

    def __init__(self, snapshot, expected, interrupt, *, interval=0.2):
        """Inject observation and exact analysis interruption dependencies."""
        self.snapshot = snapshot
        self.pid = expected["pid"]
        self.created_at = expected["created_at"]
        self.interrupt = interrupt
        self.interval = interval
        self.stopped = threading.Event()
        self.invalidated = threading.Event()
        self.thread = threading.Thread(target=self._watch, name="analysis-input-monitor", daemon=True)

    def start(self):
        """Start exactly one watcher for this analysis lifecycle."""
        self.thread.start()

    def close(self):
        """Wait for watcher exit before permitting another analysis lifecycle."""
        self.stopped.set()
        if self.thread.ident is not None:
            self.thread.join()

    def input_is_current(self):
        """Revalidate input authority and never revive an invalidated analysis."""
        if self.invalidated.is_set() or self.stopped.is_set():
            return False
        rows, _ = self.snapshot()
        valid = any(row.get("pid") == self.pid
                    and row.get("ctime") == self.created_at
                    and row["status"] == "input" for row in rows)
        if not valid:
            self.invalidated.set()
        return valid

    def mark_delivered(self):
        """End this analysis authority immediately after a successful injection."""
        self.invalidated.set()

    def allows_send(self, pid):
        """Permit only the original input owner at the final sending boundary."""
        return (pid is None or pid == self.pid) and self.input_is_current()

    def _watch(self):
        """Interrupt once on confirmed invalidation; retry observation failures."""
        while not self.stopped.wait(self.interval):
            try:
                if not self.input_is_current() and not self.stopped.is_set():
                    self.interrupt()
                    return
            except Exception:
                logger.exception("analysis input monitor failed: target_pid=%s", self.pid)
