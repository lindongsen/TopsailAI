"""Real control-channel pause steps. Author: DawsonLin.

Every scenario drives production boundaries: a real ``ControlServer`` over a
Unix domain socket, the real ``AgentRun`` ReAct loop against a real HTTP mock
provider, and the real session FIFO for the continue answer. No step replaces
the pause checkpoint, the marker file, or the input helper.
"""

import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from pytest_bdd import given, parsers, then, when

from cli_topsailai.runtime_control import send_control_request
from topsailai.ai_base.agent_base import AgentRun
from topsailai.ai_base.agent_types.react import Step4ReAct
from topsailai.ai_base.exception import HardInterruptError
from topsailai.utils.thread_local_tool import (
    ctxm_set_agent,
    set_agent_runtime_input_with_timeout,
)
from topsailai.workspace.control_channel.handler import ControlHandlerRegistry
from topsailai.workspace.control_channel.protocol import ControlContext
from topsailai.workspace.control_handlers import register_control_handlers
from topsailai.workspace.folder_utils import get_pause_flag_path
from topsailai.workspace.input_tool import input_from_pipe_session
from tests.bdd.steps.heartbeat_control_steps import ObservedControlServer, exchange
from tests.bdd.tool_calls_mock_harness import ServerOwner

FINAL_ANSWER_TEXT = "done"


def _noop() -> str:
    """Provide one trivial tool so the agent does not load every internal kit."""
    return "ok"


def _wait_until(predicate, timeout: float = 10.0, interval: float = 0.02) -> None:
    """Block until *predicate* is true, failing with a bounded budget."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError("condition was not reached within the scenario budget")


def _start_writer(pipe_path: Path, text: str) -> threading.Thread:
    """Write one answer into the real session FIFO from a separate thread."""

    def _write() -> None:
        """Open the FIFO for writing and publish exactly one answer line."""
        with open(pipe_path, "w", encoding="utf-8") as writer:
            writer.write(text)
            writer.flush()

    thread = threading.Thread(target=_write, daemon=True)
    thread.start()
    return thread


def _build_reader(state):
    """Build the production session-pipe reader while counting prompts."""

    def reader(tips: str = "", timeout: float | None = None):
        """Read one answer slice from the real session FIFO."""
        state.prompt_count += 1
        return input_from_pipe_session(
            session_id=state.session_id,
            single_line=True,
            timeout=timeout,
            prompt=tips,
            raise_eof_error=False,
        )

    return reader


def _run_agent(state, *, nested: bool = False, register_input: bool = True) -> None:
    """Drive the real AgentRun loop against the scenario provider."""
    if register_input:
        set_agent_runtime_input_with_timeout(_build_reader(state))
    else:
        set_agent_runtime_input_with_timeout(None)

    agent = AgentRun(
        system_prompt="You are a BDD pause agent.",
        tools={"bdd_noop": _noop},
        agent_name="BDDPause",
    )
    state.agent = agent
    try:
        if nested:
            with ctxm_set_agent(object()):
                state.result = agent.run(Step4ReAct(), "start the task")
        else:
            state.result = agent.run(Step4ReAct(), "start the task")
    except Exception as error:  # noqa: BLE001 - the scenario asserts the outcome
        state.error = error


def _run_agent_in_thread(state) -> None:
    """Run the real loop in its own thread so the scenario can signal it."""
    _run_agent(state)


@pytest.fixture
def pause_state(bdd_tmp_path, monkeypatch):
    """Own scenario resources and preserve unrelated scenario data."""
    sentinel = bdd_tmp_path / "unrelated.txt"
    sentinel.write_text("keep", encoding="utf-8")
    state = SimpleNamespace(
        tmp_path=bdd_tmp_path,
        monkeypatch=monkeypatch,
        session_id="bdd-pause",
        socket_path=bdd_tmp_path / "pause.sock",
        path=bdd_tmp_path / "pause.sock",
        server=None,
        server_owner=None,
        agent=None,
        thread=None,
        writer=None,
        prompt_count=0,
        result=None,
        error=None,
        caplog_text="",
    )
    try:
        yield state
    finally:
        set_agent_runtime_input_with_timeout(None)
        if state.writer is not None:
            state.writer.join(timeout=5)
        if state.thread is not None:
            state.thread.join(timeout=15)
        if state.agent is not None:
            state.agent.llm_model.tokenStat.flag_running = False
            state.agent.close()
        if state.server is not None:
            state.server.stop()
            assert not state.server.is_running()
            for thread in state.server.connections:
                thread.join(timeout=2)
                assert not thread.is_alive()
            assert not state.socket_path.exists()
        if state.server_owner is not None:
            state.server_owner.close()
        assert sentinel.read_text(encoding="utf-8") == "keep"


@given(parsers.parse('a pause control server with session "{session}"'))
def pause_server(pause_state, session):
    """Start the real service, provider, and session-scoped file identity."""
    state = pause_state
    state.session_id = session
    state.monkeypatch.setenv("TOPSAILAI_SESSION_ID", session)
    state.monkeypatch.setenv("SESSION_ID", session)
    state.monkeypatch.setattr(
        "topsailai.workspace.folder_constants.FOLDER_WORKSPACE_TASK",
        str(state.tmp_path),
    )
    state.monkeypatch.setattr(
        "topsailai.workspace.input_tool.FOLDER_WORKSPACE_TASK",
        str(state.tmp_path),
    )
    state.marker_path = Path(
        get_pause_flag_path(str(state.tmp_path), session, os.getpid())
    )
    state.pipe_path = state.tmp_path / f"{session}.{os.getpid()}.session.pipe"
    if not state.pipe_path.exists():
        os.mkfifo(state.pipe_path)
    state.interrupt_path = (
        state.tmp_path / f"{session}.{os.getpid()}.session.agent2llm_interrupt.flag"
    )

    state.server_owner = ServerOwner.start()
    values = {
        "OPENAI_API_KEY": "test-key",
        "OPENAI_MODEL": "mock-model",
        "OPENAI_API_BASE": state.server_owner.base_url,
        "OPENAI_BASE_URL": state.server_owner.base_url,
        "LLM_RESPONSE_STREAM": "0",
        "TOPSAILAI_USE_TOOL_CALLS": "0",
        "TOPSAILAI_LLM_RESPONSE_EVENTS_ENABLED": "0",
        "TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT": "0",
        "TOPSAILAI_AUTO_SESSION_NAME_ENABLED": "0",
        "TOPSAILAI_PRINT_TOOL_STAT": "0",
        "TOPSAILAI_ENABLE_TOOL_STAT": "0",
        "TOPSAILAI_ENABLE_PARALLEL_TOOL_CALLS": "0",
        "TOPSAILAI_EVENTS_ENABLED": "0",
        "TOPSAILAI_ENABLE_SESSION_TEE_OUT": "0",
        "TOPSAILAI_CONTEXT_LOAD_USER_MD_ENABLED": "0",
        "TOPSAILAI_INTERACTIVE_MODE": "0",
        "TOPSAILAI_PRINT_ENABLED": "0",
        "DEBUG": "0",
        "CONTEXT_HISTORY_MANAGERS": "",
    }
    for key, value in values.items():
        state.monkeypatch.setenv(key, value)

    registry = ControlHandlerRegistry()
    register_control_handlers(registry)
    assert registry.is_registered("pause")
    assert registry.is_registered("clear_pause")
    context = ControlContext(
        session_id=session,
        pid=os.getpid(),
        task_folder=str(state.tmp_path),
    )
    state.server = ObservedControlServer(
        str(state.socket_path), registry, context, timeout=0.1
    )
    state.server.start()
    assert state.server.is_running()


@when("the operator requests pause twice and answers yes")
def pause_twice_and_answer_yes(pause_state):
    """Accept two pause requests through both transports, then answer yes."""
    state = pause_state
    first = exchange(state, action="pause", payload={"reason": "bdd"}, request_id="pause-1")
    assert first["status"] == "ok"
    assert first["result"]["state"] == "pause_requested"
    assert state.marker_path.exists()
    marker_payload = json.loads(state.marker_path.read_text(encoding="utf-8"))
    assert marker_payload["prompt"]
    assert marker_payload["default"] == "continue"

    success, second = send_control_request(
        str(state.socket_path), "pause", {"reason": "again"}, 2
    )
    assert success is True
    assert second["status"] == "ok"
    assert second["result"]["state"] == "pause_requested"

    state.writer = _start_writer(state.pipe_path, "yes\n")
    _run_agent(state)


@then("the loop resumes after exactly one consumed marker")
def loop_resumes_once(pause_state):
    """Require one prompt, one provider request, and a consumed marker."""
    state = pause_state
    assert state.error is None, repr(state.error)
    assert state.result == FINAL_ANSWER_TEXT
    assert state.prompt_count == 1
    assert not state.marker_path.exists()
    assert len(state.server_owner.state()["request_bodies"]) == 1


@when("the operator requests pause and answers no")
def pause_and_answer_no(pause_state):
    """Accept one pause request and answer no through the session FIFO."""
    state = pause_state
    response = exchange(state, action="pause", payload={}, request_id="pause-no")
    assert response["status"] == "ok"
    assert response["result"]["state"] == "pause_requested"
    assert state.marker_path.exists()

    state.writer = _start_writer(state.pipe_path, "no\n")
    _run_agent(state)


@then("the loop is interrupted before any provider request")
def interrupted_before_provider(pause_state):
    """Require the hard-interrupt contract and no saved assistant answer."""
    state = pause_state
    assert isinstance(state.error, HardInterruptError), repr(state.error)
    assert state.result is None
    assert state.prompt_count == 1
    assert not state.marker_path.exists()
    assert state.server_owner.state()["request_bodies"] == []
    assert not any(
        message.get("role") == "assistant" for message in state.agent.messages
    )


@when("a hard interrupt arrives while the loop waits for an answer")
def interrupt_while_waiting(pause_state):
    """Signal the waiting loop with a fresh pause request and an interrupt."""
    state = pause_state
    response = exchange(state, action="pause", payload={}, request_id="pause-int")
    assert response["status"] == "ok"
    assert response["result"]["state"] == "pause_requested"

    state.thread = threading.Thread(
        target=_run_agent_in_thread, args=(state,), daemon=True
    )
    state.thread.start()
    _wait_until(lambda: not state.marker_path.exists())

    pending = exchange(state, action="pause", payload={}, request_id="pause-int-2")
    assert pending["status"] == "ok"
    assert state.marker_path.exists()
    state.interrupt_sent_at = time.monotonic()
    state.interrupt_path.write_text("1", encoding="utf-8")

    state.thread.join(timeout=15)
    assert not state.thread.is_alive()
    state.interrupt_elapsed = time.monotonic() - state.interrupt_sent_at


@then("the pause ends within one poll slice and clears the pending marker")
def pause_ended_by_interrupt(pause_state):
    """Require the interrupt to win and discard the unconsumed marker."""
    state = pause_state
    assert isinstance(state.error, HardInterruptError), repr(state.error)
    assert state.prompt_count == 1
    assert not state.marker_path.exists()
    assert not state.interrupt_path.exists()
    # One slice is the configured poll budget; allow one extra slice of
    # scheduling slack so the assertion measures the slice, not the host.
    assert state.interrupt_elapsed < 2 * AgentRun.PAUSE_POLL_INTERVAL_SECONDS, (
        state.interrupt_elapsed
    )


@when("the operator requests pause with no interactive input channel")
def pause_without_input_channel(pause_state, caplog):
    """Accept a pause request while no TTY and no runtime input exist."""
    state = pause_state
    if sys.stdin.isatty():
        pytest.skip("fail-open needs a non-TTY stdin; a real terminal would block")
    response = exchange(state, action="pause", payload={}, request_id="pause-noc")
    assert response["status"] == "ok"
    assert response["result"]["state"] == "pause_requested"
    assert state.marker_path.exists()

    with caplog.at_level(logging.WARNING):
        _run_agent(state, register_input=False)
    state.caplog_text = caplog.text


@then("the loop continues with the default answer and logs a warning")
def fail_open_without_channel(pause_state):
    """Require the default answer, a consumed marker, and a warning record."""
    state = pause_state
    assert state.error is None, repr(state.error)
    assert state.result == FINAL_ANSWER_TEXT
    assert not state.marker_path.exists()
    assert "no interactive input channel" in state.caplog_text


@when("a nested agent reaches the pause checkpoint")
def nested_agent_reaches_checkpoint(pause_state):
    """Run the real loop one nesting level below the outermost agent."""
    state = pause_state
    response = exchange(state, action="pause", payload={}, request_id="pause-nested")
    assert response["status"] == "ok"
    assert response["result"]["state"] == "pause_requested"
    assert state.marker_path.exists()

    _run_agent(state, nested=True)


@then("the marker survives for the outermost agent")
def marker_survives_nested_agent(pause_state):
    """Require the nested agent to leave the marker untouched."""
    state = pause_state
    assert state.error is None, repr(state.error)
    assert state.result == FINAL_ANSWER_TEXT
    assert state.prompt_count == 0
    assert state.marker_path.exists()
