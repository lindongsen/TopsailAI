"""Session management contract and explicit forwarding (author: DawsonLin)."""

from unittest.mock import Mock

import pytest

from topsailai.context import ctx_manager
from topsailai.context.session_manager.base import SessionManager
from topsailai.context.session_manager.manager import DefaultSessionManager
from topsailai.context.session_manager.__base import SessionData, SessionStorageBase


OPERATIONS = [
    ("exists_session", ("s",), {}),
    ("get_session", ("s",), {}),
    ("list_sessions", (), {"sessions": ["s"], "order_by": "create_time", "offset": 2, "limit": 3}),
    ("update_session_name", ("s", "name"), {}),
    ("retrieve_messages", ("s",), {}),
    ("get_messages_by_session", ("s",), {}),
    ("accumulate_session_tokens", ("s", 7, 3, 2), {}),
    ("get_session_token_totals", ("s",), {}),
    ("get_session_token_usage", ("s",), {}),
]


def test_abstract_contract_is_fully_implemented():
    """Reject incomplete managers and prove every contract member is explicit."""
    with pytest.raises(TypeError):
        SessionManager()
    assert not DefaultSessionManager.__abstractmethods__
    assert SessionManager.__abstractmethods__ == {
        "chat_history", "create_session", "delete_session", "clean_sessions",
        *(name for name, _, _ in OPERATIONS),
    }
    assert SessionManager.__abstractmethods__ <= DefaultSessionManager.__dict__.keys()
    assert "__getattr__" not in DefaultSessionManager.__dict__
    assert not issubclass(DefaultSessionManager, SessionStorageBase)


@pytest.mark.parametrize("name,args,kwargs", OPERATIONS)
def test_storage_delegation_preserves_arguments_and_result(name, args, kwargs):
    """Every ordinary operation explicitly reaches storage, not base stubs."""
    storage = Mock()
    manager = DefaultSessionManager(storage, Mock())
    result = object()
    getattr(storage, name).return_value = result
    assert getattr(manager, name)(*args, **kwargs) is result
    getattr(storage, name).assert_called_once_with(*args, **kwargs)


@pytest.mark.parametrize("name,args", [("delete_session", ("s",)), ("clean_sessions", (12,))])
def test_cleanup_delegation_never_calls_unprotected_storage(name, args):
    """Destructive operations always go through the cleanup coordinator."""
    storage = Mock()
    manager = DefaultSessionManager(storage, Mock())
    manager.cleanup = Mock()
    result = object()
    getattr(manager.cleanup, name).return_value = result
    assert getattr(manager, name)(*args) is result
    getattr(manager.cleanup, name).assert_called_once_with(*args)
    getattr(storage, name).assert_not_called()


@pytest.mark.parametrize("created", [False, True])
def test_create_then_evict_only_on_success(created):
    """Keep successful creation followed by protected soft-limit eviction."""
    storage = Mock()
    storage.create_session.return_value = created
    manager = DefaultSessionManager(storage, Mock())
    manager.cleanup = Mock()
    calls = Mock()
    calls.attach_mock(storage.create_session, "create")
    calls.attach_mock(manager.cleanup.evict_sessions, "evict")
    data = SessionData("s")
    assert manager.create_session(data) is created
    storage.create_session.assert_called_once_with(data)
    if created:
        manager.cleanup.evict_sessions.assert_called_once_with("s")
        assert [call[0] for call in calls.mock_calls] == ["create", "evict"]
    else:
        manager.cleanup.evict_sessions.assert_not_called()


def test_history_contract_keeps_ordinary_pruning_and_protected_cleanup():
    """Expose the same history storage while retaining fail-closed cleanup."""
    storage, probe = Mock(), Mock()
    manager = DefaultSessionManager(storage, probe)
    assert manager.chat_history.storage is storage.chat_history
    assert manager.chat_history.activity_probe is probe
    manager.chat_history.del_messages(session_id="s")
    storage.chat_history.del_messages.assert_called_once_with(session_id="s")
    storage.chat_history.list_cleanup_messages.return_value = ["orphan"]
    storage.chat_history.get_message_sessions.return_value = []
    assert manager.chat_history.clean_messages(1) == 0
    storage.chat_history.delete_cleanup_message.assert_not_called()


def test_default_arguments_and_exception_propagation():
    """Preserve defaults and do not swallow backend failures."""
    storage = Mock()
    manager = DefaultSessionManager(storage, Mock())
    manager.list_sessions()
    storage.list_sessions.assert_called_once_with(sessions=None, order_by=None, offset=0, limit=None)
    manager.accumulate_session_tokens("s", 2, 1)
    storage.accumulate_session_tokens.assert_called_once_with("s", 2, 1, 0)
    error = RuntimeError("backend failure")
    storage.get_session.side_effect = error
    with pytest.raises(RuntimeError) as caught:
        manager.get_session("s")
    assert caught.value is error


@pytest.mark.parametrize("source", ["explicit", "environment", "default"])
def test_factory_returns_management_contract_with_shared_probe(monkeypatch, source):
    """All connection-selection branches compose the same management contract."""
    storage, probe = Mock(), Mock()
    constructor = Mock(return_value=storage)
    monkeypatch.setattr(ctx_manager, "SessionSQLAlchemy", constructor)
    histories = [Mock(conn="environment")] if source == "environment" else []
    monkeypatch.setattr(ctx_manager, "get_managers_by_env", Mock(return_value=histories))
    manager = ctx_manager.get_session_manager(
        conn="explicit" if source == "explicit" else None,
        default_conn="default", activity_probe=probe,
    )
    assert isinstance(manager, SessionManager)
    assert isinstance(manager, DefaultSessionManager)
    assert manager.storage is storage
    assert manager.cleanup.storage is storage
    assert manager.cleanup.activity_probe is probe
    assert manager.chat_history.activity_probe is probe
    constructor.assert_called_once_with(source)
    assert ctx_manager.get_session_manager.__annotations__["return"] is SessionManager


@pytest.mark.parametrize("states,expected", [
    (["running"], 0),
    (["unknown"], 0),
    (["stopped", "running"], 0),
    (["stopped", "unknown"], 0),
    (["stopped", "stopped"], 1),
])
def test_factory_age_cleanup_rechecks_real_activity_probe(tmp_path, monkeypatch, states, expected):
    """Keep factory cleanup reachable and preserve both STOPPED authorization checks."""
    from datetime import datetime, timedelta
    from topsailai.context.session_activity import ActivityState, SessionActivityProbe

    task = tmp_path / "workspace" / "task"
    task.mkdir(parents=True)
    (task / "s.123.session.meta").write_text('{"session_id": "s", "pid": 123}')
    observer = Mock(side_effect=[ActivityState(state) for state in states])
    probe = SessionActivityProbe((task,), observer)
    row = SessionData("s", topsailai_home=str(tmp_path))
    row.create_time = datetime.now() - timedelta(days=40)
    storage = Mock()
    storage.list_sessions.return_value = [row]
    storage.delete_session.return_value = True
    monkeypatch.setattr(ctx_manager, "SessionSQLAlchemy", Mock(return_value=storage))
    manager = ctx_manager.get_session_manager("sqlite:///:memory:", activity_probe=probe)

    assert "clean_sessions" in SessionManager.__abstractmethods__
    assert "clean_sessions" in DefaultSessionManager.__dict__
    assert not DefaultSessionManager.__abstractmethods__
    assert manager.clean_sessions(before_seconds=1) == expected
    assert observer.call_count == len(states)
    assert all(call.args == (123,) for call in observer.call_args_list)
    storage.clean_sessions.assert_not_called()
    if expected:
        storage.delete_session.assert_called_once_with("s")
    else:
        storage.delete_session.assert_not_called()
