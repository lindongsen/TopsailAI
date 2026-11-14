"""Per-subscriber writer thread for the event channel.

Each subscriber gets its own writer thread so a slow or dead subscriber can only
delay itself. The writer drains the subscriber queue and pushes frames; a failed
send ends the thread, which is how a broken link stops sending.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-12
Purpose: Push queued events to one subscriber
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from topsailai.events.subscribers.subscriber import Subscriber
from topsailai.workspace.event_channel.connection import EventConnection
from topsailai.workspace.event_channel.protocol import encode_event

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL = 0.05
DEFAULT_BATCH_SIZE = 64


class EventWriter(threading.Thread):
    """Drain one subscriber queue and push each event over its connection.

    Attributes:
        subscriber: Subscriber whose queue is drained.
        connection: Link used to push frames.
        poll_interval: Seconds to wait between queue checks.
        batch_size: Maximum events pushed per drain.
    """

    def __init__(
        self,
        subscriber: Subscriber,
        connection: EventConnection,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ):
        super().__init__(
            name=f"EventWriter-{subscriber.subscriber_id}", daemon=True
        )
        self.subscriber = subscriber
        self.connection = connection
        self.poll_interval = poll_interval
        self.batch_size = batch_size
        self._stop_event = threading.Event()

    def stop(self) -> None:
        """Ask the writer to stop after its current iteration."""
        self._stop_event.set()

    def run(self) -> None:
        """Push queued events until stopped or the link fails.

        The thread is a daemon owned by one subscriber, so an unexpected failure
        must end only this writer. It is logged instead of escaping, because an
        unhandled exception in a thread would otherwise be reported as a process
        level error even though the channel is designed to tolerate loss.
        """
        try:
            self._drain_loop()
        except Exception:
            logger.warning(
                "event channel writer failed for subscriber %s",
                self.subscriber.subscriber_id,
                exc_info=True,
            )

    def _drain_loop(self) -> None:
        """Drain the subscriber queue and push frames until stopped."""
        while not self._stop_event.is_set():
            events = self.subscriber.drain(self.batch_size)
            if not events:
                self._stop_event.wait(self.poll_interval)
                continue
            for event in events:
                if self._stop_event.is_set():
                    return
                if not self.connection.send(encode_event(event.to_dict())):
                    logger.info(
                        "event channel writer stopped for subscriber %s: link closed",
                        self.subscriber.subscriber_id,
                    )
                    return

    def join_and_stop(self, timeout: Optional[float] = 2.0) -> None:
        """Stop the writer and wait for the thread to finish."""
        self.stop()
        if self.is_alive():
            self.join(timeout)
