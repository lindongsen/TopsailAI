'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-11-14
  Purpose: Resolve the project workspace for a session, preferring the
           environment and falling back to the persisted session record.
'''

import json
import logging
import os
import shutil
import signal
import subprocess
from collections import OrderedDict

logger = logging.getLogger(__name__)

PROJECT_WORKSPACE_ENV = "TOPSAILAI_PROJECT_WORKSPACE"
PROJECT_FOLDER_ENV = "TOPSAILAI_PROJECT_FOLDER"

# The fallback reads the persisted record through a CLI command instead of
# opening the session database, so this layer never depends on the storage
# schema or on a connection string that resolves against the working directory.
_LOOKUP_COMMAND = "topsailai_session_info"

# The command is a dispatcher wrapper, so the real worker is a grandchild.
# Killing only the direct child would leave that worker running, so the child is
# started as a group leader and the whole group is signalled on expiry.
_LOOKUP_TIMEOUT = 5
_LOOKUP_REAP_TIMEOUT = 2

# Successful lookups are cached per process. A miss is never cached, so a
# session record created later in the same process is still observable. The
# cache is bounded because a long-lived process may resolve many distinct
# sessions, and an unbounded map would grow without limit.
_LOOKUP_CACHE_MAX_ENTRIES = 256
_LOOKUP_CACHE: "OrderedDict[str, str]" = OrderedDict()


def _resolve_lookup_command() -> str | None:
    """Return the session-info command path, or ``None`` when unavailable.

    The command is normally discovered through ``PATH``. When it is not, the
    project ``bin/`` directory next to this package is used, so a process
    started with a minimal environment still resolves the workspace instead of
    silently degrading.
    """
    found = shutil.which(_LOOKUP_COMMAND)
    if found:
        return found
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidate = os.path.join(project_root, "bin", _LOOKUP_COMMAND)
    if os.path.isfile(candidate):
        return candidate
    return None


def _kill_process_group(process: "subprocess.Popen[str]") -> None:
    """Terminate the whole process group started for *process*.

    The group is signalled first so a grandchild worker cannot survive the
    timeout. The direct child is killed as a fallback when the group is already
    gone or cannot be signalled, and the reap is bounded so a stuck child cannot
    block the caller.
    """
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        process.kill()
    except OSError:
        pass
    try:
        process.communicate(timeout=_LOOKUP_REAP_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        pass


def _run_lookup_command(cmd: list[str]) -> "subprocess.CompletedProcess[str]":
    """Run *cmd* in its own process group and kill the group on timeout.

    Raises ``subprocess.TimeoutExpired`` only after the whole process group has
    been terminated, so the caller can treat the timeout as a transient failure
    without leaving orphaned children behind.
    """
    process = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=_LOOKUP_TIMEOUT)
    except subprocess.TimeoutExpired:
        _kill_process_group(process)
        raise
    return subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)


def _parse_workspace(stdout: str | None) -> str | None:
    """Extract ``project_workspace`` from a session-info JSON document.

    An unknown session is reported as ``error_code`` with exit status ``0``, so
    the payload decides the outcome rather than the return code. A missing,
    unparseable, or non-object document is a miss.
    """
    if not stdout:
        return None
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("error_code"):
        return None
    workspace = payload.get("project_workspace")
    if not isinstance(workspace, str) or not workspace.strip():
        return None
    return workspace


def _lookup_persisted_workspace(session_id: str) -> str | None:
    """Return the persisted project workspace for *session_id*, if any.

    The value is read through the ``topsailai_session_info`` command, so this
    layer never opens the session database. Any failure degrades to ``None`` so
    a caller can keep its own default instead of failing the whole startup.
    """
    if not session_id:
        return None
    if session_id in _LOOKUP_CACHE:
        return _LOOKUP_CACHE[session_id]
    command = _resolve_lookup_command()
    if command is None:
        logger.warning(
            "Cannot resolve project workspace for session %s: %s not found",
            session_id, _LOOKUP_COMMAND,
        )
        return None
    try:
        result = _run_lookup_command([command, "--json", session_id])
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        logger.warning(
            "Cannot read persisted project workspace for session %s: %s",
            session_id, exc,
        )
        return None
    workspace = _parse_workspace(result.stdout)
    if workspace is None:
        return None
    _LOOKUP_CACHE[session_id] = workspace
    _LOOKUP_CACHE.move_to_end(session_id)
    while len(_LOOKUP_CACHE) > _LOOKUP_CACHE_MAX_ENTRIES:
        _LOOKUP_CACHE.popitem(last=False)
    return workspace


def resolve_project_workspace(
    explicit: str | None = None, session_id: str | None = None
) -> str | None:
    """Resolve the project workspace, preferring the environment.

    The order is: explicit argument, ``TOPSAILAI_PROJECT_WORKSPACE``,
    ``TOPSAILAI_PROJECT_FOLDER``, then the persisted session record read through
    the ``topsailai_session_info`` command. The command is invoked only when no
    environment value is present, so a correctly exported environment never pays
    for a lookup.

    Args:
        explicit: Value supplied by the caller, which always wins.
        session_id: Session identity used for the fallback lookup. When omitted
            the runtime session identity is used.

    Returns:
        The resolved workspace path, or ``None`` when nothing is available.
    """
    if explicit:
        return explicit
    for name in (PROJECT_WORKSPACE_ENV, PROJECT_FOLDER_ENV):
        value = os.getenv(name)
        if value:
            return value
    if session_id is None:
        from topsailai.utils import env_tool

        session_id = env_tool.get_session_id()
    return _lookup_persisted_workspace(session_id or "")
