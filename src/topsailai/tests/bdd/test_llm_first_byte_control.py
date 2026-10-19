"""Real socket plus production HTTP/SSE control acceptance. Author: DawsonLin."""
import json
import os
import socket
import threading
import time
from uuid import uuid4
from types import SimpleNamespace

import pytest
from pytest_bdd import given, when, then, parsers, scenarios

from tests.mock.llm_mock_server import MockServerConfig, create_server
from topsailai.ai_base.llm_base import LLMModel
from topsailai.ai_base.agent_base import AgentRun
from topsailai.ai_base.exception import HardInterruptError
from topsailai.utils.thread_local_tool import ctxm_set_agent
from topsailai.workspace.control_handlers.interrupt import HardInterruptHandler
from topsailai.workspace.control_channel.handler import ControlHandlerRegistry
from topsailai.workspace.control_channel.protocol import ControlContext
from topsailai.workspace.control_channel.server import ControlServer
from topsailai.workspace.control_handlers.llm_control import LLMControlHandler

scenarios("features/llm_first_byte_control.feature")


def send(path, payload, action="llm_control"):
    """Use the real JSONL Unix socket boundary with bounded receive time."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(5)
        client.connect(path)
        client.sendall(json.dumps({"request_id": uuid4().hex, "action": action, "payload": payload}).encode() + b"\n")
        with client.makefile("rb") as reader:
            return json.loads(reader.readline())


@given(parsers.parse('a controlled mock LLM request waiting in "{phase}" with timeout "{timeout}"'), target_fixture="control_case")
def controlled_case(monkeypatch, tmp_path, request, phase, timeout):
    """Start actual OpenAI client, mock HTTP server, and authenticated control bus."""
    config = MockServerConfig(
        response_header_delays=(60, 60) if phase == "headers" else None,
        first_chunk_delays=(60, 60) if phase == "first_item" else None,
        stream_response_chunks=(("STALE",), ("FRESH",)),
    )
    resources = {}

    def cleanup():
        """Release exact resources even when fixture setup fails partway."""
        server = resources.get("server")
        if server is not None:
            for number in (1, 2):
                try:
                    server.lifecycle_capture.request_handle(number).release_delay()
                except KeyError:
                    pass
        worker = resources.get("worker")
        if worker is not None:
            worker.join(10)
        channel = resources.get("channel")
        if channel is not None:
            channel.stop()
        thread = resources.get("thread")
        if server is not None:
            if thread is not None and thread.is_alive():
                server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(5)
        model = resources.get("model")
        if model is not None:
            model.release_all_llm_models()
        assert worker is None or not worker.is_alive()
        assert thread is None or not thread.is_alive()

    request.addfinalizer(cleanup)
    server = create_server(config)
    resources["server"] = server
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    resources["thread"] = thread
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}/v1"
    for key, value in {
        "OPENAI_API_BASE": base, "OPENAI_BASE_URL": base,
        "OPENAI_API_KEY": "mock-only", "OPENAI_MODEL": "control-mock",
        "TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT": timeout,
        "TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT_RAISE": "0",
        "TOPSAILAI_EVENTS_ENABLED": "0", "TOPSAILAI_INTERACTIVE_MODE": "0",
        "TOPSAILAI_LLM_RESPONSE_EVENTS_ENABLED": "0",
    }.items():
        monkeypatch.setenv(key, value)
    model = LLMModel()
    resources["model"] = model
    from topsailai.workspace.folder_utils import get_interrupt_flag_path
    from topsailai.workspace import folder_constants
    monkeypatch.setattr(folder_constants, "FOLDER_WORKSPACE_TASK", str(tmp_path))
    monkeypatch.setenv("SESSION_ID", "wire")
    agent = SimpleNamespace(runtime=SimpleNamespace(llm_model=model))
    agent._get_interrupt_flag_path = lambda: get_interrupt_flag_path(str(tmp_path), "wire", os.getpid())
    agent._check_hard_interrupt = lambda: AgentRun._check_hard_interrupt(agent)
    agent_chat = SimpleNamespace(ai_agent=agent)
    registry = ControlHandlerRegistry()
    registry.register(LLMControlHandler())
    registry.register(HardInterruptHandler())
    temporary_root = next(parent for parent in tmp_path.parents if parent.name == ".tmp")
    path = str(temporary_root / (uuid4().hex[:12] + ".sock"))
    channel = ControlServer(path, registry, ControlContext(session_id="wire", pid=os.getpid(), agent_chat=agent_chat, task_folder=str(tmp_path)), timeout=0.1)
    resources["channel"] = channel
    channel.start()
    state = {"server": server, "model": model, "path": path, "phase": phase, "outputs": []}
    model.send_content = state["outputs"].append

    def run():
        """Run the unmodified production retry loop under explicit app routing."""
        try:
            with ctxm_set_agent(agent):
                state["result"] = model.chat([{"role": "user", "content": "same request"}], for_stream=True, for_raw=True)
        except BaseException as error:
            state["error"] = error
        finally:
            state["done"].set()

    state["done"] = threading.Event()
    worker = threading.Thread(target=run, daemon=True)
    resources["worker"] = worker
    worker.start()
    assert server.lifecycle_capture.wait_for_request(1)
    assert server.lifecycle_capture.wait_for_phase(1, phase)
    yield state


@when(parsers.parse('the operator stages "{operation}" through the control socket'))
def command(control_case, operation):
    """Send the retained command directly, without discovery or proposals."""
    state = control_case
    state["operation"] = operation
    if operation == "force_retry":
        from topsailai.ai_base.llm_control.control_runtime import _paths
        waiting, _ = _paths("wire", os.getpid())
        deadline = time.monotonic() + 3
        while not waiting.exists() and time.monotonic() < deadline:
            threading.Event().wait(0.01)
        assert waiting.exists()
    state["receipt"] = send(state["path"], {} if operation == "hard_interrupt" else
                            {"operation": "force_retry"},
                            action="hard_interrupt" if operation == "hard_interrupt" else "llm_control")
    assert state["receipt"]["status"] == "ok", state["receipt"]
    if operation == "force_retry":
        assert state["receipt"]["result"] == {"state": "flag_written"}


@then("the wait executes the command without stale output")
def outcome(control_case):
    """Assert generic interruption or same-request retry over real HTTP/SSE."""
    state = control_case
    retry = state["operation"] == "force_retry"
    if retry:
        assert state["server"].lifecycle_capture.wait_for_request(2, timeout=10)
        assert state["server"].lifecycle_capture.wait_for_phase(2, state["phase"])
        state["server"].lifecycle_capture.request_handle(2).release_delay()
    assert state["done"].wait(10)
    if retry:
        assert "error" not in state, repr(state.get("error"))
        assert state["result"] == "FRESH"
    else:
        assert isinstance(state.get("error"), HardInterruptError), repr(state.get("error"))
    records = state["server"].request_body_capture.state()["request_bodies"]
    assert len(records) == (2 if retry else 1)
    if retry:
        assert records[0]["body"] == records[1]["body"]
    assert not any("STALE" in item for item in state["outputs"])
