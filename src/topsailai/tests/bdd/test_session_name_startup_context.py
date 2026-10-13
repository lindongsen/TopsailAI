"""Bindings for the production plan-Agent startup-context regression."""

from pathlib import Path
import socket
import threading

import pytest
from pytest_bdd import given, scenarios, then, when

from tests.bdd.session_name_startup_context_harness import (
    EXPLICIT_MARKER,
    USER_MARKER,
    SessionNameStartupScenario,
)


scenarios("features/session_name_startup_context.feature")


def test_scenario_constructor_closes_unstarted_server_on_thread_start_failure(
    monkeypatch, tmp_path
):
    """Preserve the original start error while closing a real loopback socket."""
    harness = __import__(
        "tests.bdd.session_name_startup_context_harness", fromlist=["unused"]
    )
    captured = {}
    original_error = RuntimeError("thread start failed")
    real_thread = threading.Thread

    def capture_server(config):
        from tests.mock.llm_mock_server import create_server as real_create_server

        server = real_create_server(config)
        captured["server"] = server
        server.shutdown_called = False

        def forbidden_shutdown():
            server.shutdown_called = True
            raise AssertionError("shutdown called before serve_forever started")

        server.shutdown = forbidden_shutdown
        return server

    class FailingThread:
        def __init__(self, target=None, daemon=False):
            self.target = target
            self.daemon = daemon

        def start(self):
            raise original_error

        def is_alive(self):
            return False

        def join(self, timeout=None):
            return None

    monkeypatch.setattr(harness, "create_server", capture_server)
    monkeypatch.setattr(harness.threading, "Thread", FailingThread)
    outcome = {}

    def construct():
        try:
            harness.SessionNameStartupScenario(monkeypatch, tmp_path)
        except BaseException as error:
            outcome["error"] = error

    thread = real_thread(target=construct)
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert outcome["error"] is original_error

    server = captured["server"]
    assert server.socket.fileno() == -1
    assert not server.shutdown_called
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", server.server_port))




def test_scenario_constructor_closes_started_server_when_entry_is_delayed(
    monkeypatch, tmp_path
):
    """Stop a started server whose serving entry is delayed by a barrier."""
    harness = __import__(
        "tests.bdd.session_name_startup_context_harness", fromlist=["unused"]
    )
    captured = {}
    original_error = RuntimeError("startup initialization failed")
    real_thread = threading.Thread
    entry_gate = threading.Event()
    init_failed = threading.Event()
    close_entered = threading.Event()

    def capture_server(config):
        from tests.mock.llm_mock_server import create_server as real_create_server

        server = real_create_server(config)
        captured["server"] = server
        server.shutdown_called = False
        server.serve_forever_called = False
        original_shutdown = server.shutdown
        original_serve_forever = server.serve_forever

        def record_shutdown():
            server.shutdown_called = True
            return original_shutdown()

        def record_serve_forever():
            server.serve_forever_called = True
            return original_serve_forever()

        server.shutdown = record_shutdown
        server.serve_forever = record_serve_forever
        return server

    class DelayedThread:
        def __init__(self, target=None, daemon=False):
            self._target = target
            self._thread = real_thread(target=self._run, daemon=daemon)

        def _run(self):
            entry_gate.wait(timeout=5)
            self._target()

        def start(self):
            self._thread.start()

        def is_alive(self):
            return self._thread.is_alive()

        def join(self, timeout=None):
            return self._thread.join(timeout=timeout)

    class FailingEnvironment:
        def __init__(self, delegate):
            self._delegate = delegate

        def setenv(self, key, value):
            init_failed.set()
            raise original_error

    original_close = harness.SessionNameStartupScenario.close

    def observe_close(scenario):
        captured["scenario"] = scenario
        captured["serving_thread"] = scenario.server_thread._thread
        close_entered.set()
        return original_close(scenario)

    def construct():
        try:
            harness.SessionNameStartupScenario(
                FailingEnvironment(monkeypatch), tmp_path
            )
        except BaseException as error:
            captured["error"] = error

    monkeypatch.setattr(harness, "create_server", capture_server)
    monkeypatch.setattr(harness.threading, "Thread", DelayedThread)
    monkeypatch.setattr(harness.SessionNameStartupScenario, "close", observe_close)
    construct_thread = real_thread(target=construct)
    construct_thread.start()

    assert init_failed.wait(timeout=5)
    assert close_entered.wait(timeout=5)
    scenario = captured["scenario"]
    assert scenario.server_thread_started
    assert not scenario.server_loop_started.is_set()
    assert scenario.server_stop_requested.wait(timeout=5)
    entry_gate.set()

    construct_thread.join(timeout=5)
    serving_thread = captured["serving_thread"]
    serving_thread.join(timeout=5)
    assert not construct_thread.is_alive()
    assert not serving_thread.is_alive()
    assert captured["error"] is original_error

    server = captured["server"]
    assert not server.shutdown_called
    assert not server.serve_forever_called
    assert server.socket.fileno() == -1
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", server.server_port))
@pytest.fixture
def session_name_startup_ctx(bdd_tmp_path: Path, monkeypatch):
    """Provide and close one isolated real AgentChat scenario."""
    scenario = None
    try:
        scenario = SessionNameStartupScenario(monkeypatch, bdd_tmp_path)
        yield scenario
    finally:
        if scenario is not None:
            scenario.close()


@given("a fresh plan Agent startup scenario with automatic naming enabled")
def given_fresh_plan_agent(session_name_startup_ctx):
    """Keep the fresh-process-equivalent isolated production configuration."""
    return session_name_startup_ctx


@when("the plan Agent runs its first real turn")
def when_plan_agent_runs(session_name_startup_ctx):
    """Drive the real factory and AgentChat loop over loopback SSE."""
    session_name_startup_ctx.run()


@then("the Manager request contains the USER.md marker")
def then_manager_contains_user(session_name_startup_ctx):
    """Assert startup context reached the first Manager request."""
    texts = session_name_startup_ctx.request_texts()
    assert any(USER_MARKER in text for text in texts), (texts, session_name_startup_ctx.process.stdout, session_name_startup_ctx.process.stderr)


@then("the naming request omits the USER.md and explicit startup markers")
def then_naming_omits_startup(session_name_startup_ctx):
    """Assert the naming prompt is isolated from both startup sources."""
    texts = session_name_startup_ctx.request_texts()
    naming = [text for text in texts if "naming assistant" in text.lower()]
    assert len(naming) == 1
    assert USER_MARKER not in naming[0]
    assert EXPLICIT_MARKER not in naming[0]


@then("the naming request is made only after Agent startup is published")
def then_order_is_published(session_name_startup_ctx):
    """Assert the readiness barrier was entered before startup publication."""
    assert session_name_startup_ctx.wait_entered.exists()
    assert session_name_startup_ctx.started.exists()
    assert session_name_startup_ctx.wait_released.exists()


@then("the session name update completes")
def then_name_update_completes(session_name_startup_ctx):
    """Assert the created session has a generated name in storage."""
    from topsailai.context.ctx_manager import get_session_manager

    manager = get_session_manager()
    data = manager.get_session(session_name_startup_ctx.session_id)
    assert data is not None
    assert data.session_name


@then("the later plan Agent turn completes without reloading USER.md")
def then_later_turn_does_not_reload(session_name_startup_ctx):
    """Assert the child completed its second turn without rereading USER.md."""
    texts = session_name_startup_ctx.request_texts()
    assert len(texts) >= 3
    assert int(session_name_startup_ctx.user_open_count.read_text(encoding="utf-8")) == 1


@pytest.fixture
def chat_session_name_startup_ctx(bdd_tmp_path: Path, monkeypatch):
    """Provide an isolated real chat Agent startup scenario."""
    scenario = None
    try:
        scenario = SessionNameStartupScenario(monkeypatch, bdd_tmp_path, agent_type="react")
        yield scenario
    finally:
        if scenario is not None:
            scenario.close()


@given("a fresh chat Agent startup scenario with automatic naming enabled")
def given_fresh_chat_agent(chat_session_name_startup_ctx):
    """Use the real chat Agent factory path in a fresh subprocess."""
    return chat_session_name_startup_ctx


@when("the chat Agent runs its first real turn")
def when_chat_agent_runs(chat_session_name_startup_ctx):
    """Drive the real chat Agent through two turns."""
    chat_session_name_startup_ctx.run()


@then("the later chat Agent turn completes without reloading USER.md")
def then_later_chat_turn_does_not_reload(chat_session_name_startup_ctx):
    """Assert the chat Agent later turn does not reread startup context."""
    texts = chat_session_name_startup_ctx.request_texts()
    assert len(texts) >= 3
    assert int(chat_session_name_startup_ctx.user_open_count.read_text(encoding="utf-8")) == 1


@then("the chat Manager request contains the USER.md marker")
def then_chat_manager_contains_user(chat_session_name_startup_ctx):
    """Assert startup context reached the chat Agent request."""
    assert any(USER_MARKER in text for text in chat_session_name_startup_ctx.request_texts())


@then("the chat naming request omits the USER.md and explicit startup markers")
def then_chat_naming_omits_startup(chat_session_name_startup_ctx):
    """Assert chat naming omits startup context."""
    naming = [text for text in chat_session_name_startup_ctx.request_texts() if "naming assistant" in text.lower()]
    assert len(naming) == 1
    assert USER_MARKER not in naming[0]
    assert EXPLICIT_MARKER not in naming[0]


@then("the chat naming request is made only after Agent startup is published")
def then_chat_order_is_published(chat_session_name_startup_ctx):
    """Assert chat readiness ordering."""
    assert chat_session_name_startup_ctx.wait_entered.exists()
    assert chat_session_name_startup_ctx.started.exists()
    assert chat_session_name_startup_ctx.wait_released.exists()


@then("the chat session name update completes")
def then_chat_name_update_completes(chat_session_name_startup_ctx):
    """Assert chat session naming completed in storage."""
    from topsailai.context.ctx_manager import get_session_manager
    data = get_session_manager().get_session(chat_session_name_startup_ctx.session_id)
    assert data is not None
    assert data.session_name
