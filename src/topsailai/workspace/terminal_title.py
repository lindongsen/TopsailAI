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


def set_terminal_title(title: str) -> bool:
    """Set the terminal window title if conditions are met.

    The update is skipped when:
      - the feature is disabled,
      - the title is empty,
      - stdout is not a TTY,
      - interactive mode is disabled,
      - the title is identical to the last set title.

    Errors are caught and logged at debug level so the caller is never
    interrupted.

    Args:
        title: The title string to display.

    Returns:
        bool: True if the title was set, False otherwise.
    """
    global _last_title
    try:
        if not _is_enabled() or not title:
            return False
        if title == _last_title:
            return True
        if not _is_interactive_tty():
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


def refresh_terminal_title(session_id: str = "", session_name: str = "") -> bool:
    """Refresh the terminal title from the current session.

    When session_name is not provided, the function attempts to read it from
    the session manager. Any failure is caught and logged at debug level so
    the caller is never interrupted.

    Args:
        session_id: Optional session identifier. When empty, the value is
            read from the environment.
        session_name: Optional session display name. When empty, the value
            is read from the session manager.

    Returns:
        bool: True if the title was refreshed, False otherwise.
    """
    try:
        if not _is_enabled():
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
                logger.debug("refresh_terminal_title failed to read session: %s", e)
                session_name = session_id

        title = build_title(session_name=session_name, session_id=session_id)
        return set_terminal_title(title)
    except Exception as e:
        logger.debug("refresh_terminal_title failed: %s", e)
        return False
