"""Unit tests for session category configuration and creation forwarding."""

import logging
import os
import re
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import event

from topsailai.context.session_category import load_session_category


@pytest.mark.parametrize("value", ["agent", "chat_2", "hosting", "123", "___"])
def test_load_session_category_accepts_valid_values(value):
    """Valid lowercase category formats are returned unchanged."""
    assert load_session_category({"TOPSAILAI_SESSION_CATEGORY": value}) == value


def test_load_session_category_missing_or_empty_is_silent(caplog):
    """Missing and empty category configuration resolve to empty silently."""
    with caplog.at_level(logging.ERROR):
        assert load_session_category({}) == ""
        assert load_session_category({"TOPSAILAI_SESSION_CATEGORY": ""}) == ""
    assert not caplog.records


@pytest.mark.parametrize("value", ["Agent", "chat x", "chat-x", "聊天", "agent\n"])
def test_load_session_category_rejects_invalid_values(caplog, value):
    """Invalid category configuration logs ERROR and resolves to empty."""
    with caplog.at_level(logging.ERROR):
        result = load_session_category({"TOPSAILAI_SESSION_CATEGORY": value})

    assert result == ""
    records = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert len(records) == 1
    assert repr(value)[1:-1] in records[0].message


def test_ctx_create_session_forwards_explicit_category():
    """The context facade forwards category explicitly into SessionData."""
    from topsailai.context import ctx_manager
    from topsailai.context.session_manager.__base import SessionData

    manager = MagicMock()
    with patch.object(ctx_manager, "_get_session_environment_paths", return_value={
        "project_workspace": None,
        "pwd": None,
        "topsailai_home": None,
    }), patch.object(ctx_manager, "threading"):
        assert ctx_manager.create_session(
            "session",
            "task",
            session_mgr=manager,
            category="chat_2",
        )

    data = manager.create_session.call_args.args[0]
    assert isinstance(data, SessionData)
    assert data.category == "chat_2"


def test_agent_factory_uses_environment_category_once():
    """Agent factory resolves environment category and forwards it."""
    from topsailai.workspace import agent_shell

    with patch.object(agent_shell, "load_session_category", return_value="agent") as load:
        with patch.object(agent_shell, "_get_agent_chat_impl", return_value="chat") as impl:
            with patch.object(agent_shell, "ctxm_void") as lock:
                lock.return_value.__enter__.return_value = True
                lock.return_value.__exit__.return_value = False
                assert agent_shell.get_agent_chat(need_project_workspace_lock=False) == "chat"

    load.assert_called_once_with(os.environ)
    assert impl.call_args.kwargs["session_category"] == "agent"


def test_llm_factory_forwards_environment_category_to_session_creation():
    """LLM factory passes its resolved category to the context facade."""
    from topsailai.workspace import llm_shell

    model = MagicMock(max_tokens=4096, temperature=0.3, content_senders=[])
    prompt = MagicMock(messages=[])
    with patch.object(llm_shell, "load_session_category", return_value="hosting"), \
            patch.object(llm_shell, "get_message", return_value="task"), \
            patch.object(llm_shell, "file_tool") as file_tool, \
            patch.object(llm_shell, "LLMModel", return_value=model), \
            patch.object(llm_shell, "PromptBase", return_value=prompt), \
            patch.object(llm_shell, "record_project_history"), \
            patch.object(llm_shell.ctx_manager, "get_messages_by_session", return_value=[]), \
            patch.object(llm_shell.ctx_manager, "create_session") as create:
        file_tool.get_file_content_fuzzy.return_value = (True, "system")
        llm_shell.get_llm_chat(
            message="task",
            session_id="session",
            need_input_message=False,
            need_print_session=False,
        )

    assert create.call_args.kwargs["category"] == "hosting"


class _FakeRuntimeData:
    """Minimal context runtime used by real agent factory persistence tests."""

    def __init__(self):
        self.messages = []
        self.session_id = ""
        self.session_data = None

    def init(self, session_id, ai_agent=None):
        self.session_id = session_id


class _FakeAgent:
    """Minimal agent object accepted by the real agent factory path."""

    def __init__(self):
        self.runtime = type("Runtime", (), {})()
        self.runtime.llm_model = type("Model", (), {
            "max_tokens": 4096,
            "temperature": 0.3,
        })()


def test_agent_factory_persists_environment_category_in_real_sqlite(monkeypatch):
    """The agent factory reaches the real facade and SQLite storage."""
    from sqlalchemy import text
    from topsailai.context import ctx_manager
    from topsailai.context.session_manager.sql import SessionSQLAlchemy
    from topsailai.workspace import agent_shell

    storage = SessionSQLAlchemy("sqlite:///:memory:")
    monkeypatch.setenv("TOPSAILAI_SESSION_CATEGORY", "agent")
    monkeypatch.setenv("TOPSAILAI_AUTO_SESSION_NAME_ENABLED", "0")
    monkeypatch.setattr(ctx_manager, "get_session_manager", lambda: storage)
    monkeypatch.setattr(agent_shell, "get_ai_agent", lambda **kwargs: _FakeAgent())
    monkeypatch.setattr(agent_shell, "ContextRuntimeData", _FakeRuntimeData)
    monkeypatch.setattr(agent_shell, "ContextRuntimeAIAgent", lambda data: object())
    monkeypatch.setattr(agent_shell, "ContextRuntimeInstructions", lambda data: type(
        "Instructions", (), {"instructions": {}})())
    monkeypatch.setattr(agent_shell, "HookInstruction", lambda **kwargs: type("Hooks", (), {
        "load_instructions": lambda self, instructions: None,
    })())
    monkeypatch.setattr(agent_shell, "AgentChat", lambda **kwargs: type("Chat", (), {})())
    monkeypatch.setattr(agent_shell, "record_project_history", lambda session_id: None)
    monkeypatch.setattr(agent_shell, "create_session_meta", lambda **kwargs: None)
    monkeypatch.setattr(agent_shell, "cleanup_session_meta_files", lambda: None)
    monkeypatch.setattr(agent_shell, "print_tool", type("Print", (), {
        "print_info": staticmethod(lambda value: None),
    })())
    monkeypatch.setattr(agent_shell, "_cleanup_stale_interrupt_flag", lambda session_id, pid: None)
    monkeypatch.setattr(agent_shell, "get_message", lambda **kwargs: "")

    agent_shell.get_agent_chat(
        session_id="agent-factory",
        message="task",
        need_input_message=False,
        need_print_session=False,
        need_project_workspace_lock=False,
    )

    with storage.engine.connect() as connection:
        assert connection.execute(text(
            "SELECT category FROM session WHERE session_id = 'agent-factory'"
        )).scalar_one() == "agent"

def test_llm_factory_persists_environment_category_in_real_sqlite(monkeypatch):
    """The LLM factory reaches the real facade and SQLite storage."""
    from sqlalchemy import text
    from topsailai.context import ctx_manager
    from topsailai.context.session_manager.sql import SessionSQLAlchemy
    from topsailai.workspace import llm_shell

    storage = SessionSQLAlchemy("sqlite:///:memory:")
    monkeypatch.setenv("TOPSAILAI_SESSION_CATEGORY", "hosting")
    monkeypatch.setattr(ctx_manager, "get_session_manager", lambda: storage)
    monkeypatch.setattr(llm_shell, "record_project_history", lambda session_id: None)
    monkeypatch.setattr(llm_shell.file_tool, "get_file_content_fuzzy", lambda value: (True, ""))
    monkeypatch.setattr(llm_shell, "LLMModel", lambda: type("Model", (), {
        "content_senders": [], "max_tokens": 4096, "temperature": 0.3,
    })())
    monkeypatch.setattr(llm_shell, "PromptBase", lambda *args, **kwargs: type("Prompt", (), {
        "messages": [],
        "new_session": lambda self, *args, **kwargs: None,
        "add_user_message": lambda self, *args, **kwargs: None,
    })())

    llm_shell.get_llm_chat(
        message="task",
        session_id="llm-factory",
        need_input_message=False,
        need_print_session=False,
        need_stdout=False,
    )

    with storage.engine.connect() as connection:
        assert connection.execute(text(
            "SELECT category FROM session WHERE session_id = 'llm-factory'"
        )).scalar_one() == "hosting"



def _query_session_category(storage, session_id):
    """Read the persisted category directly from SQLite."""
    from sqlalchemy import text

    with storage.engine.connect() as connection:
        return connection.execute(
            text("SELECT category FROM session WHERE session_id = :session_id"),
            {"session_id": session_id},
        ).scalar_one()


def _patch_real_agent_factory(monkeypatch, storage):
    """Keep the agent factory path real while isolating unrelated startup work."""
    from topsailai.context import ctx_manager
    from topsailai.workspace import agent_shell

    monkeypatch.setattr(ctx_manager, "get_session_manager", lambda: storage)
    monkeypatch.setattr(agent_shell, "get_ai_agent", lambda **kwargs: _FakeAgent())
    monkeypatch.setattr(agent_shell, "ContextRuntimeData", _FakeRuntimeData)
    monkeypatch.setattr(agent_shell, "ContextRuntimeAIAgent", lambda data: object())
    monkeypatch.setattr(agent_shell, "ContextRuntimeInstructions", lambda data: type(
        "Instructions", (), {"instructions": {}})())
    monkeypatch.setattr(agent_shell, "HookInstruction", lambda **kwargs: type("Hooks", (), {
        "load_instructions": lambda self, instructions: None,
    })())
    monkeypatch.setattr(agent_shell, "AgentChat", lambda **kwargs: type("Chat", (), {})())
    monkeypatch.setattr(agent_shell, "record_project_history", lambda session_id: None)
    monkeypatch.setattr(agent_shell, "create_session_meta", lambda **kwargs: None)
    monkeypatch.setattr(agent_shell, "cleanup_session_meta_files", lambda: None)
    monkeypatch.setattr(agent_shell, "print_tool", type("Print", (), {
        "print_info": staticmethod(lambda value: None),
    })())
    monkeypatch.setattr(agent_shell, "_cleanup_stale_interrupt_flag", lambda session_id, pid: None)
    monkeypatch.setattr(agent_shell, "get_message", lambda **kwargs: "")
    monkeypatch.setenv("TOPSAILAI_AUTO_SESSION_NAME_ENABLED", "0")
    return agent_shell


def _patch_real_llm_factory(monkeypatch, storage):
    """Keep the LLM factory and persistence path real while isolating the model."""
    from topsailai.context import ctx_manager
    from topsailai.workspace import llm_shell

    monkeypatch.setattr(ctx_manager, "get_session_manager", lambda: storage)
    monkeypatch.setattr(ctx_manager, "generate_session_name", lambda session_id, message: "")
    monkeypatch.setattr(llm_shell, "record_project_history", lambda session_id: None)
    monkeypatch.setattr(llm_shell.file_tool, "get_file_content_fuzzy", lambda value: (True, ""))
    monkeypatch.setattr(llm_shell, "LLMModel", lambda: type("Model", (), {
        "content_senders": [], "max_tokens": 4096, "temperature": 0.3,
    })())
    monkeypatch.setattr(llm_shell, "PromptBase", lambda *args, **kwargs: type("Prompt", (), {
        "messages": [],
        "new_session": lambda self, *args, **kwargs: None,
        "add_user_message": lambda self, *args, **kwargs: None,
    })())
    return llm_shell


@pytest.mark.parametrize("environment_value", ["", "Agent", "chat x", "chat-x", "聊天", "agent\n"])
def test_agent_environment_categories_reach_storage_as_empty(
    monkeypatch, caplog, environment_value
):
    """Invalid agent environment categories reach SQLite as a real empty string."""
    from topsailai.context.session_manager.sql import SessionSQLAlchemy

    storage = SessionSQLAlchemy("sqlite:///:memory:")
    agent_shell = _patch_real_agent_factory(monkeypatch, storage)
    monkeypatch.setenv("TOPSAILAI_SESSION_CATEGORY", environment_value)
    session_id = "agent-environment-" + str(abs(hash(environment_value)))

    with caplog.at_level(logging.ERROR):
        agent_shell.get_agent_chat(
            session_id=session_id,
            message="task",
            need_input_message=False,
            need_print_session=False,
            need_project_workspace_lock=False,
        )

    assert _query_session_category(storage, session_id) == ""
    if environment_value:
        assert any(record.levelno == logging.ERROR for record in caplog.records)
        assert repr(environment_value)[1:-1] in caplog.text
    else:
        assert not caplog.records


@pytest.mark.parametrize("environment_value", ["", "Agent", "chat x", "chat-x", "聊天", "agent\n"])
def test_llm_environment_categories_reach_storage_as_empty(
    monkeypatch, caplog, environment_value
):
    """Invalid LLM environment categories reach SQLite as a real empty string."""
    from topsailai.context.session_manager.sql import SessionSQLAlchemy

    storage = SessionSQLAlchemy("sqlite:///:memory:")
    llm_shell = _patch_real_llm_factory(monkeypatch, storage)
    monkeypatch.setenv("TOPSAILAI_SESSION_CATEGORY", environment_value)
    session_id = "llm-environment-" + str(abs(hash(environment_value)))

    with caplog.at_level(logging.ERROR):
        llm_shell.get_llm_chat(
            message="task",
            session_id=session_id,
            need_input_message=False,
            need_print_session=False,
            need_stdout=False,
        )

    assert _query_session_category(storage, session_id) == ""
    if environment_value:
        assert any(record.levelno == logging.ERROR for record in caplog.records)
        assert repr(environment_value)[1:-1] in caplog.text
    else:
        assert not caplog.records


def _record_category_updates(storage):
    """Record category updates on the real SQLAlchemy engine."""
    statements = []

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        normalized = re.sub(r"\s+", " ", statement).strip().lower()
        if normalized.startswith("update ") and "session" in normalized and "category" in normalized:
            statements.append(statement)

    event.listen(storage.engine, "before_cursor_execute", before_cursor_execute)
    return statements, before_cursor_execute


def test_agent_explicit_category_overrides_environment_without_loading(monkeypatch):
    """An explicit agent category bypasses environment resolution and persists."""
    from topsailai.context.session_manager.sql import SessionSQLAlchemy

    storage = SessionSQLAlchemy("sqlite:///:memory:")
    agent_shell = _patch_real_agent_factory(monkeypatch, storage)
    monkeypatch.setenv("TOPSAILAI_SESSION_CATEGORY", "agent")
    loader_calls = []
    monkeypatch.setattr(agent_shell, "load_session_category", lambda environ: loader_calls.append(1))

    agent_shell.get_agent_chat(
        session_id="agent-explicit",
        message="task",
        session_category="chat",
        need_input_message=False,
        need_print_session=False,
        need_project_workspace_lock=False,
    )

    assert loader_calls == []
    assert _query_session_category(storage, "agent-explicit") == "chat"


def test_agent_explicit_empty_category_overrides_environment(monkeypatch):
    """An explicit empty agent category is not replaced by the environment."""
    from topsailai.context.session_manager.sql import SessionSQLAlchemy

    storage = SessionSQLAlchemy("sqlite:///:memory:")
    agent_shell = _patch_real_agent_factory(monkeypatch, storage)
    monkeypatch.setenv("TOPSAILAI_SESSION_CATEGORY", "agent")

    agent_shell.get_agent_chat(
        session_id="agent-empty",
        message="task",
        session_category="",
        need_input_message=False,
        need_print_session=False,
        need_project_workspace_lock=False,
    )

    assert _query_session_category(storage, "agent-empty") == ""


def test_agent_existing_session_keeps_category_without_update(monkeypatch):
    """Reopening an agent session does not reclassify or update its category."""
    from sqlalchemy import text
    from topsailai.context.session_manager.sql import SessionSQLAlchemy

    storage = SessionSQLAlchemy("sqlite:///:memory:")
    agent_shell = _patch_real_agent_factory(monkeypatch, storage)
    monkeypatch.setenv("TOPSAILAI_SESSION_CATEGORY", "agent")
    agent_shell.get_agent_chat(
        session_id="agent-existing",
        message="task",
        need_input_message=False,
        need_print_session=False,
        need_project_workspace_lock=False,
    )

    monkeypatch.setenv("TOPSAILAI_SESSION_CATEGORY", "chat")
    statements, listener = _record_category_updates(storage)
    try:
        agent_shell.get_agent_chat(
            session_id="agent-existing",
            message="task",
            need_input_message=False,
            need_print_session=False,
            need_project_workspace_lock=False,
        )
    finally:
        event.remove(storage.engine, "before_cursor_execute", listener)

    with storage.engine.connect() as connection:
        after = connection.execute(text(
            "SELECT category FROM session WHERE session_id = 'agent-existing'"
        )).one()

    assert after.category == "agent"
    assert statements == []


def test_llm_explicit_category_overrides_environment_without_loading(monkeypatch):
    """An explicit LLM category bypasses environment resolution and persists."""
    from topsailai.context.session_manager.sql import SessionSQLAlchemy

    storage = SessionSQLAlchemy("sqlite:///:memory:")
    llm_shell = _patch_real_llm_factory(monkeypatch, storage)
    monkeypatch.setenv("TOPSAILAI_SESSION_CATEGORY", "agent")
    loader_calls = []
    monkeypatch.setattr(llm_shell, "load_session_category", lambda environ: loader_calls.append(1))

    llm_shell.get_llm_chat(
        message="task",
        session_id="llm-explicit",
        session_category="chat",
        need_input_message=False,
        need_print_session=False,
        need_stdout=False,
    )

    assert loader_calls == []
    assert _query_session_category(storage, "llm-explicit") == "chat"


def test_llm_explicit_empty_category_overrides_environment(monkeypatch):
    """An explicit empty LLM category is not replaced by the environment."""
    from topsailai.context.session_manager.sql import SessionSQLAlchemy

    storage = SessionSQLAlchemy("sqlite:///:memory:")
    llm_shell = _patch_real_llm_factory(monkeypatch, storage)
    monkeypatch.setenv("TOPSAILAI_SESSION_CATEGORY", "agent")

    llm_shell.get_llm_chat(
        message="task",
        session_id="llm-empty",
        session_category="",
        need_input_message=False,
        need_print_session=False,
        need_stdout=False,
    )

    assert _query_session_category(storage, "llm-empty") == ""


def test_llm_existing_session_keeps_category_without_update(monkeypatch):
    """Reopening an LLM session does not reclassify or update its category."""
    from topsailai.context import ctx_manager
    from sqlalchemy import text
    from topsailai.context.session_manager.sql import SessionSQLAlchemy

    storage = SessionSQLAlchemy("sqlite:///:memory:")
    llm_shell = _patch_real_llm_factory(monkeypatch, storage)
    monkeypatch.setenv("TOPSAILAI_SESSION_CATEGORY", "agent")
    llm_shell.get_llm_chat(
        message="task",
        session_id="llm-existing",
        need_input_message=False,
        need_print_session=False,
        need_stdout=False,
    )

    monkeypatch.setenv("TOPSAILAI_SESSION_CATEGORY", "chat")
    monkeypatch.setattr(ctx_manager, "get_messages_by_session", lambda session_id: [{
        "role": "user", "content": "existing",
    }])
    statements, listener = _record_category_updates(storage)
    try:
        llm_shell.get_llm_chat(
            message="task",
            session_id="llm-existing",
            need_input_message=False,
            need_print_session=False,
            need_stdout=False,
        )
    finally:
        event.remove(storage.engine, "before_cursor_execute", listener)

    with storage.engine.connect() as connection:
        after = connection.execute(text(
            "SELECT category FROM session WHERE session_id = 'llm-existing'"
        )).one()

    assert after.category == "agent"
    assert statements == []
