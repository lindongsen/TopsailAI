"""Extended session metrics: storage semantics and hook-module behaviour.

Author: DawsonLin

Covers the additive, peak and last-write semantics of
``accumulate_session_metrics``, the legacy SQLite migration, the dedicated
settle hook module, and the two heavy-task counter modules.
"""

import importlib
import sqlite3
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from topsailai.context.session_manager.sql import SessionSQLAlchemy

NEW_COLUMNS = (
    "response_content_errors", "first_byte_sum_ms", "first_byte_count",
    "requests_per_minute_max", "turn_failure_count", "turn_back_count",
    "turn_interrupt_count", "max_prompt_tokens", "model_name",
    "heavy_task_warning_count", "heavy_task_block_count",
)

LEGACY_DDL = """
CREATE TABLE session (
  session_id VARCHAR(32) PRIMARY KEY, session_name TEXT, task TEXT NOT NULL,
  project_workspace TEXT, pwd TEXT, topsailai_home TEXT,
  total_tokens INTEGER DEFAULT 0, total_cached_tokens INTEGER DEFAULT 0,
  total_completion_tokens INTEGER DEFAULT 0, summary_count INTEGER DEFAULT 0,
  turn_count INTEGER DEFAULT 0, tool_call_count INTEGER DEFAULT 0,
  tool_error_count INTEGER DEFAULT 0, llm_request_count INTEGER DEFAULT 0,
  llm_request_failure_count INTEGER DEFAULT 0, tool_duration_ms_sum INTEGER DEFAULT 0,
  llm_request_duration_ms_sum INTEGER DEFAULT 0,
  create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  category TEXT NOT NULL DEFAULT '')
"""

SETTLE_MODULE = (
    "topsailai.hooks.points.workspace.after_attempt_settle_user2agent.modules"
    ".session_metrics_ext"
)
WARNING_MODULE = (
    "topsailai.hooks.points.workspace.after_heavy_task_warning.modules"
    ".session_heavy_task"
)
BLOCK_MODULE = (
    "topsailai.hooks.points.workspace.error_heavy_task_terminated.modules"
    ".session_heavy_task"
)


@pytest.fixture()
def legacy_storage(tmp_path):
    """Build a legacy database without the new columns, then migrate it."""
    db_path = tmp_path / "legacy.db"
    connection = sqlite3.connect(str(db_path))
    connection.execute(LEGACY_DDL)
    connection.execute("INSERT INTO session (session_id, task) VALUES ('s1', 't')")
    connection.commit()
    connection.close()
    return SessionSQLAlchemy(f"sqlite:///{db_path}"), db_path


def test_legacy_database_gains_every_new_column(legacy_storage):
    """A pre-existing database must be migrated, not left without the columns."""
    _storage, db_path = legacy_storage
    connection = sqlite3.connect(str(db_path))
    columns = {row[1] for row in connection.execute("PRAGMA table_info(session)")}
    connection.close()
    assert set(NEW_COLUMNS) <= columns


def test_additive_counters_are_summed(legacy_storage):
    """Additive counters accumulate across attempts."""
    storage, _ = legacy_storage
    storage.accumulate_session_metrics(
        "s1", turn_count=1, turn_failure_count=1, first_byte_sum_ms=100,
        first_byte_count=2, heavy_task_warning_count=1,
    )
    storage.accumulate_session_metrics(
        "s1", turn_count=1, turn_back_count=1, first_byte_sum_ms=50,
        first_byte_count=1, heavy_task_block_count=1,
    )
    data = storage.get_session("s1")
    assert data.turn_count == 2
    assert data.turn_failure_count == 1
    assert data.turn_back_count == 1
    assert data.first_byte_sum_ms == 150
    assert data.first_byte_count == 3
    assert data.heavy_task_warning_count == 1
    assert data.heavy_task_block_count == 1


def test_peak_counters_never_regress(legacy_storage):
    """A smaller later observation must not lower a recorded peak."""
    storage, _ = legacy_storage
    storage.accumulate_session_metrics(
        "s1", requests_per_minute_max=9, max_prompt_tokens=900,
    )
    storage.accumulate_session_metrics(
        "s1", requests_per_minute_max=3, max_prompt_tokens=400,
    )
    data = storage.get_session("s1")
    assert data.requests_per_minute_max == 9
    assert data.max_prompt_tokens == 900


def test_model_name_is_last_write_and_empty_never_erases(legacy_storage):
    """An empty model name must not overwrite a known one."""
    storage, _ = legacy_storage
    storage.accumulate_session_metrics("s1", model_name="m-a")
    storage.accumulate_session_metrics("s1", model_name="")
    assert storage.get_session("s1").model_name == "m-a"
    storage.accumulate_session_metrics("s1", model_name="m-b")
    assert storage.get_session("s1").model_name == "m-b"


def test_negative_deltas_are_clamped(legacy_storage):
    """A misreported negative value must never subtract from the totals."""
    storage, _ = legacy_storage
    storage.accumulate_session_metrics("s1", turn_count=2)
    storage.accumulate_session_metrics("s1", turn_count=-5, first_byte_sum_ms=-10)
    data = storage.get_session("s1")
    assert data.turn_count == 2
    assert data.first_byte_sum_ms == 0


def test_missing_session_reports_false(legacy_storage):
    """A missing session is a business result, not an exception."""
    storage, _ = legacy_storage
    assert storage.accumulate_session_metrics("absent", turn_count=1) is False


class _Binding:
    """Minimal binding stand-in.

    A ``Mock`` cannot be used here: it answers every attribute with a truthy
    Mock, so the module's baseline lookup would return a Mock instead of the
    ``None`` that a real binding returns before the first settled attempt.
    """

    def __init__(self, authorized=True):
        self._authorized = authorized

    def settle_authorized(self, agent):
        """Report whether this settlement may write metrics."""
        return self._authorized


class _Attempt:
    """Minimal attempt stand-in carrying a real binding object."""

    def __init__(self, authorized=True):
        self.binding = _Binding(authorized)


def _fake_agent(state):
    """Build a minimal agent exposing the trackers the settle module reads."""
    token_stat = Mock()
    token_stat.first_byte_sum_ms = state["first_byte_sum_ms"]
    token_stat.first_byte_count = state["first_byte_count"]
    token_stat.current_prompt_tokens = state["prompt_tokens"]
    request_stat = Mock()
    request_stat._response_content_errors = state["content_errors"]
    request_stat._requests_per_minute_max = state["rpm_max"]
    runtime = Mock()
    runtime.token_stat = token_stat
    runtime.llm_model.model_name = state["model_name"]
    agent = Mock()
    agent.runtime = runtime
    agent.llm_request_stat = request_stat
    return agent


def _settle_call(monkeypatch, state, outcome, session_id="s1", authorized=True):
    """Run the settle module once and return the recorded manager call."""
    module = importlib.import_module(SETTLE_MODULE)
    agent_chat = Mock()
    agent_chat.ai_agent = _fake_agent(state)
    agent_chat.ctx_runtime_data.session_id = session_id
    manager = Mock()
    manager.accumulate_session_metrics.return_value = True
    monkeypatch.setattr(
        "topsailai.context.ctx_manager.get_session_manager", lambda: manager,
    )
    attempt = _Attempt(authorized)
    result = module.main(agent_chat=agent_chat, outcome=outcome, attempt=attempt)
    return result, manager, attempt


BASE_STATE = {
    "first_byte_sum_ms": 120.0, "first_byte_count": 2, "prompt_tokens": 500,
    "content_errors": 1, "rpm_max": 4, "model_name": "m",
}


@pytest.mark.parametrize(
    "outcome,column",
    [("failure", "turn_failure_count"), ("back", "turn_back_count"),
     ("interrupt", "turn_interrupt_count")],
)
def test_settle_module_maps_outcome_to_its_column(monkeypatch, outcome, column):
    """Each non-success outcome increments only its own counter."""
    result, manager, _attempt = _settle_call(monkeypatch, BASE_STATE, outcome)
    assert result is True
    kwargs = manager.accumulate_session_metrics.call_args.kwargs
    assert kwargs[column] == 1
    assert kwargs["response_content_errors"] == 1
    assert kwargs["first_byte_count"] == 2
    assert kwargs["first_byte_sum_ms"] == 120
    assert kwargs["requests_per_minute_max"] == 4
    assert kwargs["max_prompt_tokens"] == 500
    assert kwargs["model_name"] == "m"


def test_settle_module_success_adds_no_outcome_column(monkeypatch):
    """Success is already counted by turn_count, so it adds no outcome column."""
    _result, manager, _attempt = _settle_call(monkeypatch, BASE_STATE, "success")
    kwargs = manager.accumulate_session_metrics.call_args.kwargs
    assert "turn_failure_count" not in kwargs
    assert "turn_back_count" not in kwargs
    assert "turn_interrupt_count" not in kwargs


def test_settle_module_is_idempotent_per_attempt(monkeypatch):
    """A repeated invocation on the same attempt must not double count."""
    module = importlib.import_module(SETTLE_MODULE)
    agent_chat = Mock()
    agent_chat.ai_agent = _fake_agent(BASE_STATE)
    agent_chat.ctx_runtime_data.session_id = "s1"
    manager = Mock()
    manager.accumulate_session_metrics.return_value = True
    monkeypatch.setattr(
        "topsailai.context.ctx_manager.get_session_manager", lambda: manager,
    )
    attempt = _Attempt()
    module.main(agent_chat=agent_chat, outcome="failure", attempt=attempt)
    module.main(agent_chat=agent_chat, outcome="failure", attempt=attempt)
    assert manager.accumulate_session_metrics.call_count == 1


def test_settle_module_skips_runs_without_session(monkeypatch):
    """A run without a session must not write metrics."""
    result, manager, _attempt = _settle_call(monkeypatch, BASE_STATE, "success", session_id="")
    assert result is False
    manager.accumulate_session_metrics.assert_not_called()


def test_settle_module_skips_unauthorized_settlement(monkeypatch):
    """An unauthorized settlement must not write metrics."""
    result, manager, _attempt = _settle_call(
        monkeypatch, BASE_STATE, "success", authorized=False,
    )
    assert result is False
    manager.accumulate_session_metrics.assert_not_called()


@pytest.mark.parametrize(
    "module_path,column",
    [(WARNING_MODULE, "heavy_task_warning_count"),
     (BLOCK_MODULE, "heavy_task_block_count")],
)
def test_heavy_task_modules_increment_their_own_counter(monkeypatch, module_path, column):
    """Each heavy-task stage increments only its own session counter."""
    module = importlib.import_module(module_path)
    monkeypatch.setenv("TOPSAILAI_SESSION_ID", "s1")
    manager = Mock()
    manager.accumulate_session_metrics.return_value = True
    monkeypatch.setattr(
        "topsailai.context.ctx_manager.get_session_manager", lambda: manager,
    )
    assert module.main(schema_version=1) == {"recorded": True}
    manager.accumulate_session_metrics.assert_called_once_with(
        session_id="s1", **{column: 1},
    )


@pytest.mark.parametrize("module_path", [WARNING_MODULE, BLOCK_MODULE])
def test_heavy_task_modules_never_raise_on_write_failure(monkeypatch, module_path):
    """A failed statistics write must not interrupt the turn."""
    module = importlib.import_module(module_path)
    monkeypatch.setenv("TOPSAILAI_SESSION_ID", "s1")
    manager = Mock()
    manager.accumulate_session_metrics.side_effect = RuntimeError("boom")
    monkeypatch.setattr(
        "topsailai.context.ctx_manager.get_session_manager", lambda: manager,
    )
    assert module.main(schema_version=1) == {"recorded": False}


@pytest.mark.parametrize("module_path", [WARNING_MODULE, BLOCK_MODULE])
def test_heavy_task_modules_skip_without_session(monkeypatch, module_path):
    """Without a session there is nothing to update."""
    module = importlib.import_module(module_path)
    monkeypatch.delenv("TOPSAILAI_SESSION_ID", raising=False)
    monkeypatch.delenv("SESSION_ID", raising=False)
    manager = Mock()
    monkeypatch.setattr(
        "topsailai.context.ctx_manager.get_session_manager", lambda: manager,
    )
    assert module.main(schema_version=1) == {"recorded": False}
    manager.accumulate_session_metrics.assert_not_called()
