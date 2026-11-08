'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-11-09
  Purpose: Shared policy for database write I/O failures.

  Policy (approved by the human):
    - A transient write failure blocks instead of failing fast. The block budget is
      applied per write connection through the SQLite ``busy_timeout`` pragma.
    - ``TOPSAILAI_DB_WRITE_MAX_BLOCK_SECONDS`` bounds that block. ``0`` (default)
      means block indefinitely.
    - When the write cannot make progress, the process exits. This covers both an
      exhausted block budget and an unrecoverable I/O condition such as a full disk
      or a corrupt database file.
    - The scope is writes only. Reads keep the driver default so a stuck write can
      never make a read hang.

  Why the process exits with ``os._exit``:
    ``_async_update_session_name`` runs inside a daemon thread, so ``sys.exit``
    there would only stop that thread and the agent would keep running with a lost
    write. ``os._exit`` terminates the whole process from any thread. Log handlers
    are flushed first, because ``os._exit`` skips ``atexit`` and buffered output.
'''

import logging
import os
import sqlite3
import sys

from sqlalchemy.exc import TimeoutError as SAPoolTimeoutError

from topsailai.logger import logger
from topsailai.utils import env_tool

# Environment variable that bounds how long one write may block.
ENV_MAX_BLOCK_SECONDS = "TOPSAILAI_DB_WRITE_MAX_BLOCK_SECONDS"

# Driver default busy timeout in milliseconds, restored after every write so a
# read on the same pooled connection keeps failing fast.
DEFAULT_BUSY_TIMEOUT_MS = 5000

# Largest value SQLite accepts for ``busy_timeout``, used to express "block
# indefinitely" (about 24.8 days).
INFINITE_BUSY_TIMEOUT_MS = 2147483647

# SQLite primary result codes that resolve on their own once the competing
# writer finishes. These are the only codes worth waiting for.
TRANSIENT_SQLITE_CODES = frozenset({
    5,   # SQLITE_BUSY
    6,   # SQLITE_LOCKED
})

# SQLite primary result codes that never resolve by waiting. Waiting on them
# would turn a recoverable failure into a permanently hung agent.
FATAL_SQLITE_CODES = frozenset({
    8,   # SQLITE_READONLY
    10,  # SQLITE_IOERR
    11,  # SQLITE_CORRUPT
    13,  # SQLITE_FULL
    14,  # SQLITE_CANTOPEN
    15,  # SQLITE_PROTOCOL
    26,  # SQLITE_NOTADB
})


def _get_sqlite_error_code(exc: BaseException) -> int | None:
    """Return the SQLite primary result code carried by an exception, if any."""
    orig = getattr(exc, "orig", None)
    if orig is None:
        return None
    code = getattr(orig, "sqlite_errorcode", None)
    if isinstance(code, int):
        # Extended result codes encode the primary code in the low byte.
        return code & 0xFF
    return None


def is_db_io_failure(exc: BaseException) -> bool:
    """Return whether an exception represents a database I/O failure.

    Only I/O conditions are covered. A programming error such as a malformed
    statement or an integrity violation is a defect, not an I/O failure, so it
    keeps propagating normally and stays testable.
    """
    if isinstance(exc, SAPoolTimeoutError):
        # The connection pool could not hand out a connection in time.
        return True

    code = _get_sqlite_error_code(exc)
    if code is not None:
        return code in TRANSIENT_SQLITE_CODES or code in FATAL_SQLITE_CODES

    orig = getattr(exc, "orig", None)
    if isinstance(orig, sqlite3.OperationalError):
        # An OperationalError without a code is still a driver-level failure.
        return True
    return False


def is_transient_db_io_failure(exc: BaseException) -> bool:
    """Return whether waiting could resolve the failure."""
    if isinstance(exc, SAPoolTimeoutError):
        return False
    code = _get_sqlite_error_code(exc)
    return code in TRANSIENT_SQLITE_CODES if code is not None else False


def get_max_block_seconds() -> float:
    """Return the configured write block budget in seconds.

    ``0`` means block indefinitely. Unset, empty, negative, or invalid values
    also mean block indefinitely, so the safe default never fails fast.
    """
    raw = env_tool.get(ENV_MAX_BLOCK_SECONDS, default="")
    if raw is None:
        return 0.0
    text = str(raw).strip()
    if not text:
        return 0.0
    try:
        value = float(text)
    except (TypeError, ValueError):
        logger.warning(
            "db_io: invalid %s=%r, falling back to an unbounded write block",
            ENV_MAX_BLOCK_SECONDS, raw,
        )
        return 0.0
    if value <= 0:
        return 0.0
    return value


def resolve_busy_timeout_ms() -> int:
    """Return the ``busy_timeout`` value that implements the block budget."""
    seconds = get_max_block_seconds()
    if seconds <= 0:
        return INFINITE_BUSY_TIMEOUT_MS
    return min(int(seconds * 1000), INFINITE_BUSY_TIMEOUT_MS)


def _read_busy_timeout(session) -> int:
    """Read the current connection's busy timeout, falling back to the default."""
    try:
        value = session.execute(_pragma("busy_timeout")).scalar()
        if isinstance(value, int):
            return value
    except Exception:
        logger.debug("db_io: unable to read busy_timeout, using the default")
    return DEFAULT_BUSY_TIMEOUT_MS


def _pragma(name: str):
    """Build a PRAGMA statement without importing SQLAlchemy text at module load."""
    from sqlalchemy import text

    return text(f"PRAGMA {name}")


def apply_write_block(session) -> int:
    """Widen the busy timeout on one write connection and return the old value.

    The pragma is connection scoped and survives the session, so the caller must
    restore it before the connection returns to the pool. Otherwise a later read
    on the same pooled connection would block indefinitely.
    """
    original = _read_busy_timeout(session)
    target = resolve_busy_timeout_ms()
    if target == original:
        return original
    try:
        session.execute(_pragma(f"busy_timeout = {target}"))
        logger.debug("db_io: write busy_timeout %s -> %s ms", original, target)
    except Exception:
        logger.warning(
            "db_io: unable to widen busy_timeout to %s ms, keeping %s ms",
            target, original, exc_info=True,
        )
        return original
    return original


def restore_write_block(session, original: int) -> None:
    """Restore the busy timeout so reads on this connection keep failing fast."""
    if original is None:
        return
    try:
        session.execute(_pragma(f"busy_timeout = {int(original)}"))
    except Exception:
        logger.warning(
            "db_io: unable to restore busy_timeout to %s ms", original,
            exc_info=True,
        )


def _flush_output() -> None:
    """Flush every log handler and the standard streams before a hard exit."""
    for handler in logging.getLogger().handlers:
        try:
            handler.flush()
        except Exception:
            pass
    for name in list(logging.Logger.manager.loggerDict):
        instance = logging.Logger.manager.loggerDict.get(name)
        if not isinstance(instance, logging.Logger):
            continue
        for handler in instance.handlers:
            try:
                handler.flush()
            except Exception:
                pass
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None:
                stream.flush()
        except Exception:
            pass


def _exit_process(code: int = 1) -> None:
    """Terminate the whole process after flushing buffered output.

    Tests replace this attribute to observe the exit decision without ending
    the test runner.
    """
    _flush_output()
    os._exit(code)


def handle_write_failure(exc: BaseException, operation: str, **context) -> BaseException:
    """Apply the write failure policy and return the exception to re-raise.

    An I/O failure never returns: the process exits, because a lost write must
    not be mistaken for success. A non-I/O failure is returned so the caller can
    re-raise it with its original traceback.
    """
    if not is_db_io_failure(exc):
        return exc

    transient = is_transient_db_io_failure(exc)
    budget = get_max_block_seconds()
    details = ", ".join(f"{key}={value}" for key, value in context.items())
    logger.critical(
        "db_io: write failed and cannot make progress: operation=%s, "
        "transient=%s, block_budget_seconds=%s, %s, error=%s: %s",
        operation, transient, budget, details, type(exc).__name__, exc,
        exc_info=True,
    )
    _exit_process(1)
    # ``_exit_process`` does not return; keep a raise for a replaced hook.
    return exc
