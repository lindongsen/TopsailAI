"""
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-11-09
  Purpose: Verify the approved database write I/O failure policy.

  Policy under test:
    - A transient write failure blocks instead of failing fast.
    - TOPSAILAI_DB_WRITE_MAX_BLOCK_SECONDS bounds that block; 0 means unbounded.
    - When the write cannot make progress the process exits.
    - Unrecoverable I/O conditions exit immediately without waiting.
    - Scope is writes only; reads keep failing fast.
    - A business "not found" result stays False and is never an I/O failure.
"""

import os
import sqlite3
import subprocess
import sys
import threading
import time
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.exc import TimeoutError as SAPoolTimeoutError

from topsailai.utils import db_io_tool


def _sqlite_error(code: int, message: str = "synthetic") -> OperationalError:
    """Build an OperationalError carrying a real SQLite primary result code."""
    orig = sqlite3.OperationalError(message)
    orig.sqlite_errorcode = code
    return OperationalError("stmt", {}, orig)


class _ExitRecorder:
    """Replace db_io_tool._exit_process so the test runner survives."""

    def __init__(self):
        self.calls = []

    def __call__(self, code=1):
        self.calls.append(code)


@pytest.fixture
def exit_recorder():
    recorder = _ExitRecorder()
    with patch.object(db_io_tool, "_exit_process", recorder):
        yield recorder


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "policy.db")


@pytest.fixture
def manager(db_path):
    from topsailai.context.session_manager.sql import SessionSQLAlchemy

    return SessionSQLAlchemy(f"sqlite:///{db_path}")


def _hold_lock(db_path, seconds, ready, release, exclusive=False):
    """Hold a write lock on the database for a bounded time.

    ``BEGIN IMMEDIATE`` takes a RESERVED lock, which still admits readers.
    ``BEGIN EXCLUSIVE`` additionally blocks readers, which is what the read
    isolation checks need.
    """
    engine = create_engine(f"sqlite:///{db_path}")
    conn = engine.connect()
    conn.execute(text("BEGIN EXCLUSIVE" if exclusive else "BEGIN IMMEDIATE"))
    ready.set()
    release.wait(seconds)
    try:
        conn.execute(text("COMMIT"))
    except Exception:
        pass
    conn.close()
    engine.dispose()


def _run_with_lock(db_path, seconds, action, exclusive=False):
    """Run action while an external writer holds the lock for a bounded time."""
    ready = threading.Event()
    release = threading.Event()
    holder = threading.Thread(
        target=_hold_lock,
        args=(db_path, seconds, ready, release, exclusive),
        daemon=True,
    )
    holder.start()
    assert ready.wait(5), "lock holder did not start"
    started = time.monotonic()
    try:
        result = action()
    finally:
        release.set()
        holder.join(5)
    return result, time.monotonic() - started


# --------------------------------------------------------------------------
# A. Policy module
# --------------------------------------------------------------------------

def test_a1_default_budget_is_unbounded(monkeypatch):
    monkeypatch.delenv(db_io_tool.ENV_MAX_BLOCK_SECONDS, raising=False)
    assert db_io_tool.get_max_block_seconds() == 0.0


def test_a2_empty_value_is_unbounded(monkeypatch):
    monkeypatch.setenv(db_io_tool.ENV_MAX_BLOCK_SECONDS, "")
    assert db_io_tool.get_max_block_seconds() == 0.0


def test_a3_invalid_value_falls_back_to_unbounded(monkeypatch):
    monkeypatch.setenv(db_io_tool.ENV_MAX_BLOCK_SECONDS, "abc")
    assert db_io_tool.get_max_block_seconds() == 0.0


def test_a4_negative_value_is_unbounded(monkeypatch):
    monkeypatch.setenv(db_io_tool.ENV_MAX_BLOCK_SECONDS, "-5")
    assert db_io_tool.get_max_block_seconds() == 0.0


def test_a5_positive_value_is_honored(monkeypatch):
    monkeypatch.setenv(db_io_tool.ENV_MAX_BLOCK_SECONDS, "30")
    assert db_io_tool.get_max_block_seconds() == 30.0


def test_a6_unbounded_maps_to_max_pragma(monkeypatch):
    monkeypatch.delenv(db_io_tool.ENV_MAX_BLOCK_SECONDS, raising=False)
    assert db_io_tool.resolve_busy_timeout_ms() == db_io_tool.INFINITE_BUSY_TIMEOUT_MS


def test_a7_bounded_maps_to_milliseconds(monkeypatch):
    monkeypatch.setenv(db_io_tool.ENV_MAX_BLOCK_SECONDS, "30")
    assert db_io_tool.resolve_busy_timeout_ms() == 30000


def test_a8_transient_code_detected():
    exc = _sqlite_error(5, "database is locked")
    assert db_io_tool.is_db_io_failure(exc) is True
    assert db_io_tool.is_transient_db_io_failure(exc) is True


def test_a9_fatal_full_disk_detected():
    exc = _sqlite_error(13, "database or disk is full")
    assert db_io_tool.is_db_io_failure(exc) is True
    assert db_io_tool.is_transient_db_io_failure(exc) is False


def test_a10_corrupt_file_detected():
    exc = _sqlite_error(26, "file is not a database")
    assert db_io_tool.is_db_io_failure(exc) is True
    assert db_io_tool.is_transient_db_io_failure(exc) is False


def test_a11_pool_timeout_detected():
    exc = SAPoolTimeoutError("QueuePool limit reached")
    assert db_io_tool.is_db_io_failure(exc) is True
    assert db_io_tool.is_transient_db_io_failure(exc) is False


def test_a12_non_io_error_is_not_io_failure():
    assert db_io_tool.is_db_io_failure(ValueError("bad input")) is False


def test_a13_integrity_error_is_not_io_failure():
    exc = IntegrityError("stmt", {}, sqlite3.IntegrityError("unique"))
    assert db_io_tool.is_db_io_failure(exc) is False


def test_a14_non_io_error_returned_for_reraise(exit_recorder):
    exc = ValueError("bad input")
    returned = db_io_tool.handle_write_failure(exc, "op")
    assert returned is exc
    assert exit_recorder.calls == []


def test_a15_io_error_triggers_exit(exit_recorder):
    db_io_tool.handle_write_failure(_sqlite_error(5), "op")
    assert exit_recorder.calls == [1]


def test_a16_fatal_error_triggers_exit(exit_recorder):
    db_io_tool.handle_write_failure(_sqlite_error(13), "op")
    assert exit_recorder.calls == [1]


# --------------------------------------------------------------------------
# B. Blocking behavior with a real lock
# --------------------------------------------------------------------------

def test_b1_write_blocks_then_succeeds(manager, db_path, monkeypatch, exit_recorder):
    monkeypatch.delenv(db_io_tool.ENV_MAX_BLOCK_SECONDS, raising=False)
    from topsailai.context.session_manager.__base import SessionData

    data = SessionData(session_id="s-b1", task="t")
    result, elapsed = _run_with_lock(
        db_path, 2.0, lambda: manager.create_session(data),
    )
    assert result is True
    assert elapsed >= 1.8
    assert exit_recorder.calls == []


def test_b2_bounded_budget_succeeds_when_lock_clears(manager, db_path, monkeypatch, exit_recorder):
    monkeypatch.setenv(db_io_tool.ENV_MAX_BLOCK_SECONDS, "10")
    from topsailai.context.session_manager.__base import SessionData

    data = SessionData(session_id="s-b2", task="t")
    result, elapsed = _run_with_lock(
        db_path, 1.0, lambda: manager.create_session(data),
    )
    assert result is True
    assert elapsed >= 0.8
    assert exit_recorder.calls == []


def test_b3_bounded_budget_exits_when_lock_never_clears(
    manager, db_path, monkeypatch, exit_recorder,
):
    """An exhausted budget exits the process, then the exception propagates."""
    monkeypatch.setenv(db_io_tool.ENV_MAX_BLOCK_SECONDS, "1")
    from topsailai.context.session_manager.__base import SessionData

    data = SessionData(session_id="s-b3", task="t")
    with pytest.raises(OperationalError):
        _run_with_lock(db_path, 5.0, lambda: manager.create_session(data))
    assert exit_recorder.calls == [1]


def test_b4_update_session_name_blocks_instead_of_returning_false(
    manager, db_path, monkeypatch, exit_recorder,
):
    monkeypatch.delenv(db_io_tool.ENV_MAX_BLOCK_SECONDS, raising=False)
    from topsailai.context.session_manager.__base import SessionData

    manager.create_session(SessionData(session_id="s-b4", task="t"))
    result, elapsed = _run_with_lock(
        db_path, 2.0, lambda: manager.update_session_name("s-b4", "renamed"),
    )
    assert result is True
    assert elapsed >= 1.8
    assert exit_recorder.calls == []


def test_b5_accumulate_tokens_blocks_instead_of_returning_false(
    manager, db_path, monkeypatch, exit_recorder,
):
    monkeypatch.delenv(db_io_tool.ENV_MAX_BLOCK_SECONDS, raising=False)
    from topsailai.context.session_manager.__base import SessionData

    manager.create_session(SessionData(session_id="s-b5", task="t"))
    result, elapsed = _run_with_lock(
        db_path, 2.0,
        lambda: manager.accumulate_session_tokens(
            session_id="s-b5", current_tokens=10,
            current_cached_tokens=0, current_completion_tokens=5,
        ),
    )
    assert result is True
    assert elapsed >= 1.8
    assert exit_recorder.calls == []


def test_b6_accumulate_metrics_blocks_instead_of_returning_false(
    manager, db_path, monkeypatch, exit_recorder,
):
    monkeypatch.delenv(db_io_tool.ENV_MAX_BLOCK_SECONDS, raising=False)
    from topsailai.context.session_manager.__base import SessionData

    manager.create_session(SessionData(session_id="s-b6", task="t"))
    result, elapsed = _run_with_lock(
        db_path, 2.0,
        lambda: manager.accumulate_session_metrics(session_id="s-b6", turn_count=1),
    )
    assert result is True
    assert elapsed >= 1.8
    assert exit_recorder.calls == []


def test_b7_add_message_blocks_then_succeeds(manager, db_path, monkeypatch, exit_recorder):
    monkeypatch.delenv(db_io_tool.ENV_MAX_BLOCK_SECONDS, raising=False)
    from topsailai.context.chat_history_manager.__base import ChatHistoryMessageData

    msg = ChatHistoryMessageData(message="hello", msg_id="m-b7", session_id="s-b7")
    _, elapsed = _run_with_lock(
        db_path, 2.0, lambda: manager.chat_history.add_message(msg),
    )
    assert elapsed >= 1.8
    assert exit_recorder.calls == []
    assert manager.chat_history.get_message("m-b7") is not None


def test_b8_del_messages_blocks_then_succeeds(manager, db_path, monkeypatch, exit_recorder):
    monkeypatch.delenv(db_io_tool.ENV_MAX_BLOCK_SECONDS, raising=False)
    from topsailai.context.chat_history_manager.__base import ChatHistoryMessageData

    msg = ChatHistoryMessageData(message="hello", msg_id="m-b8", session_id="s-b8")
    manager.chat_history.add_message(msg)
    _, elapsed = _run_with_lock(
        db_path, 2.0, lambda: manager.chat_history.del_messages(msg_id="m-b8"),
    )
    assert elapsed >= 1.8
    assert exit_recorder.calls == []
    assert manager.chat_history.get_message("m-b8") is None


# --------------------------------------------------------------------------
# C. Contract: business result vs I/O failure
# --------------------------------------------------------------------------

def test_c1_update_session_name_missing_returns_false(manager, exit_recorder):
    assert manager.update_session_name("missing", "name") is False
    assert exit_recorder.calls == []


def test_c2_delete_session_missing_returns_false(manager, exit_recorder):
    assert manager.delete_session("missing") is False
    assert exit_recorder.calls == []


def test_c3_accumulate_tokens_missing_returns_false(manager, exit_recorder):
    result = manager.accumulate_session_tokens(
        session_id="missing", current_tokens=1,
        current_cached_tokens=0, current_completion_tokens=1,
    )
    assert result is False
    assert exit_recorder.calls == []


def test_c4_accumulate_metrics_missing_returns_false(manager, exit_recorder):
    assert manager.accumulate_session_metrics(session_id="missing", turn_count=1) is False
    assert exit_recorder.calls == []


def test_c5_create_session_duplicate_raises_value_error(manager, exit_recorder):
    from topsailai.context.session_manager.__base import SessionData

    manager.create_session(SessionData(session_id="dup", task="t"))
    with pytest.raises(ValueError):
        manager.create_session(SessionData(session_id="dup", task="t"))
    assert exit_recorder.calls == []


def test_c6_delete_cleanup_message_not_old_returns_zero(manager, exit_recorder):
    from topsailai.context.chat_history_manager.__base import ChatHistoryMessageData

    manager.chat_history.add_message(
        ChatHistoryMessageData(message="fresh", msg_id="m-c6", session_id="s-c6"),
    )
    assert manager.chat_history.delete_cleanup_message("m-c6", 3600) == 0
    assert exit_recorder.calls == []


def test_c7_clean_sessions_zero_returns_zero(manager, exit_recorder):
    assert manager.clean_sessions(0) == 0
    assert exit_recorder.calls == []


def test_c8_update_session_name_non_io_error_returns_false(
    manager, exit_recorder, monkeypatch,
):
    """A non-I/O failure keeps the original False contract and never exits."""
    from topsailai.context.session_manager import sql as session_sql
    from topsailai.context.session_manager.__base import SessionData

    manager.create_session(SessionData(session_id="s-c8", task="t"))
    with patch.object(session_sql, "datetime", side_effect=RuntimeError("clock")):
        assert manager.update_session_name("s-c8", "renamed") is False
    assert exit_recorder.calls == []


def test_c9_accumulate_tokens_non_io_error_returns_false(
    manager, exit_recorder, monkeypatch,
):
    """A non-I/O failure keeps the original False contract and never exits."""
    from topsailai.context.session_manager import sql as session_sql
    from topsailai.context.session_manager.__base import SessionData

    manager.create_session(SessionData(session_id="s-c9", task="t"))
    with patch.object(session_sql, "datetime", side_effect=RuntimeError("clock")):
        result = manager.accumulate_session_tokens(
            session_id="s-c9", current_tokens=1,
            current_cached_tokens=0, current_completion_tokens=1,
        )
    assert result is False
    assert exit_recorder.calls == []


def test_c10_accumulate_metrics_non_io_error_returns_false(
    manager, exit_recorder, monkeypatch,
):
    """A non-I/O failure keeps the original False contract and never exits."""
    from topsailai.context.session_manager import sql as session_sql
    from topsailai.context.session_manager.__base import SessionData

    manager.create_session(SessionData(session_id="s-c10", task="t"))
    with patch.object(session_sql, "datetime", side_effect=RuntimeError("clock")):
        result = manager.accumulate_session_metrics(session_id="s-c10", turn_count=1)
    assert result is False
    assert exit_recorder.calls == []


# --------------------------------------------------------------------------
# D. Read isolation: the leaked pragma hazard
# --------------------------------------------------------------------------

def _busy_timeout(manager) -> int:
    with manager.engine.connect() as conn:
        return conn.execute(text("PRAGMA busy_timeout")).scalar()


def test_d1_busy_timeout_restored_after_success(manager, monkeypatch):
    monkeypatch.delenv(db_io_tool.ENV_MAX_BLOCK_SECONDS, raising=False)
    from topsailai.context.session_manager.__base import SessionData

    before = _busy_timeout(manager)
    manager.create_session(SessionData(session_id="s-d1", task="t"))
    assert _busy_timeout(manager) == before


def test_d2_busy_timeout_restored_after_failure(manager, monkeypatch, exit_recorder):
    monkeypatch.setenv(db_io_tool.ENV_MAX_BLOCK_SECONDS, "1")
    from topsailai.context.session_manager.__base import SessionData

    before = _busy_timeout(manager)
    db_path = manager.conn.replace("sqlite:///", "")
    with pytest.raises(OperationalError):
        _run_with_lock(
            db_path, 3.0,
            lambda: manager.create_session(SessionData(session_id="s-d2", task="t")),
        )
    assert exit_recorder.calls == [1]
    assert _busy_timeout(manager) == before


def test_d3_read_after_write_does_not_block(manager, monkeypatch, exit_recorder):
    """A read must not inherit the widened write timeout.

    ``BEGIN EXCLUSIVE`` blocks readers too, so a read that inherited the
    unbounded write timeout would hang instead of raising.
    """
    monkeypatch.delenv(db_io_tool.ENV_MAX_BLOCK_SECONDS, raising=False)
    from topsailai.context.session_manager.__base import SessionData

    manager.create_session(SessionData(session_id="s-d3", task="t"))
    db_path = manager.conn.replace("sqlite:///", "")
    ready = threading.Event()
    release = threading.Event()
    holder = threading.Thread(
        target=_hold_lock,
        args=(db_path, 8.0, ready, release, True),
        daemon=True,
    )
    holder.start()
    assert ready.wait(5)
    started = time.monotonic()
    try:
        with pytest.raises(OperationalError):
            manager.list_sessions()
    finally:
        release.set()
        holder.join(5)
    elapsed = time.monotonic() - started
    assert elapsed < 7.0, "a read must not inherit the write block"
    assert exit_recorder.calls == []


def test_d4_get_message_fails_fast_under_lock(manager, db_path, monkeypatch, exit_recorder):
    monkeypatch.delenv(db_io_tool.ENV_MAX_BLOCK_SECONDS, raising=False)
    from topsailai.context.chat_history_manager.__base import ChatHistoryMessageData

    manager.chat_history.add_message(
        ChatHistoryMessageData(message="x", msg_id="m-d4", session_id="s-d4"),
    )
    ready = threading.Event()
    release = threading.Event()
    holder = threading.Thread(
        target=_hold_lock,
        args=(db_path, 8.0, ready, release, True),
        daemon=True,
    )
    holder.start()
    assert ready.wait(5)
    started = time.monotonic()
    try:
        with pytest.raises(OperationalError):
            manager.chat_history.get_message("m-d4")
    finally:
        release.set()
        holder.join(5)
    elapsed = time.monotonic() - started
    assert elapsed < 7.0, "a read must keep failing fast"
    assert exit_recorder.calls == []


# --------------------------------------------------------------------------
# E. Callers must not downgrade an I/O failure to a warning
# --------------------------------------------------------------------------

def test_e1_ctx_manager_propagates_io_failure(exit_recorder):
    from topsailai.context import ctx_manager

    class _Failing:
        def update_session_name(self, session_id, session_name):
            raise db_io_tool.handle_write_failure(
                _sqlite_error(5), "update_session_name", session_id=session_id,
            )

    with pytest.raises(OperationalError):
        ctx_manager.update_session_name("s-e1", "name", session_mgr=_Failing())
    assert exit_recorder.calls == [1]


def test_e2_token_finalize_propagates_io_failure(exit_recorder, monkeypatch):
    from topsailai.context import ctx_manager, token

    class _Failing:
        def accumulate_session_tokens(self, **kwargs):
            raise db_io_tool.handle_write_failure(
                _sqlite_error(5), "accumulate_session_tokens",
            )

    monkeypatch.setattr(ctx_manager, "get_session_manager", lambda: _Failing())
    monkeypatch.setenv("SESSION_ID", "s-e2")
    stat = token.TokenStat(llm_id="test-e2")
    try:
        with pytest.raises(OperationalError):
            stat.finalize_usage(completion_text="hello")
    finally:
        stat.flag_running = False
        stat.join(5)
    assert exit_recorder.calls == [1]


def test_e3_session_metrics_propagates_io_failure(exit_recorder, monkeypatch):
    from topsailai.context import ctx_manager
    from topsailai.hooks.points.workspace.after_attempt_settle_user2agent.modules import (
        session_metrics,
    )

    class _Failing:
        def accumulate_session_metrics(self, **kwargs):
            raise db_io_tool.handle_write_failure(
                _sqlite_error(5), "accumulate_session_metrics",
            )

    class _Binding:
        def settle_authorized(self, agent):
            return True

    class _RuntimeData:
        session_id = "s-e3"

    class _AgentChat:
        ai_agent = object()
        ctx_runtime_data = _RuntimeData()

    class _Attempt:
        binding = _Binding()

    monkeypatch.setattr(ctx_manager, "get_session_manager", lambda: _Failing())
    with pytest.raises(OperationalError):
        session_metrics.main(agent_chat=_AgentChat(), outcome=None, attempt=_Attempt())
    assert exit_recorder.calls == [1]


# --------------------------------------------------------------------------
# F. Real process exit (no patched hook)
# --------------------------------------------------------------------------

def test_f1_real_process_exits_with_code_one(tmp_path):
    """The unpatched policy must terminate the interpreter with exit code 1."""
    script = tmp_path / "exit_probe.py"
    script.write_text(
        "import sqlite3\n"
        "from sqlalchemy.exc import OperationalError\n"
        "from topsailai.utils import db_io_tool\n"
        "orig = sqlite3.OperationalError('database is locked')\n"
        "orig.sqlite_errorcode = 5\n"
        "exc = OperationalError('stmt', {}, orig)\n"
        "db_io_tool.handle_write_failure(exc, 'probe')\n"
        "print('NOT REACHED')\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(tmp_path.parent), os.getcwd(), os.path.join(os.getcwd(), "src")]
    )
    completed = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True, text=True, timeout=60, env=env,
    )
    assert completed.returncode == 1, completed.stderr
    assert "NOT REACHED" not in completed.stdout
