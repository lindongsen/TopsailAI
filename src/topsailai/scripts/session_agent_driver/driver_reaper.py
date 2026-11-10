"""Reap the driver's own analysis sessions after the driver process exits.

The analysis agent runs inside the driver process, so every analysis session
owner record carries the driver's own PID. ``SessionActivityProbe.can_clean()``
authorizes deletion only after a fresh ``STOPPED`` observation, which can never
hold while the driver is alive. Deleting from the driver's own ``finally`` block
or from a plain ``atexit`` handler is therefore refused every single time.

This module keeps the guard untouched and moves the deletion to a detached child
process that outlives the driver. The child waits for the driver PID to
disappear, so the observation is ``STOPPED`` and the existing authorization path
approves the deletion.

Author: DawsonLin
"""

import argparse
import atexit
import json
import logging
import os
import subprocess
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

logger = logging.getLogger(__name__)

REAPER_ENABLED_ENV = "TOPSAILAI_SESSION_DRIVER_REAPER_ENABLED"
REAPER_TIMEOUT_ENV = "TOPSAILAI_SESSION_DRIVER_REAPER_TIMEOUT"
REAPER_POLL_ENV = "TOPSAILAI_SESSION_DRIVER_REAPER_POLL_INTERVAL"
REAPER_LOG_MAX_BYTES_ENV = "TOPSAILAI_SESSION_DRIVER_REAPER_LOG_MAX_BYTES"
REAPER_LOG_MAX_BACKUPS_ENV = "TOPSAILAI_SESSION_DRIVER_REAPER_LOG_MAX_BACKUPS"

DEFAULT_TIMEOUT = 300
DEFAULT_POLL_INTERVAL = 0.5
DEFAULT_LOG_MAX_BYTES = 1024 * 1024
DEFAULT_LOG_MAX_BACKUPS = 3
REAPER_LOG_NAME = "session_agent_driver_reaper.log"

_TRACKED = set()
_TRACKED_LOCK = threading.Lock()
_REGISTERED = False


def _read_int_env(name, default):
    """Read a positive integer environment variable with a safe fallback."""
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _read_float_env(name, default):
    """Read a positive float environment variable with a safe fallback."""
    try:
        value = float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def track_session(session_id):
    """Remember one analysis session so the exit reaper can delete it later.

    Tracking is skipped when the reaper is disabled, so a disabled reaper can
    never leave a pending spawn behind at interpreter exit.
    """
    if not isinstance(session_id, str) or not session_id:
        return
    if not _is_enabled():
        return
    with _TRACKED_LOCK:
        _TRACKED.add(session_id)


def tracked_sessions():
    """Return the analysis sessions tracked by this process as a sorted tuple."""
    with _TRACKED_LOCK:
        return tuple(sorted(_TRACKED))


def _is_enabled():
    """Return whether the exit reaper may spawn a child process."""
    return os.environ.get(REAPER_ENABLED_ENV, "1").strip().lower() not in (
        "0", "false", "no", "off",
    )


def register_exit_reaper():
    """Register the exit handler once per process."""
    global _REGISTERED
    with _TRACKED_LOCK:
        if _REGISTERED:
            return
        _REGISTERED = True
    atexit.register(_spawn_reaper)


def build_reaper_command(parent_pid, home, session_ids):
    """Build the detached reaper command line for one parent process."""
    return [
        sys.executable,
        str(Path(__file__).resolve()),
        "--parent-pid", str(parent_pid),
        "--home", str(home),
        "--sessions", json.dumps(list(session_ids)),
    ]


def _child_environment(home):
    """Return the child environment with the resolved home exported.

    The reaper is disabled in the child so a reaper can never spawn another one.
    """
    environment = dict(os.environ)
    environment["TOPSAILAI_HOME"] = str(home)
    environment[REAPER_ENABLED_ENV] = "0"
    return environment


def _spawn_reaper():
    """Spawn one detached reaper for the sessions tracked by this process."""
    if not _is_enabled():
        logger.info("session reaper disabled by %s", REAPER_ENABLED_ENV)
        return
    session_ids = tracked_sessions()
    if not session_ids:
        return
    home = os.environ.get("TOPSAILAI_HOME", "")
    if not home:
        logger.warning("cannot spawn session reaper: TOPSAILAI_HOME is unset")
        return
    # Resolve here: the child imports the framework, which re-reads
    # TOPSAILAI_HOME, so a relative value would be resolved twice.
    home = str(Path(home).expanduser().resolve())
    command = build_reaper_command(os.getpid(), home, session_ids)
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
            env=_child_environment(home),
        )
    except Exception as error:  # noqa: BLE001 - exit must never fail on cleanup
        logger.warning("cannot spawn session reaper: %s", error)
        return
    logger.info(
        "spawned session reaper pid=%s for %d analysis session(s)",
        process.pid, len(session_ids),
    )


def _pid_alive(pid):
    """Return whether *pid* is alive using a signal-zero probe."""
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def wait_for_parent_exit(parent_pid, timeout, poll_interval, observer=None):
    """Return True once the parent PID is gone, False when the wait times out."""
    observe = observer or _pid_alive
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not observe(parent_pid):
            return True
        time.sleep(poll_interval)
    return not observe(parent_pid)


def _owner_pattern():
    """Return the framework owner-record pattern, or None when unavailable.

    The pattern is the framework's single authoritative definition of an owner
    record. Reusing it avoids a second suffix list that would silently drift.
    """
    try:
        from topsailai.context.session_activity import _OWNER_PATTERN
    except Exception as error:  # noqa: BLE001 - fail closed and preserve files
        logger.warning("cannot load the owner record pattern: %s", error)
        return None
    return _OWNER_PATTERN


def find_owner_records(task_dir, session_id):
    """Return every owner record on disk that belongs to *session_id*."""
    pattern = _owner_pattern()
    if pattern is None:
        return []
    directory = Path(task_dir)
    try:
        entries = sorted(directory.iterdir())
    except OSError as error:
        logger.warning("cannot list task directory %s: %s", directory, error)
        return []
    records = []
    for entry in entries:
        match = pattern.fullmatch(entry.name)
        if match is None or match.group(1) != session_id:
            continue
        records.append(entry)
    return records


def _delete_owner_records(task_dir, session_id, probe):
    """Delete every owner record after a fresh STOPPED observation."""
    deleted = []
    for path in find_owner_records(task_dir, session_id):
        if not probe.can_clean(session_id):
            logger.warning("preserved owner record %s: cleanup not authorized", path)
            break
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        except OSError as error:
            logger.error("cannot delete owner record %s: %s", path, error)
            continue
        logger.info("deleted owner record %s", path)
        deleted.append(path)
    return deleted


def _delete_session_row(session_id):
    """Delete the database row; return True when no row remains."""
    from topsailai.context import ctx_manager

    manager = ctx_manager.get_session_manager()
    if manager is None:
        logger.warning("cannot delete session %s: session manager unavailable", session_id)
        return False
    if not manager.exists_session(session_id):
        logger.info("session %s already absent from the database", session_id)
        return True
    if manager.delete_session(session_id):
        logger.info("deleted session row %s", session_id)
        return True
    logger.warning("preserved session row %s: deletion not authorized", session_id)
    return False


def reap_sessions(parent_pid, session_ids, home, timeout=DEFAULT_TIMEOUT,
                  poll_interval=DEFAULT_POLL_INTERVAL, observer=None):
    """Wait for the parent to exit, then delete each tracked session."""
    # Resolve the home before any framework import: importing topsailai
    # re-reads TOPSAILAI_HOME and a relative value would be resolved twice.
    home = Path(home).expanduser().resolve()
    if not wait_for_parent_exit(parent_pid, timeout, poll_interval, observer):
        logger.warning(
            "parent %s still alive after %ss; preserving %d analysis session(s)",
            parent_pid, timeout, len(session_ids),
        )
        return []
    from topsailai.context.session_activity import SessionActivityProbe

    task_dir = home / "workspace" / "task"
    probe = SessionActivityProbe((task_dir,))
    reaped = []
    for session_id in session_ids:
        if not probe.can_clean(session_id):
            logger.warning("preserved session %s: cleanup not authorized", session_id)
            continue
        if not _delete_session_row(session_id):
            continue
        _delete_owner_records(task_dir, session_id, probe)
        reaped.append(session_id)
    return reaped


def _configure_child_logging(home):
    """Attach a bounded file handler so the orphaned child can report."""
    log_dir = Path(home) / "log"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_dir / REAPER_LOG_NAME,
            maxBytes=_read_int_env(REAPER_LOG_MAX_BYTES_ENV, DEFAULT_LOG_MAX_BYTES),
            backupCount=_read_int_env(REAPER_LOG_MAX_BACKUPS_ENV, DEFAULT_LOG_MAX_BACKUPS),
            encoding="utf-8",
        )
    except OSError as error:
        logging.basicConfig(level=logging.INFO)
        logger.warning("cannot open the reaper log in %s: %s", log_dir, error)
        return
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def _ensure_project_paths():
    """Make the framework importable when this module runs as a child process."""
    script_dir = Path(__file__).resolve().parent
    for path in (script_dir.parent.parent.parent, script_dir.parent.parent,
                 script_dir.parent.parent / "cli", script_dir):
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)


def _parse_session_ids(payload):
    """Return validated session ids, or None when the payload is malformed."""
    try:
        session_ids = json.loads(payload)
    except ValueError:
        return None
    if not isinstance(session_ids, list):
        return None
    if not all(isinstance(item, str) and item for item in session_ids):
        return None
    return session_ids


def main(argv=None):
    """Run the detached reaper for one parent process."""
    parser = argparse.ArgumentParser(
        prog="driver_reaper",
        description="Delete analysis sessions after their owning driver exits.",
    )
    parser.add_argument("--parent-pid", type=int, required=True,
                        help="PID of the driver process that spawned this reaper")
    parser.add_argument("--home", required=True,
                        help="TOPSAILAI_HOME that owns the session records")
    parser.add_argument("--sessions", required=True,
                        help="JSON array of analysis session ids to delete")
    args = parser.parse_args(argv)

    session_ids = _parse_session_ids(args.sessions)
    if session_ids is None:
        print("error: --sessions must be a JSON array of session ids", file=sys.stderr)
        return 2

    # Resolve once, before any framework import can re-read TOPSAILAI_HOME.
    home = Path(args.home).expanduser().resolve()
    _configure_child_logging(home)
    _ensure_project_paths()
    timeout = _read_int_env(REAPER_TIMEOUT_ENV, DEFAULT_TIMEOUT)
    poll_interval = _read_float_env(REAPER_POLL_ENV, DEFAULT_POLL_INTERVAL)
    reaped = reap_sessions(args.parent_pid, session_ids, home,
                           timeout, poll_interval)
    logger.info("session reaper finished: reaped=%d of %d",
                len(reaped), len(session_ids))
    return 0


if __name__ == "__main__":
    sys.exit(main())
