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
    - A database I/O failure never terminates the process. A committed write
      re-raises so the caller can abandon the turn, and a non-committed write is
      logged and skipped.
    - The scope is writes only. Reads keep the driver default so a stuck write can
      never make a read hang.

  Why the process is never terminated here:
    ``_async_update_session_name`` runs inside a daemon thread, so a process-wide
    exit would also destroy an interactive session that is still usable. The
    conversation, the session metadata and the diagnostic artifacts all survive a
    failed write, so the failure is reported to the caller instead of ending the
    process. Session artifacts are retained on every exit path, including an
    abnormal one, so a lost write never costs the operator the evidence.
'''

import sqlite3

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


def _describe_failure(exc: BaseException, operation: str, context: dict) -> str:
    """Build one diagnosable description of a failed write."""
    details = ", ".join(f"{key}={value}" for key, value in context.items())
    return (
        f"operation={operation}, transient={is_transient_db_io_failure(exc)}, "
        f"block_budget_seconds={get_max_block_seconds()}, {details}, "
        f"error={type(exc).__name__}: {exc}"
    )


def handle_write_failure(exc: BaseException, operation: str, **context) -> BaseException:
    """Report a failed committed write and return the exception to re-raise.

    A committed write is a promise: the caller must not mistake a lost write for
    success, so the exception is always returned for the caller to re-raise. The
    process is never terminated here, because the conversation, the session
    metadata and the diagnostic artifacts all survive a failed write and an
    interactive session stays usable.

    A non-I/O failure is returned unchanged so a programming defect keeps its
    original traceback and stays testable.
    """
    if not is_db_io_failure(exc):
        return exc

    logger.critical(
        "db_io: committed write failed: %s", _describe_failure(exc, operation, context),
        exc_info=True,
    )
    return exc


def handle_skipped_write_failure(
    exc: BaseException, operation: str, **context
) -> bool:
    """Report a failed non-committed write and return ``False``.

    A non-committed write records statistics or presentation metadata. Losing it
    does not damage the conversation, so it is logged and skipped instead of
    being raised. Returning ``False`` keeps the caller's existing "not applied"
    contract without turning a counter into a fatal error.
    """
    if not is_db_io_failure(exc):
        return False

    logger.warning(
        "db_io: non-committed write skipped: %s",
        _describe_failure(exc, operation, context),
        exc_info=True,
    )
    return False
