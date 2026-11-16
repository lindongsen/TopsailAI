"""Shared private-provider fixtures for summary acceptance tests. Author: DawsonLin."""

import json
import threading
import urllib.request

import pytest

from tests.mock.llm_mock_server import MockServerConfig, create_server
from topsailai.ai_base.agent_base import AgentRun
from topsailai.ai_base.llm_pool.openai_client_pool import default_openai_client_pool
from topsailai.workspace.context.ctx_runtime import ContextRuntimeData


@pytest.fixture
def summary_provider_resources(monkeypatch):
    """Own one mock server and production agent, including failure teardown."""
    default_openai_client_pool.close_all()
    reply = json.dumps([{"step_name": "final_answer", "raw_text": "Keep project constraints and continue the pending task using source references."}])
    server = create_server(MockServerConfig(port=0, reply=reply, stream_chunks=(reply,)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}/v1"
    values = {
        "OPENAI_API_BASE": base, "OPENAI_BASE_URL": base, "OPENAI_API_KEY": "mock",
        "OPENAI_MODEL": "summary-mock", "LLM_RESPONSE_STREAM": "0",
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
        agent = AgentRun(system_prompt="Keep the user task and safety constraints.", tools={}, agent_name="SummaryBDD")
        owner = ContextRuntimeData()
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


def provider_state(server):
    """Read wire-level evidence from the private provider."""
    with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/debug/state", timeout=3) as response:
        return json.load(response)
