"""Session category tests for the session agent driver.

Author: DawsonLin
"""

import json
from pathlib import Path
from unittest import mock

import pytest
from sqlalchemy import text

import session_agent_driver as sad
class _FakeRuntimeData:
    """Minimal runtime data object for the real agent factory path."""

    def __init__(self, storage=None):
        self.messages = []
        self.session_id = ""
        self.session_data = None
        self._storage = storage

    def init(self, session_id, ai_agent=None):
        self.session_id = session_id
        if self._storage is not None:
            self.session_data = self._storage.get_session(session_id)

class _FakeAgent:
    """Minimal agent object accepted by the real agent factory path."""

    def __init__(self):
        self.runtime = type("Runtime", (), {})()
        self.runtime.llm_model = type(
            "Model", (), {"max_tokens": 4096, "temperature": 0.3}
        )()


def _driver_patches(monkeypatch, factory):
    """Patch only driver-side runtime effects around one analysis round."""
    monkeypatch.setattr(sad, "check_session_status", lambda session_id: "input")
    monkeypatch.setattr(sad, "get_session_info", lambda session_id: {"status": "input"})
    monkeypatch.setattr(sad, "render_analysis_prompt", lambda info: "task")
    monkeypatch.setattr(sad, "get_agent_chat", factory)
    monkeypatch.setattr(sad, "cleanup_analysis_session", lambda session_id: None)
    monkeypatch.setattr(sad.signal, "signal", lambda *args: object())
    monkeypatch.setattr(sad.signal, "alarm", lambda value: None)
    monkeypatch.setattr(sad, "_session_snapshot", lambda session_id: ([], []))


def test_analysis_factory_receives_explicit_driver_category(monkeypatch):
    """The analysis factory receives the fixed category and a private ID."""
    calls = []

    def factory(**kwargs):
        calls.append(kwargs)
        return mock.Mock(run=mock.Mock())

    _driver_patches(monkeypatch, factory)
    sad.run_analysis_agent("target-session")

    assert calls[0]["session_category"] == "agent_driver"
    assert calls[0]["session_id"].startswith(sad.ANALYSIS_SESSION_PREFIX)
    assert calls[0]["session_id"] != "target-session"


@pytest.mark.parametrize("environment_value", [None, "", "hosting", "Agent", "agent\n"])
def test_analysis_category_persists_in_sqlite(monkeypatch, environment_value):
    """The real Agent factory persists the driver category despite the environment."""
    from topsailai.context import ctx_manager
    from topsailai.context.session_manager.sql import SessionSQLAlchemy
    from topsailai.workspace import agent_shell

    storage = SessionSQLAlchemy("sqlite:///:memory:")
    if environment_value is None:
        monkeypatch.delenv("TOPSAILAI_SESSION_CATEGORY", raising=False)
    else:
        monkeypatch.setenv("TOPSAILAI_SESSION_CATEGORY", environment_value)
    monkeypatch.setenv("TOPSAILAI_AUTO_SESSION_NAME_ENABLED", "0")
    monkeypatch.setattr(ctx_manager, "get_session_manager", lambda: storage)
    monkeypatch.setattr(agent_shell, "get_ai_agent", lambda **kwargs: _FakeAgent())
    monkeypatch.setattr(agent_shell, "ContextRuntimeData", lambda: _FakeRuntimeData(storage))
    monkeypatch.setattr(agent_shell, "ContextRuntimeAIAgent", lambda data: object())
    monkeypatch.setattr(agent_shell, "ContextRuntimeInstructions", lambda data: type(
        "Instructions", (), {"instructions": {}})())
    monkeypatch.setattr(agent_shell, "HookInstruction", lambda **kwargs: type(
        "Hooks", (), {"load_instructions": lambda self, instructions: None})())
    monkeypatch.setattr(agent_shell, "AgentChat", lambda **kwargs: mock.Mock())
    monkeypatch.setattr(agent_shell, "record_project_history", lambda session_id: None)
    monkeypatch.setattr(agent_shell, "create_session_meta", lambda **kwargs: None)
    monkeypatch.setattr(agent_shell, "cleanup_session_meta_files", lambda: None)
    monkeypatch.setattr(agent_shell, "print_tool", type(
        "Print", (), {"print_info": staticmethod(lambda value: None)})())
    monkeypatch.setattr(agent_shell, "_cleanup_stale_interrupt_flag", lambda *args: None)
    monkeypatch.setattr(agent_shell, "get_message", lambda **kwargs: "task")

    captured = {}

    def factory(**kwargs):
        captured.update(kwargs)
        return agent_shell.get_agent_chat(**kwargs)

    _driver_patches(monkeypatch, factory)
    sad.run_analysis_agent("target-session")

    with storage.engine.connect() as connection:
        category = connection.execute(text(
            "SELECT category FROM session WHERE session_id LIKE 'sad-%'"
        )).scalar_one()
    assert category == "agent_driver"
    assert captured["session_category"] == "agent_driver"


def test_analysis_category_preserves_parent_environment(monkeypatch):
    """An inherited category remains unchanged when the driver starts."""
    monkeypatch.setenv("TOPSAILAI_SESSION_CATEGORY", "hosting")
    loader = mock.Mock(side_effect=AssertionError("driver must not load category"))
    calls = []

    def factory(**kwargs):
        calls.append(kwargs)
        return mock.Mock(run=mock.Mock())

    _driver_patches(monkeypatch, factory)
    with mock.patch("topsailai.workspace.agent_shell.load_session_category", loader):
        sad.run_analysis_agent("target-session")

    assert sad.os.environ["TOPSAILAI_SESSION_CATEGORY"] == "hosting"
    assert calls[0]["session_category"] == "agent_driver"
    loader.assert_not_called()


@pytest.mark.parametrize("target_category", ["hosting", ""])
def test_analysis_category_does_not_reclassify_target(monkeypatch, target_category):
    """Real SQLite target categories remain unchanged beside the analysis row."""
    from topsailai.context import ctx_manager
    from topsailai.context.session_manager.__base import SessionData
    from topsailai.context.session_manager.sql import SessionSQLAlchemy
    from topsailai.workspace import agent_shell

    target_session_id = f"target-{target_category or 'empty'}"
    storage = SessionSQLAlchemy("sqlite:///:memory:")
    storage.create_session(SessionData(
        session_id=target_session_id,
        task="target task",
        category=target_category,
    ))
    monkeypatch.setenv("TOPSAILAI_AUTO_SESSION_NAME_ENABLED", "0")
    monkeypatch.setattr(ctx_manager, "get_session_manager", lambda: storage)
    monkeypatch.setattr(agent_shell, "get_ai_agent", lambda **kwargs: _FakeAgent())
    monkeypatch.setattr(agent_shell, "ContextRuntimeData", lambda: _FakeRuntimeData(storage))
    monkeypatch.setattr(agent_shell, "ContextRuntimeAIAgent", lambda data: object())
    monkeypatch.setattr(agent_shell, "ContextRuntimeInstructions", lambda data: type(
        "Instructions", (), {"instructions": {}})())
    monkeypatch.setattr(agent_shell, "HookInstruction", lambda **kwargs: type(
        "Hooks", (), {"load_instructions": lambda self, instructions: None})())
    monkeypatch.setattr(agent_shell, "AgentChat", lambda **kwargs: mock.Mock())
    monkeypatch.setattr(agent_shell, "record_project_history", lambda session_id: None)
    monkeypatch.setattr(agent_shell, "create_session_meta", lambda **kwargs: None)
    monkeypatch.setattr(agent_shell, "cleanup_session_meta_files", lambda: None)
    monkeypatch.setattr(agent_shell, "print_tool", type(
        "Print", (), {"print_info": staticmethod(lambda value: None)})())
    monkeypatch.setattr(agent_shell, "_cleanup_stale_interrupt_flag", lambda *args: None)
    monkeypatch.setattr(agent_shell, "get_message", lambda **kwargs: "task")

    captured = {}

    def factory(**kwargs):
        captured.update(kwargs)
        return agent_shell.get_agent_chat(**kwargs)

    _driver_patches(monkeypatch, factory)
    sad.run_analysis_agent(target_session_id)

    with storage.engine.connect() as connection:
        rows = connection.execute(text(
            "SELECT session_id, category FROM session ORDER BY session_id"
        )).all()
    categories = {row.session_id: row.category for row in rows}
    analysis_ids = [session_id for session_id in categories if session_id.startswith("sad-")]
    assert categories[target_session_id] == target_category
    assert len(analysis_ids) == 1
    assert analysis_ids[0] != target_session_id
    assert categories[analysis_ids[0]] == "agent_driver"
    assert captured["session_id"] == analysis_ids[0]
    assert captured["session_category"] == "agent_driver"


@pytest.mark.parametrize("target_category", ["hosting", ""])
def test_analysis_meta_persists_driver_category(monkeypatch, tmp_path, target_category):
    """Real SQLite persistence and the real metadata writer store the category.

    The runtime object is intentionally isolated because exercising the complete
    AgentChat lifecycle is outside this metadata persistence contract; the
    production factory and storage/meta writers remain real.
    """
    from topsailai.context import ctx_manager
    from topsailai.context.session_manager.sql import SessionSQLAlchemy
    from topsailai.workspace import agent_shell, session_meta

    storage = SessionSQLAlchemy("sqlite:///:memory:")
    monkeypatch.setenv("TOPSAILAI_AUTO_SESSION_NAME_ENABLED", "0")
    monkeypatch.setattr(ctx_manager, "get_session_manager", lambda: storage)
    monkeypatch.setattr(agent_shell, "get_ai_agent", lambda **kwargs: _FakeAgent())
    monkeypatch.setattr(agent_shell, "ContextRuntimeData", lambda: _FakeRuntimeData(storage))
    monkeypatch.setattr(agent_shell, "ContextRuntimeAIAgent", lambda data: object())
    monkeypatch.setattr(agent_shell, "ContextRuntimeInstructions", lambda data: type(
        "Instructions", (), {"instructions": {}})())
    monkeypatch.setattr(agent_shell, "HookInstruction", lambda **kwargs: type(
        "Hooks", (), {"load_instructions": lambda self, instructions: None})())
    monkeypatch.setattr(agent_shell, "AgentChat", lambda **kwargs: mock.Mock())
    monkeypatch.setattr(agent_shell, "record_project_history", lambda session_id: None)
    monkeypatch.setattr(agent_shell, "cleanup_session_meta_files", lambda: None)
    monkeypatch.setattr(agent_shell, "print_tool", type(
        "Print", (), {"print_info": staticmethod(lambda value: None)})())
    monkeypatch.setattr(agent_shell, "_cleanup_stale_interrupt_flag", lambda *args: None)
    monkeypatch.setattr(agent_shell, "get_message", lambda **kwargs: "task")
    monkeypatch.setenv("TOPSAILAI_SESSION_CATEGORY", target_category)
    monkeypatch.setattr(session_meta, "FOLDER_WORKSPACE_TASK", str(tmp_path))

    def factory(**kwargs):
        return agent_shell.get_agent_chat(**kwargs)

    _driver_patches(monkeypatch, factory)
    sad.run_analysis_agent("target-session")

    with storage.engine.connect() as connection:
        row = connection.execute(text(
            "SELECT session_id, category FROM session WHERE session_id LIKE 'sad-%'"
        )).one()
    meta_files = list(Path(tmp_path).glob(f"{row.session_id}.*.session.meta"))
    assert row.category == "agent_driver"
    assert len(meta_files) == 1
    assert json.loads(meta_files[0].read_text())["category"] == "agent_driver"
