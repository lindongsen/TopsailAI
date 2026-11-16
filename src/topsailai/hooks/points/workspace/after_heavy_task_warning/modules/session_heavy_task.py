"""Persist one heavy-task advisory warning into the session row.

Author: DawsonLin

The heavy-task counter on ``HeavyTaskBase`` is per-turn by design, so the
session-level total cannot be derived from it. This module increments the
session column at the moment the advisory is actually delivered.

The event is rare, so one write per warning is acceptable and keeps the count
exact. A failed write is logged and skipped: statistics must never interrupt
the turn.
"""

from topsailai.logger.log_chat import logger
from topsailai.utils import env_tool


def main(**payload):
    """Increment the session warning counter; never raise."""
    try:
        session_id = env_tool.get_session_id()
        if not session_id:
            return {"recorded": False}
        from topsailai.context import ctx_manager

        session_mgr = ctx_manager.get_session_manager()
        if session_mgr is None:
            return {"recorded": False}
        applied = session_mgr.accumulate_session_metrics(
            session_id=session_id, heavy_task_warning_count=1,
        )
        return {"recorded": bool(applied)}
    except Exception:
        logger.warning("heavy_task_warning_count_persist_failed", exc_info=True)
        return {"recorded": False}


__all__ = ["main"]
