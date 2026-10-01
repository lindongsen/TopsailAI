"""RED regression for diagnostics shutdown with a full observer queue."""

from __future__ import annotations

import threading

from topsailai.hooks.diagnostics import DiagnosticBuffer


def test_first_close_self_terminates_observer_after_full_queue_is_released() -> None:
    """A lost sentinel must not require a second close to terminate the observer."""
    entered = threading.Event()
    release = threading.Event()
    callback_records: list[str] = []

    def observer(record: dict[str, object]) -> None:
        """Block the first callback so one later record fills the queue."""
        callback_records.append(str(record["kind"]))
        entered.set()
        assert release.wait(2)

    diagnostics = DiagnosticBuffer(capacity=1, observer=observer)
    try:
        diagnostics.publish("running")
        assert entered.wait(1)
        diagnostics.publish("queued")
        diagnostics.publish("overflow")

        before_close = diagnostics.drain(10)
        preexisting_drop = next(
            int(record["count"])
            for record in before_close
            if record.get("kind") == "diagnostics_dropped"
        )
        assert preexisting_drop == 3

        diagnostics.close(0.02)
        assert diagnostics._thread is not None
        assert diagnostics._thread.is_alive()
        release.set()
        diagnostics._thread.join(1)
        assert not diagnostics._thread.is_alive(), (
            "observer required a second-close sentinel after the first close returned"
        )
        assert callback_records == ["running"]

        after_close = diagnostics.drain(10)
        shutdown_drop = next(
            int(record["count"])
            for record in after_close
            if record.get("kind") == "diagnostics_dropped"
        )
        assert shutdown_drop == 1
        diagnostics.close(0.02)
    finally:
        release.set()
        if diagnostics._thread is not None and diagnostics._thread.is_alive():
            diagnostics.close(0.2)
            diagnostics._thread.join(1)
        assert diagnostics._thread is None or not diagnostics._thread.is_alive()
