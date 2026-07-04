'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-12-26
  Purpose: Provides file locking functionality for thread-safe operations
'''

import logging
import os
import sys
from contextlib import contextmanager

from topsailai.utils.file_tool import (
    ctxm_file_lock,
    delete_file,
    ctxm_try_file_lock,
    ctxm_wait_flock,
)
from topsailai.utils import (
    env_tool,
)

from . import folder_constants


logger = logging.getLogger(__name__)


def init():
    """
    Initialize the lock directory structure.

    This function ensures that the lock directory specified by FOLDER_LOCK
    exists. If the directory doesn't exist, it will be created.

    Note: This function is called automatically when the module is imported.

    Returns:
        None
    """
    os.makedirs(folder_constants.FOLDER_LOCK, exist_ok=True)


# Initialize lock directory on module import
init()


class YieldData(object):
    """ save data for yield """
    def __init__(self, **kwargs):
        self.data = kwargs
        return

    def get(self, k:str):
        """ get value """
        return self.data.get(k)


@contextmanager
def FileLock(name: str):
    """
    Context manager for file-based locking.

    This function provides a thread-safe file locking mechanism using
    the underlying ctxm_file_lock utility. It automatically handles
    lock file creation, acquisition, and release.

    Args:
        name (str): The name of the lock. If the name doesn't end with
                   ".lock", the extension will be automatically added.
                   The lock file will be created in the FOLDER_LOCK directory.

    Yields:
        fd: A file descriptor (writeable) representing the acquired lock.

    Raises:
        AssertionError: If the name parameter is empty or None.

    Example:
        >>> with FileLock("my_resource"):
        ...     # Critical section - only one process can execute this at a time
        ...     perform_thread_safe_operation()

    Note:
        - The lock file is automatically managed and does not need to be
          manually deleted
        - This uses file-based locking which works across processes
        - The lock is released automatically when exiting the context
    """
    # Validate that the lock name is provided
    assert name, "Lock name cannot be empty"

    # Ensure the lock name has the correct extension
    if not name.endswith(".lock"):
        name += ".lock"

    # Construct the full path to the lock file
    file_path = folder_constants.FOLDER_LOCK + "/" + name

    # Acquire the lock and yield control to the critical section
    with ctxm_file_lock(file_path) as fd:
        try:
            yield fd
        finally:
            delete_file(file_path)

    # Lock is automatically released when context exits
    # No need to manually delete the lock file
    return


@contextmanager
def ctxm_try_session_lock(session_id:str=None, timeout:int=None, to_delete_lock_file:bool=None):
    """
    yield YieldData(session_id, fp, msg)
      if exists file operation object, session is locked, else None for locking failed.
    """
    if not session_id:
        session_id = env_tool.get_session_id()

    lock_file = None
    if session_id:
        lock_name = session_id.replace("/", ".").replace(" ", ".") + ".lock"
        lock_file = os.path.join(folder_constants.FOLDER_LOCK, lock_name)

    if not timeout:
        timeout = env_tool.EnvReaderInstance.get("TOPSAILAI_SESSION_LOCK_WAIT_TIMEOUT", default=60, formatter=int)
    timeout = max(1, timeout)

    if to_delete_lock_file is None:
        to_delete_lock_file = env_tool.EnvReaderInstance.check_bool(
            "TOPSAILAI_SESSION_LOCK_FILE_NEED_DELETE", True
        )

    msg = ""
    with ctxm_wait_flock(lock_file, to_delete_lock_file=to_delete_lock_file, timeout=timeout) as fp:
        if session_id and not fp:
            msg = f"session is busy: [{session_id}]"

        yield YieldData(session_id=session_id, fp=fp, msg=msg)

    return


def _resolve_project_workspace(project_workspace: str | None = None) -> str | None:
    """Resolve the project workspace path from argument or environment."""
    if project_workspace:
        return project_workspace
    return os.getenv("TOPSAILAI_PROJECT_WORKSPACE") or os.getenv("TOPSAILAI_PROJECT_FOLDER") or None


def _get_project_workspace_lock_enabled() -> bool:
    """Return whether the project workspace startup lock is enabled.

    Defaults to enabled when the variable is unset.
    """
    value = os.getenv("TOPSAILAI_PROJECT_WORKSPACE_LOCK_ENABLED")
    if value is None:
        return True
    return env_tool.is_true(value)


def _get_project_workspace_lock_timeout(default: float = 300.0) -> float:
    """Return the prompt timeout for the project workspace lock action.

    Empty, unset, or invalid values fall back to *default*.
    """
    value = os.getenv("TOPSAILAI_PROJECT_WORKSPACE_LOCK_TIMEOUT")
    if not value:
        return default
    try:
        timeout = float(value)
        return timeout if timeout > 0 else default
    except (TypeError, ValueError):
        return default


def _prompt_for_lock_action(lock_file: str, prompt_timeout: float) -> str:
    """Prompt the user to choose an action when the workspace lock is contested.

    Uses pipe-based input when ``TOPSAILAI_INPUT_PIPE_ENABLED`` is set, so
    the prompt works with the ``/send`` command. Otherwise reads directly from
    the terminal with a timeout, which is simpler and more reliable for a
    one-shot startup prompt than always creating a named pipe.

    Returns one of "exit", "continue", or "wait". On timeout or empty input,
    returns "wait".
    """
    from topsailai.workspace.input_tool import input_from_pipe_session
    from topsailai.utils.input_tool import input_with_timeout

    prompt = (
        f"Project workspace is locked by another process: {lock_file}\n"
        f"Choose: [exit / continue / wait] (default: wait, timeout: {int(prompt_timeout)}s) "
    )

    try:
        if env_tool.is_input_pipe_enabled():
            answer = input_from_pipe_session(
                timeout=prompt_timeout,
                single_line=True,
                prompt=prompt,
                cleanup_pipe=False,
            )
        else:
            answer = input_with_timeout(
                prompt=prompt,
                timeout=prompt_timeout,
                default="wait",
            )
    except TimeoutError:
        logger.warning("Project workspace lock prompt timed out; defaulting to wait")
        return "wait"
    except Exception as exc:
        logger.warning("Project workspace lock prompt failed: %s; defaulting to wait", exc)
        return "wait"

    answer = (answer or "").strip().lower()
    if not answer:
        return "wait"

    if answer in ("exit", "e", "quit", "q"):
        return "exit"
    if answer in ("continue", "c", "skip"):
        return "continue"
    if answer in ("wait", "w"):
        return "wait"

    # Unknown input defaults to wait, matching the timeout behavior.
    logger.warning("Unknown lock action '%s'; defaulting to wait", answer)
    return "wait"


@contextmanager
def ctxm_project_workspace_lock(
    project_workspace: str | None = None,
    prompt_timeout: float | None = None,
):
    """Acquire an advisory lock for the project workspace.

    This lock is intended for agent startup only. It is called from
    ``agent_shell.get_agent_chat()`` when ``TOPSAILAI_PROJECT_WORKSPACE`` is
    configured, so that only one agent process at a time actively operates on
    the project workspace.

    ``llm_shell`` is a pure chat interface without tool calls, so it does not
    modify the project workspace and therefore should NOT use this lock. Do not
    integrate ``ctxm_project_workspace_lock`` into ``llm_shell.get_llm_chat()``.

    If the lock is already held, the user is prompted via
    ``input_from_pipe_session`` to choose ``exit``, ``continue``, or ``wait``.
    On prompt timeout the default choice is ``wait``.

    Args:
        project_workspace: Optional project workspace path. If not provided,
            resolved from ``TOPSAILAI_PROJECT_WORKSPACE`` or
            ``TOPSAILAI_PROJECT_FOLDER``.
        prompt_timeout: Optional timeout in seconds for the prompt. If not
            provided, read from ``TOPSAILAI_PROJECT_WORKSPACE_LOCK_TIMEOUT``
            (default 300).

    Yields:
        bool: ``True`` if the lock is held, ``False`` if the user chose to
        continue without the lock.
    """
    project_workspace = _resolve_project_workspace(project_workspace)
    if not project_workspace:
        yield False
        return

    if not _get_project_workspace_lock_enabled():
        yield False
        return

    lock_dir = os.path.join(project_workspace, ".topsailai")
    try:
        os.makedirs(lock_dir, exist_ok=True)
    except OSError as exc:
        logger.warning("Cannot create project workspace lock directory %s: %s; skipping lock", lock_dir, exc)
        yield False
        return

    lock_file = os.path.join(lock_dir, "project_workspace.lock")
    timeout = prompt_timeout if prompt_timeout is not None else _get_project_workspace_lock_timeout()

    while True:
        with ctxm_try_file_lock(lock_file) as fp:
            if fp is not None:
                logger.debug("Acquired project workspace lock: %s", lock_file)
                try:
                    yield True
                finally:
                    logger.debug("Releasing project workspace lock: %s", lock_file)
                    delete_file(lock_file)
                return

        action = _prompt_for_lock_action(lock_file, timeout)

        if action == "exit":
            logger.info("User chose to exit because project workspace lock is held: %s", lock_file)
            sys.exit(1)

        if action == "continue":
            logger.warning("Continuing without project workspace lock: %s", lock_file)
            yield False
            return

        # action == "wait": try to acquire the lock with a blocking wait.
        with ctxm_wait_flock(lock_file, timeout=int(timeout), to_delete_lock_file=True) as fp:
            if fp is not None:
                logger.debug("Acquired project workspace lock after wait: %s", lock_file)
                try:
                    yield True
                finally:
                    logger.debug("Releasing project workspace lock: %s", lock_file)
                    delete_file(lock_file)
                return

        # Still not acquired; loop back and prompt again.
        logger.debug("Project workspace lock still held after wait: %s", lock_file)


@contextmanager
def ctxm_void(*_, **__):
    """ void
    yield YieldData
    """
    yield YieldData()
    return
