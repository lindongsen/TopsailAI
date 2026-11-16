"""Persist one heavy-task hard termination into the session row.

Author: DawsonLin

``block_heavy_task()`` raises ``HeavyTaskError`` immediately after this point
runs, so the terminating turn never reaches the advisory warning hook. Counting
the two stages separately keeps "warned" and "killed" distinguishable.

A failed write is logged and skipped: statistics must never replace or suppress
``HeavyTaskError``.
"""

from topsailai.logger.log_chat import logger
from topsailai.utils import env_tool


def main(**payload):
    """Increment the session block counter; never raise."""
    try:
        session_id = env_tool.get_session_id()
        if not session_id:
            return {"recorded": False}
        from topsailai.context import ctx_manager

        session_mgr = ctx_manager.get_session_manager()
        if session_mgr is None:
            return {"recorded": False}
        applied = session_mgr.accumulate_session_metrics(
            session_id=session_id, heavy_task_block_count=1,
        )
        return {"recorded": bool(applied)}
    except Exception:
        logger.warning("heavy_task_block_count_persist_failed", exc_info=True)
        return {"recorded": False}


__all__ = ["main"]
