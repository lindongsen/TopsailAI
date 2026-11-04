"""Real HTTP acceptance of conditional startup recovery. Author: DawsonLin."""

import json
import threading
import urllib.request

import pytest
from pytest_bdd import given, when, then, parsers, scenarios

from tests.mock.llm_mock_server import MockServerConfig, create_server
from topsailai.ai_base.agent_base import AgentRun
from topsailai.ai_base.llm_pool.openai_client_pool import default_openai_client_pool
from topsailai.workspace.context.ctx_runtime import ContextRuntimeData
from topsailai.workspace.context.summary_recovery import RecoveryConfig

scenarios("features/summary_observation_recovery.feature")


@pytest.fixture
def recovery_resources(monkeypatch):
    """Own one mock server and production agent, including failure teardown."""
    default_openai_client_pool.close_all()
    reply = json.dumps([{"step_name": "final_answer", "raw_text": "Keep project constraints and continue the pending task using source references."}])
    server = create_server(MockServerConfig(port=0, reply=reply, stream_chunks=(reply,)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}/v1"
    values = {
        "OPENAI_API_BASE": base, "OPENAI_BASE_URL": base, "OPENAI_API_KEY": "mock",
        "OPENAI_MODEL": "recovery-mock", "LLM_RESPONSE_STREAM": "0",
        "TOPSAILAI_CONTEXT_SUMMARY_MODE": "runtime",
        "TOPSAILAI_CONTEXT_SUMMARY_PROCESSOR": "agent_llm_model",
        "TOPSAILAI_INTERACTIVE_MODE": "0", "TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT": "0",
        "TOPSAILAI_LLM_RESPONSE_EVENTS_ENABLED": "0", "TOPSAILAI_MODEL_SETTINGS": "",
        "TOPSAILAI_USE_TOOL_CALLS": "0", "TOPSAILAI_USE_TOOL_CALLS_MODEL_PREFIXES": "",
        "TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD": "64000",
        "TOPSAILAI_AGENT2LLM_TOKEN_SUMMARIZE_THRESHOLD": "128000",
        "TOPSAILAI_USER2AGENT_MESSAGES_QUANTITY_THRESHOLD": "17",
        "TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD": "97",
        "TOPSAILAI_CONTEXT_MESSAGES_HEAD_OFFSET_TO_KEEP": "0",
        "TOPSAILAI_CONTEXT_MESSAGES_TAIL_OFFSET_TO_KEEP": "0",
        "TOPSAILAI_MODEL_MAX_CONTEXT_DEFAULT": "256000",
        "TOPSAILAI_CONTEXT_LOAD_USER_MD_ENABLED": "0",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr("topsailai.workspace.llm_shell.record_project_history", lambda _sid: None)
    agent = None
    try:
        agent = AgentRun(system_prompt="Keep the user task and safety constraints.", tools={}, agent_name="RecoveryBDD")
        owner = ContextRuntimeData(RecoveryConfig(True))
        owner.ai_agent = agent
        yield owner, server
    finally:
        if agent is not None:
            agent.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()
        default_openai_client_pool.close_all()


@given(parsers.parse("a recovery runtime using a private HTTP provider for {layer} in {mode} mode with stream {stream}"), target_fixture="recovery_case")
def arrange(recovery_resources, monkeypatch, layer, mode, stream):
    """Build a representative large observation with genuine task provenance."""
    owner, server = recovery_resources
    monkeypatch.setenv("TOPSAILAI_CONTEXT_SUMMARY_MODE", mode)
    monkeypatch.setenv("LLM_RESPONSE_STREAM", stream)
    observation = {"role": "user", "content": {"step_name": "observation", "raw_text": "source reference constraints " * 35000}}
    task = {"role": "user", "content": {"step_name": "task", "raw_text": "Implement the pending task and preserve safety constraints"}}
    owner.messages = [observation, task]
    owner.ai_agent.messages = [{"role": "system", "content": "Keep project rules"}, observation, task]
    return owner, server, layer, observation, task


@when("the oversized startup context is summarized once")
def summarize(recovery_case):
    """Use the real production summary owner and provider client."""
    owner, _, layer, _, _ = recovery_case
    method = owner.summarize_messages_for_processed if layer == "user2agent" else owner.summarize_messages_for_processing
    assert method(messages=owner.messages, force=True)


def provider_state(server):
    """Read wire-level evidence from the private provider."""
    with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/debug/state", timeout=3) as response:
        return json.load(response)


@then("the provider received the original material in exactly one request")
def check_wire(recovery_case):
    """Ensure compression never omits its source from the summary input."""
    _, server, _, observation, _ = recovery_case
    state = provider_state(server)
    assert state["total_requests"] == 1
    messages = state["request_bodies"][0]["body"]["messages"]
    assert observation["content"]["raw_text"] in str(messages)


@then("both context layers retain the task without the oversized observation")
def check_layers(recovery_case):
    """Both copies leave active context only after successful generation."""
    owner, _, _, observation, task = recovery_case
    assert observation not in owner.messages and observation not in owner.ai_agent.messages
    assert task in owner.messages and task in owner.ai_agent.messages


@then("subsequent file reading does not immediately trigger another summary")
def continue_work(recovery_case):
    """Real token admission permits useful new work rather than a second summary."""
    owner, server, _, _, _ = recovery_case
    for index in range(5):
        owner.ai_agent.messages.append({"role": "assistant", "content": f"Read source {index}: " + "file detail " * 300})
        assert not owner.is_need_summarize_for_processed()
        assert not owner.is_need_summarize_for_processing()
    assert provider_state(server)["total_requests"] == 1
