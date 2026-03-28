'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-12-26
  Purpose: Provides file locking functionality for thread-safe operations
'''

import os
from contextlib import contextmanager

from topsailai.utils.file_tool import (
    ctxm_file_lock,
    delete_file,
    ctxm_wait_flock,
)

from . import folder_constants


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
def ctxm_try_session_lock(session_id:str=None, timeout=60):
    """
    yield YieldData(session_id, fp, msg)
      if exists file operation object, session is locked, else None for locking failed.
    """
    if not session_id:
        session_id = os.getenv("SESSION_ID")

    lock_file = None
    if session_id:
        lock_name = session_id.replace("/", ".").replace(" ", ".") + ".lock"
        lock_file = os.path.join(folder_constants.FOLDER_LOCK, lock_name)

    msg = ""
    with ctxm_wait_flock(lock_file, to_delete_lock_file=True, timeout=timeout) as fp:
        if session_id and not fp:
            msg = f"session is busy: [{session_id}]"

        yield YieldData(session_id=session_id, fp=fp, msg=msg)

    return

@contextmanager
def ctxm_void(*_, **__):
    """ void
    yield YieldData
    """
    yield YieldData()
    return
