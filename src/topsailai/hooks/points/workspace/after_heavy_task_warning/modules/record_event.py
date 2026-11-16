"""Record one heavy-task advisory warning event.

Author: DawsonLin
"""

import logging

from topsailai.events import record_event

logger = logging.getLogger(__name__)

EVENT_TYPE = "heavy_task.warning"
SOURCE = "hooks.heavy_task_warning"


def main(**payload):
    """Record the validated metadata; a recording failure never interrupts the turn."""
    try:
        record_event(event_type=EVENT_TYPE, source=SOURCE,
                     payload=dict(payload), flush=True)
    except Exception:
        logger.warning("heavy_task_warning_event_record_failed")
        return {"recorded": False}
    return {"recorded": True}


__all__ = ["main", "EVENT_TYPE", "SOURCE"]
