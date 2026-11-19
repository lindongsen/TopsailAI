"""Automatic cleanup for temporary files in FOLDER_WORKSPACE_TASK.

This module ensures that transient runtime files created under
``FOLDER_WORKSPACE_TASK`` (``.task``, ``.stdout``, ``.pipe``) are removed
when the process exits, including abnormal exits caused by ``SIGINT`` or
``SIGTERM``.

Files are cleaned up via two mechanisms:

1. **Registered files** — callers register paths they create with
   :func:`register_cleanup_file`.  The registry is process-private, so
   deleting registered files is equivalent to deleting files owned by the
   current process.
2. **PID-scoped pipes** — session pipe filenames already embed the process
   ID (``{session_id}.{pid}.session.pipe``).  On exit the task folder is
   scanned for files matching the current PID and removed.

Normal exits are handled through :mod:`atexit`.  Abnormal exits are handled
by installing signal handlers for ``SIGINT`` and ``SIGTERM`` that chain to
the original handler.  Cleanup is only performed directly when the default
signal action would terminate the process; otherwise cleanup is deferred to
:mod:`atexit` so that a transient ``Ctrl+C`` which is caught by the
application does not remove task files while the process continues running.
"""

from __future__ import annotations

import atexit
import fnmatch
import logging
import os
import signal
import threading

from topsailai.utils import env_tool
from topsailai.utils.file_tool import delete_file
from topsailai.workspace.folder_constants import FOLDER_WORKSPACE_TASK
from topsailai.workspace.session_meta import (
    STATUS_COMPLETED,
    TASK_ARTIFACT_SUFFIXES,
    get_session_meta_path,
    read_session_meta_status,
)

logger = logging.getLogger(__name__)

_CLEANUP_FILES: set[str] = set()
_CLEANUP_FUNCS: list[callable] = []
_CLEANUP_LOCK = threading.Lock()

_ORIGINAL_SIGNAL_HANDLERS: dict[int, object] = {}
_SIGNALS_INSTALLED = False
_INSTALL_LOCK = threading.Lock()

_SESSION_META_PRINTED = False
_SESSION_META_PRINT_LOCK = threading.Lock()

def register_cleanup_file(file_path: str) -> None:
    """Register *file_path* for removal when the process exits.

    The path is normalized to an absolute path before registration.
    Registration is idempotent and thread-safe.
    """
    if not file_path:
        return
    abs_path = os.path.abspath(file_path)
    with _CLEANUP_LOCK:
        _CLEANUP_FILES.add(abs_path)
    _ensure_signal_handlers_installed()
    logger.debug("Registered task folder file for cleanup: %s", abs_path)


def register_cleanup_func(func: callable) -> None:
    """Register *func* to be invoked when the process exits.

    The callable is stored as-is and invoked during :func:`cleanup_task_folder`
    (which runs on process exit via :mod:`atexit` or the signal handler).
    Registration is idempotent and thread-safe.
    """
    if not callable(func):
        raise TypeError("func must be callable")
    with _CLEANUP_LOCK:
        if func not in _CLEANUP_FUNCS:
            _CLEANUP_FUNCS.append(func)
    _ensure_signal_handlers_installed()
    logger.debug("Registered cleanup function: %s", func)


def unregister_cleanup_file(file_path: str) -> None:
    """Remove *file_path* from the cleanup registry.

    Callers should unregister files they have already deleted so the exit
    cleanup does not attempt to remove them again.
    """
    if not file_path:
        return
    abs_path = os.path.abspath(file_path)
    with _CLEANUP_LOCK:
        _CLEANUP_FILES.discard(abs_path)


def _cleanup_pid_scoped_pipes(pid: int | None = None) -> None:
    """Remove session pipe files whose names include *pid*.

    Session pipes follow the naming convention
    ``{session_id}.{pid}.session.pipe``.  This function scans
    ``FOLDER_WORKSPACE_TASK`` and deletes any matching files.
    """
    if not os.path.isdir(FOLDER_WORKSPACE_TASK):
        return
    if pid is None:
        pid = os.getpid()
    pattern = f"*.{pid}.session.pipe"
    try:
        for name in os.listdir(FOLDER_WORKSPACE_TASK):
            if fnmatch.fnmatch(name, pattern):
                delete_file(os.path.join(FOLDER_WORKSPACE_TASK, name))
    except OSError as exc:
        logger.error("Failed to scan task folder for pid-scoped pipes: %s", exc)


# Session counters that prove at least one turn actually ran. A session whose
# counters are all zero never produced a transcript worth keeping.
_ACTIVITY_COUNTERS = ("turn_count", "llm_request_count", "tool_call_count", "total_tokens")


def _session_is_empty_by_counters(session_id: str) -> bool | None:
    """Return whether *session_id* recorded no activity, or None when unknown.

    The session table is the authority for emptiness: a session with no row
    never reached its first turn, and a row whose counters are all zero never
    completed one. ``None`` means the counters could not be read, so the caller
    must preserve the file instead of guessing.
    """
    try:
        from topsailai.context import ctx_manager

        session = ctx_manager.get_session_manager().get_session(session_id)
    except Exception as exc:
        logger.error("Failed to read session counters for %s: %s", session_id, exc)
        return None
    if session is None:
        return True
    for name in _ACTIVITY_COUNTERS:
        if getattr(session, name, 0) or 0:
            return False
    return True


def _cleanup_empty_session_stdout(pid: int | None = None) -> None:
    """Remove this process's session stdout files that recorded no activity.

    A session that starts and exits immediately leaves a stdout file and no
    session counters. Such a file has no diagnostic value, so it is removed on
    exit. A file belonging to a session that ran at least one turn is
    preserved, because it is the transcript the CLI reads after the process
    ends.
    """
    if not os.path.isdir(FOLDER_WORKSPACE_TASK):
        return
    if pid is None:
        pid = os.getpid()
    suffix = f".{pid}.session.stdout"
    try:
        names = os.listdir(FOLDER_WORKSPACE_TASK)
    except OSError as exc:
        logger.error("Failed to scan task folder for session stdout: %s", exc)
        return
    for name in names:
        if not name.endswith(suffix):
            continue
        session_id = name[: -len(suffix)]
        if not session_id:
            continue
        if _session_is_empty_by_counters(session_id) is not True:
            continue
        delete_file(os.path.join(FOLDER_WORKSPACE_TASK, name))


def _cleanup_completed_task_artifacts(pid: int | None = None) -> None:
    """Remove this process's task artifacts after a normal exit.

    A task artifact is a diagnostic record of one task execution. It is kept on
    every abnormal exit so the scene survives, and removed only when the session
    metadata proves the process ended normally. ``completed`` is that proof: a
    normal return and a deliberate exit command both write it, while an uncaught
    exception leaves ``running`` (rewritten to ``interrupted`` by the metadata
    finalizer) and a controlled database failure records ``error``.

    Only regular files carrying this process's ``{session_id}.{pid}.`` prefix are
    touched, so another process's artifacts and unrelated files are never
    removed.
    """
    if not os.path.isdir(FOLDER_WORKSPACE_TASK):
        return
    if pid is None:
        pid = os.getpid()
    session_id = env_tool.get_session_id() or "topsailai"
    if read_session_meta_status(session_id) != STATUS_COMPLETED:
        logger.debug(
            "Preserving task artifacts for session %s: the session did not end normally",
            session_id,
        )
        return
    prefix = f"{session_id}.{pid}."
    try:
        names = os.listdir(FOLDER_WORKSPACE_TASK)
    except OSError as exc:
        logger.error("Failed to scan task folder for task artifacts: %s", exc)
        return
    for name in names:
        if not name.startswith(prefix):
            continue
        if not name.endswith(TASK_ARTIFACT_SUFFIXES):
            continue
        path = os.path.join(FOLDER_WORKSPACE_TASK, name)
        try:
            if not os.path.isfile(path) or os.path.islink(path):
                continue
        except OSError as exc:
            logger.error("Cannot inspect task artifact %s: %s", path, exc)
            continue
        delete_file(path)


def cleanup_task_folder() -> None:
    """Remove all registered temporary files and PID-scoped pipes.

    This function is safe to call multiple times: the registry is cleared
    on the first call, making subsequent calls no-ops for registered files.
    """
    print_session_meta_files_on_exit()

    with _CLEANUP_LOCK:
        files = sorted(_CLEANUP_FILES)
        _CLEANUP_FILES.clear()
        funcs = list(_CLEANUP_FUNCS)
        _CLEANUP_FUNCS.clear()

    for file_path in files:
        delete_file(file_path)

    for func in funcs:
        try:
            func()
        except Exception as exc:
            logger.error("Error during cleanup function %s: %s", func, exc)

    _cleanup_pid_scoped_pipes()
    _cleanup_empty_session_stdout()
    _cleanup_completed_task_artifacts()


def print_session_meta_files_on_exit() -> None:
    """Print the current process's session ``.meta`` file before cleanup.

    The output is written directly to ``stdout`` in interactive mode so it is
    visible even when the process is exiting abnormally.  If the current
    process has no meta file, this function produces no output.  The operation
    is idempotent and thread-safe.
    """
    if not env_tool.is_interactive_mode():
        return

    global _SESSION_META_PRINTED
    with _SESSION_META_PRINT_LOCK:
        if _SESSION_META_PRINTED:
            return
        _SESSION_META_PRINTED = True

    meta_path = get_session_meta_path()
    if not os.path.isfile(meta_path):
        return

    print(f"\n--- Session meta file: {meta_path} ---")
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            for line in f:
                print(line, end="")
    except OSError as exc:
        print(f"[Error reading {meta_path}: {exc}]")
    print("\n--- End of session meta file ---")


def _raise_signal(signum: int) -> None:
    """Re-raise *signum* in the current process.

    Prefers :func:`signal.raise_signal` when available and falls back to
    :func:`os.kill` for older Python versions.
    """
    if hasattr(signal, "raise_signal"):
        signal.raise_signal(signum)
    else:
        os.kill(os.getpid(), signum)


def _signal_handler(signum: int, frame) -> None:
    """Chain to the original signal handler.

    Cleanup is only performed directly when the default action will
    terminate the process.  For custom handlers (e.g. Python's default
    ``SIGINT`` handler that raises ``KeyboardInterrupt``), cleanup is
    deferred to :mod:`atexit` so that a caught ``Ctrl+C`` does not remove
    task files while the process continues running.
    """
    original = _ORIGINAL_SIGNAL_HANDLERS.get(signum)
    if original is not None:
        if original == signal.SIG_DFL:
            # Default action terminates the process; run cleanup before dying.
            signal.signal(signum, signal.SIG_DFL)
            try:
                cleanup_task_folder()
            except Exception as exc:
                logger.error("Error during signal cleanup: %s", exc)
            _raise_signal(signum)
            return
        if original == signal.SIG_IGN:
            signal.signal(signum, signal.SIG_IGN)
            return
        if callable(original):
            # Let the custom handler decide. If it exits the process,
            # atexit will run cleanup. If it returns, files stay intact.
            try:
                original(signum, frame)
            except Exception:
                pass
            return

    # No original handler recorded; treat as default.
    signal.signal(signum, signal.SIG_DFL)
    try:
        cleanup_task_folder()
    except Exception as exc:
        logger.error("Error during signal cleanup: %s", exc)
    _raise_signal(signum)


def _ensure_signal_handlers_installed() -> None:
    """Install atexit and signal handlers once.

    The function is idempotent.  It installs handlers for ``SIGINT`` and
    ``SIGTERM`` when supported by the platform, saving the original handlers
    so they can be chained.
    """
    global _SIGNALS_INSTALLED
    with _INSTALL_LOCK:
        if _SIGNALS_INSTALLED:
            return
        _SIGNALS_INSTALLED = True

        atexit.register(cleanup_task_folder)

        for signum in (signal.SIGINT, signal.SIGTERM):
            try:
                original = signal.signal(signum, _signal_handler)
                _ORIGINAL_SIGNAL_HANDLERS[signum] = original
                logger.debug("Installed task cleanup handler for signal %s", signum)
            except (ValueError, OSError) as exc:
                logger.debug("Could not install handler for signal %s: %s", signum, exc)


# Install handlers on module import so that any module creating task files is
# covered from the moment it imports this module.
_ensure_signal_handlers_installed()
