"""Persisted cleanup safety contracts (author: DawsonLin)."""
import json
from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest

from topsailai.context.session_activity import ActivityState as State, SessionActivityProbe
from topsailai.context.session_manager.sql import SessionSQLAlchemy, Session, SessionData
from topsailai.context.session_cleanup import HistoryCleanupManager
from topsailai.context.session_manager.manager import DefaultSessionManager
from topsailai.context.chat_history_manager.sql import Message, SessionMessage, ChatHistorySQLAlchemy


def manager(tmp_path, observer):
    """Build isolated persisted stores with explicit local ownership scope."""
    task = tmp_path / "workspace" / "task"
    task.mkdir(parents=True)
    probe = SessionActivityProbe((task,), observer)
    mgr = DefaultSessionManager(SessionSQLAlchemy(f"sqlite:///{tmp_path / 'guard.db'}"), probe)
    return mgr, task


def owner(task, sid, pid):
    """Publish valid stopped/live ownership fixtures."""
    (task / f"{sid}.{pid}.session.meta").write_text(json.dumps({"session_id": sid, "pid": pid}))


def add_session(mgr, home, sid, pid, task):
    """Create an old session and its owner evidence."""
    owner(task, sid, pid)
    data = SessionData(session_id=sid, task="test", topsailai_home=str(home))
    data.create_time = datetime.now() - timedelta(days=40)
    mgr.create_session(data)


@pytest.mark.parametrize("state", [State.RUNNING, State.UNKNOWN])
def test_protected_delete_and_age_cleanup(tmp_path, state):
    """Both manager entry points refuse protected sessions and their mappings."""
    mgr, task = manager(tmp_path, lambda pid: state)
    add_session(mgr, tmp_path, "s", 123, task)
    with mgr.chat_history.SessionLocal() as db:
        db.add(Message(msg_id="m", message="keep", msg_size=4))
        db.add(SessionMessage(msg_id="m", session_id="s"))
        db.commit()
    assert mgr.delete_session("s") is False
    assert mgr.clean_sessions(1) == 0
    assert len(mgr.chat_history.get_messages_by_session("s")) == 1


def test_stopped_delete_and_default_unknown(tmp_path):
    """Explicit observed absence permits cleanup; direct managers fail closed."""
    mgr, task = manager(tmp_path, lambda pid: State.STOPPED)
    add_session(mgr, tmp_path, "s", 123, task)
    assert mgr.clean_sessions(0) == 0
    assert mgr.clean_sessions(1) == 1
    direct = DefaultSessionManager(SessionSQLAlchemy("sqlite:///:memory:"), SessionActivityProbe(()))
    direct.create_session(SessionData(session_id="legacy", task="test"))
    assert not direct.delete_session("legacy")


@pytest.mark.parametrize("all_running", [False, True])
def test_soft_eviction_limit(tmp_path, all_running):
    """Skip protected oldest rows and never evict the just-created session."""
    mgr, task = manager(tmp_path, lambda pid: State.RUNNING if all_running or pid == 1 else State.STOPPED)
    for index in range(101):
        add_session(mgr, tmp_path, f"s{index:03}", index + 1, task)
    assert mgr.exists_session("s000")
    assert mgr.exists_session("s100")
    assert len(mgr.list_sessions()) == (101 if all_running else 100)
    assert mgr.exists_session("s001") == all_running


def test_shared_message_all_owners(tmp_path):
    """One active owner retains the message and every mapping until stopped."""
    states = {123: State.STOPPED, 456: State.RUNNING}
    mgr, task = manager(tmp_path, lambda pid: states[pid])
    add_session(mgr, tmp_path, "old", 123, task)
    add_session(mgr, tmp_path, "live", 456, task)
    history = mgr.chat_history
    with history.SessionLocal() as db:
        db.add(Message(msg_id="shared", message="keep", msg_size=4, access_time=datetime.now() - timedelta(days=40)))
        db.add_all([SessionMessage(msg_id="shared", session_id=sid) for sid in ("old", "live")])
        db.commit()
    assert history.clean_messages(1) == 0
    with history.SessionLocal() as db:
        assert db.query(SessionMessage).count() == 2
    states[456] = State.STOPPED
    assert history.clean_messages(1) == 1


def test_history_only_and_ordinary_pruning(tmp_path):
    """Missing session provenance blocks retention but not explicit compaction."""
    history = HistoryCleanupManager(ChatHistorySQLAlchemy("sqlite:///:memory:"), Mock(can_clean=Mock(return_value=True)))
    with history.SessionLocal() as db:
        db.add(Message(msg_id="m", message="keep", msg_size=4, access_time=datetime.now() - timedelta(days=40)))
        db.add(SessionMessage(msg_id="m", session_id="s"))
        db.commit()
    assert history.clean_messages(1) == 0
    history.del_messages(session_id="s")
    with history.SessionLocal() as db:
        assert db.query(Message).count() == 0


def test_multiple_managers_receive_same_probe(tmp_path, monkeypatch):
    """Every built-in SQL history manager gets the boundary's explicit probe."""
    from topsailai.context import ctx_manager
    probe = SessionActivityProbe(())
    monkeypatch.setenv("CONTEXT_HISTORY_MANAGERS", "sql.ChatHistorySQLAlchemy conn=sqlite:///:memory:;sql.ChatHistorySQLAlchemy conn=sqlite:///:memory:")
    managers = ctx_manager.get_managers_by_env(activity_probe=probe)
    assert len(managers) == 2
    assert all(mgr.activity_probe is probe for mgr in managers)
    mgr = ctx_manager.get_session_manager("sqlite:///:memory:", activity_probe=probe)
    assert mgr.cleanup.activity_probe is probe
    assert mgr.chat_history.activity_probe is probe


def test_unknown_shared_owner_and_orphan(tmp_path):
    """Missing ownership preserves both unmapped messages and mapped messages."""
    from sqlalchemy import text
    history = HistoryCleanupManager(ChatHistorySQLAlchemy("sqlite:///:memory:"), SessionActivityProbe(()))
    with history.SessionLocal() as db:
        db.add_all([Message(msg_id=sid, message="keep", msg_size=4, access_time=datetime.now() - timedelta(days=40)) for sid in ("mapped", "orphan")])
        db.add(SessionMessage(msg_id="mapped", session_id="missing"))
        db.commit()
    assert history.clean_messages(1) == 0
    with history.SessionLocal() as db:
        assert {row.msg_id for row in db.query(Message).all()} == {"mapped", "orphan"}
        assert [(row.msg_id, row.session_id) for row in db.query(SessionMessage).all()] == [("mapped", "missing")]
    with history.engine.begin() as db:
        db.execute(text("CREATE TABLE session (session_id TEXT PRIMARY KEY)"))
    assert history.clean_messages(1) == 0
    with history.SessionLocal() as db:
        assert db.query(Message).count() == 2
        assert db.query(SessionMessage).count() == 1


def test_real_waiting_process_then_exit(tmp_path):
    """Protect a real waiting worker, then reclaim its stale ownership record."""
    import shutil
    import subprocess
    interpreter = shutil.which("python3") or shutil.which("python")
    if not interpreter:
        pytest.skip("No Python interpreter available for owned child")
    mgr, task = manager(tmp_path, None)
    mgr.cleanup.activity_probe = SessionActivityProbe((task,))
    mgr.chat_history.activity_probe = mgr.cleanup.activity_probe
    child = subprocess.Popen([interpreter, "-B", "-c", "import sys; sys.stdin.read()"], stdin=subprocess.PIPE)
    try:
        add_session(mgr, tmp_path, "worker", child.pid, task)
        assert not mgr.delete_session("worker")
    finally:
        child.communicate(input=b"exit")
    assert child.returncode == 0
    assert mgr.delete_session("worker")


def test_recheck_refuses_newly_running_session(tmp_path):
    """A changed observation prevents the final destructive storage call."""
    mgr, task = manager(tmp_path, lambda pid: State.STOPPED)
    add_session(mgr, tmp_path, "race", 123, task)
    mgr.cleanup.activity_probe = Mock(can_clean=Mock(side_effect=[True, False]))
    assert not mgr.delete_session("race")
    assert mgr.exists_session("race")


def test_message_recheck_preserves_all_mappings(tmp_path):
    """Recheck shared-message owners before invoking the SQL delete primitive."""
    mgr, task = manager(tmp_path, lambda pid: State.STOPPED)
    add_session(mgr, tmp_path, "owner", 123, task)
    with mgr.chat_history.SessionLocal() as db:
        db.add(Message(msg_id="race", message="keep", msg_size=4,
                       access_time=datetime.now() - timedelta(days=40)))
        db.add(SessionMessage(msg_id="race", session_id="owner"))
        db.commit()
    mgr.chat_history.activity_probe = Mock(can_clean=Mock(side_effect=[True, False]))
    assert mgr.chat_history.clean_messages(1) == 0
    assert mgr.chat_history.get_message_sessions("race") == ["owner"]


def test_sql_storage_has_no_activity_dependency():
    """Pure storage primitives retain original explicit deletion semantics."""
    import inspect
    from topsailai.context.session_manager import sql as sessions
    from topsailai.context.chat_history_manager import sql as history
    for module in (sessions, history):
        source = inspect.getsource(module)
        assert "activity_probe" not in source
        assert "SessionActivityProbe" not in source
        assert "psutil" not in source
        assert "_evict_stopped" not in source
    storage = SessionSQLAlchemy("sqlite:///:memory:")
    storage.create_session(SessionData(session_id="pure", task="storage"))
    assert storage.delete_session("pure")


def test_missing_session_and_unsuccessful_creation():
    """Do not probe nonexistent sessions or run retention after failed creation."""
    storage = Mock()
    storage.list_sessions.return_value = []
    storage.create_session.return_value = False
    probe = Mock()
    mgr = DefaultSessionManager(storage, probe)
    assert not mgr.delete_session("missing")
    storage.list_sessions.reset_mock()
    assert not mgr.create_session(SessionData(session_id="failed", task="test"))
    storage.list_sessions.assert_not_called()
    probe.can_clean.assert_not_called()


def test_message_changed_before_sql_delete():
    """A storage-side freshness check can refuse without inflating the count."""
    storage = Mock()
    storage.list_cleanup_messages.return_value = ["updated"]
    storage.get_message_sessions.return_value = ["stopped"]
    storage.get_session_home.return_value = "home"
    storage.delete_cleanup_message.return_value = 0
    mgr = HistoryCleanupManager(storage, Mock(can_clean=Mock(return_value=True)))
    assert mgr.clean_messages(1) == 0
    storage.delete_cleanup_message.assert_called_once_with("updated", 1)


@pytest.mark.parametrize("owners", [[[]], [["stopped"], []]])
def test_missing_message_owners_never_delete(owners):
    """Missing initial or rechecked ownership never authorizes destructive SQL."""
    storage = Mock()
    storage.list_cleanup_messages.return_value = ["unowned"]
    storage.get_message_sessions.side_effect = owners
    storage.get_session_home.return_value = "home"
    probe = Mock(can_clean=Mock(return_value=True))
    history = HistoryCleanupManager(storage, probe)
    assert history.clean_messages(1) == 0
    assert storage.get_message_sessions.call_count == len(owners)
    storage.delete_cleanup_message.assert_not_called()
    assert probe.can_clean.call_count == len(owners) - 1
