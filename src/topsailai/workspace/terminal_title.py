'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-07-28
  Purpose: Set the terminal window title during interactive sessions.
'''

import os
import socket
import sys

from topsailai.logger import logger
from topsailai.utils import env_tool


# Cache the last title to avoid writing the same escape sequence repeatedly.
_last_title = None

# Track skip reasons already reported so each one is logged only once.
_logged_skip_reasons = set()


def _is_enabled() -> bool:
    """Return True when the terminal title feature is enabled."""
    return env_tool.EnvReaderInstance.check_bool(
        "TOPSAILAI_TERMINAL_TITLE_ENABLED", True
    )


def _is_interactive_tty() -> bool:
    """Return True when stdout is a TTY and interactive mode is enabled."""
    if not env_tool.is_interactive_mode():
        return False
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


def get_host_name() -> str:
    """Return the short hostname."""
    try:
        return socket.gethostname().split(".")[0]
    except Exception:
        return "unknown"


def build_title(session_name: str = "", session_id: str = "") -> str:
    """Build the terminal title from the configured format string.

    Supported placeholders:
      - {host_name}
      - {session_name}
      - {session_id}

    Args:
        session_name: Display name of the session.
        session_id: Identifier of the session.

    Returns:
        str: The formatted title.
    """
    fmt = os.getenv(
        "TOPSAILAI_TERMINAL_TITLE_FORMAT", "{host_name}:{session_name}"
    )
    return fmt.format(
        host_name=get_host_name(),
        session_name=session_name or session_id or "",
        session_id=session_id or "",
    )


def _set_title_posix(title: str) -> bool:
    """Set the terminal title using the OSC escape sequence on POSIX systems."""
    try:
        sys.stdout.write(f"\033]0;{title}\007")
        sys.stdout.flush()
        return True
    except Exception as e:
        logger.debug("set_terminal_title posix failed: %s", e)
        return False


def _set_title_windows(title: str) -> bool:
    """Set the console title on Windows using the Win32 API."""
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW(title)
        return True
    except Exception as e:
        logger.debug("set_terminal_title windows failed: %s", e)
        return False


# Exposed for tests on non-Windows platforms.
_set_title_windows_for_test = _set_title_windows


def _log_skip_once(reason: str, message: str, *args) -> None:
    """Log a skip reason once per process so a missed update stays diagnosable.

    Routine skips happen on every call (non-TTY stdout, disabled feature), so
    logging them at debug level on each call hides the reason completely at the
    default log level. Emitting one info line per distinct reason keeps the
    cause discoverable without flooding the log.
    """
    if reason in _logged_skip_reasons:
        logger.debug(message, *args)
        return
    _logged_skip_reasons.add(reason)
    logger.info(message, *args)


def set_terminal_title(title: str, force: bool = False) -> bool:
    """Set the terminal window title if conditions are met.

    The update is skipped when:
      - the feature is disabled,
      - the title is empty,
      - stdout is not a TTY,
      - interactive mode is disabled,
      - the title is identical to the last set title and force is False.

    Skip reasons are logged once per process at info level, and failures are
    logged at debug level, so the caller is never interrupted.

    Args:
        title: The title string to display.
        force: When True, write the title even when it equals the cached one.
            Use it after the terminal may have overwritten the title on its
            own, for example a shell prompt hook or a tmux reattach.

    Returns:
        bool: True if the title was set, False otherwise.
    """
    global _last_title
    try:
        if not _is_enabled():
            _log_skip_once(
                "disabled", "terminal title skipped: feature is disabled"
            )
            return False
        if not title:
            _log_skip_once("empty", "terminal title skipped: empty title")
            return False
        if not force and title == _last_title:
            return True
        if not _is_interactive_tty():
            _log_skip_once(
                "non-tty",
                "terminal title skipped: stdout is not an interactive TTY",
            )
            return False

        if sys.platform == "win32":
            ok = _set_title_windows(title)
        else:
            ok = _set_title_posix(title)

        if ok:
            _last_title = title
        return ok
    except Exception as e:
        logger.debug("set_terminal_title failed: %s", e)
        return False


def refresh_terminal_title(
        session_id: str = "",
        session_name: str = "",
        force: bool = False,
    ) -> bool:
    """Refresh the terminal title from the current session.

    When session_name is not provided, the function attempts to read it from
    the session manager. Any failure is caught and logged so the caller is
    never interrupted.

    Args:
        session_id: Optional session identifier. When empty, the value is
            read from the environment.
        session_name: Optional session display name. When empty, the value
            is read from the session manager.
        force: When True, write the title even when it equals the cached one.

    Returns:
        bool: True if the title was refreshed, False otherwise.
    """
    try:
        if not _is_enabled():
            _log_skip_once(
                "disabled", "terminal title skipped: feature is disabled"
            )
            return False

        if not session_id:
            session_id = env_tool.get_session_id() or ""

        if session_id and not session_name:
            try:
                from topsailai.context import ctx_manager
                session_mgr = ctx_manager.get_session_manager()
                session_data = session_mgr.get_session(session_id)
                if session_data:
                    session_name = session_data.session_name or session_id
            except Exception as e:
                _log_skip_once(
                    "session-read",
                    "refresh_terminal_title failed to read session: %s", e,
                )
                session_name = session_id

        title = build_title(session_name=session_name, session_id=session_id)
        return set_terminal_title(title, force=force)
    except Exception as e:
        logger.debug("refresh_terminal_title failed: %s", e)
        return False


def reset_terminal_title_cache() -> None:
    """Forget the last written title so the next update is always emitted.

    The terminal may overwrite the title on its own (for example a shell
    prompt hook, a tmux reattach, or a restored tab). Clearing the cache
    forces the next refresh to write the escape sequence again instead of
    short-circuiting on an identical cached value.
    """
    global _last_title
    _last_title = None
