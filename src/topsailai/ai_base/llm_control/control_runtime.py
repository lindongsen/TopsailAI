"""Session/PID flag staging for first-byte wait control. Author: DawsonLin."""
from contextlib import contextmanager
import logging
import os
import sys
from pathlib import Path
from threading import RLock

_LOG = logging.getLogger(__name__)
_FLAG_LOCK = RLock()


class LLMRequestedRetryError(Exception):
    """Retry the current request within its original attempt budget."""


def _paths(session_id, pid):
    """Resolve only this session/process's two control markers."""
    from topsailai.workspace.folder_constants import FOLDER_WORKSPACE_TASK
    from topsailai.workspace.folder_utils import get_interrupt_flag_path
    interrupt = Path(get_interrupt_flag_path(FOLDER_WORKSPACE_TASK, session_id, pid))
    return (interrupt.with_suffix(".fbt_waiting"), interrupt.with_suffix(".fbt_retry"))


def _remove(path):
    """Remove an owned marker idempotently and log actual deletion."""
    try:
        path.unlink()
    except FileNotFoundError:
        return
    _LOG.info("Removed first-byte control marker: %s", path)


def stage_retry(session_id, pid):
    """Write a flag only during a current wait; acceptance is not execution."""
    with _FLAG_LOCK:
        waiting, retry = _paths(session_id, pid)
        if not waiting.exists():
            return False
        retry.touch()
        return True


def consume_retry(session_id, pid):
    """Consume one flag without replaying it on subsequent ticks."""
    with _FLAG_LOCK:
        _, retry = _paths(session_id, pid)
        if not retry.exists():
            return False
        _remove(retry)
        return True


@contextmanager
def first_byte_wait_scope():
    """Bound flag admission and cleanup to the existing coordinator wait."""
    from topsailai.utils.thread_local_tool import get_agent_object
    from topsailai.utils import env_tool
    agent = get_agent_object()
    if agent is None:
        yield
        return
    waiting, retry = _paths(env_tool.get_session_id() or "topsailai", os.getpid())
    with _FLAG_LOCK:
        waiting.parent.mkdir(parents=True, exist_ok=True)
        _remove(retry)
        waiting.touch()
    try:
        yield
    finally:
        primary = sys.exc_info()[1]
        with _FLAG_LOCK:
            for path in (waiting, retry):
                try:
                    _remove(path)
                except OSError as error:
                    _LOG.exception("Failed to remove first-byte marker: %s", path)
                    if primary is None:
                        primary = error
                    elif primary is not error:
                        primary.add_note("First-byte marker cleanup failed")
        if primary is not None and sys.exc_info()[1] is None:
            raise primary
