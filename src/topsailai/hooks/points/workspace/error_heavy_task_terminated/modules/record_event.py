"""Record one heavy-task hard termination event.

Author: DawsonLin
"""

import logging

from topsailai.events import record_event

logger = logging.getLogger(__name__)

EVENT_TYPE = "heavy_task.terminated"
SOURCE = "hooks.heavy_task_terminated"


def main(**payload):
    """Record the validated metadata; a recording failure never replaces the error."""
    try:
        record_event(event_type=EVENT_TYPE, source=SOURCE,
                     payload=dict(payload), flush=True)
    except Exception:
        logger.warning("heavy_task_terminated_event_record_failed")
        return {"recorded": False}
    return {"recorded": True}


__all__ = ["main", "EVENT_TYPE", "SOURCE"]
