"""Real-HTTP harness for OpenAI SDK client reuse BDD."""

from __future__ import annotations

import json
import threading
import urllib.request
from typing import Any

from tests.mock.llm_mock_server import MockServerConfig, create_server
from topsailai.ai_base.agent_base import AgentRun
from topsailai.ai_base.llm_pool.openai_client_pool import (
    default_openai_client_pool,
)
from topsailai.workspace.context.base import ContextRuntimeBase


class OpenAIClientReuseScenario:
    """Own Agent2LLM, runtime summarization, and one private provider."""

    def __init__(self, monkeypatch: Any):
        """Configure an isolated process-pool generation and mock provider."""
        self.monkeypatch = monkeypatch
        default_openai_client_pool.close_all()
        self.server = create_server(MockServerConfig(
            port=0,
            reply="Agent2LLM response",
            stream_chunks=("Runtime summary response",),
        ))
        self.server_thread = threading.Thread(
            target=self.server.serve_forever,
            name="bdd-openai-client-reuse-server",
            daemon=True,
        )
        self.server_thread.start()
        base_url = f"http://127.0.0.1:{self.server.server_port}/v1"
        values = {
            "OPENAI_API_BASE": base_url,
            "OPENAI_BASE_URL": base_url,
            "OPENAI_API_KEY": "mock-client-reuse",
            "OPENAI_MODEL": "topsailai-client-reuse",
            "LLM_RESPONSE_STREAM": "0",
            "TOPSAILAI_CONTEXT_SUMMARY_MODE": "runtime",
            "TOPSAILAI_INTERACTIVE_MODE": "0",
            "TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT": "0",
            "TOPSAILAI_LLM_RESPONSE_EVENTS_ENABLED": "0",
            "TOPSAILAI_MODEL_SETTINGS": "",
        }
        for key, value in values.items():
            monkeypatch.setenv(key, value)

        monkeypatch.setattr(
            "topsailai.workspace.llm_shell.record_project_history",
            lambda _session_id: None,
        )
        self.agent = AgentRun(
            system_prompt="You are the Agent2LLM client-reuse test agent.",
            tools={},
            agent_name="BDDOpenAIClientReuse",
        )
        self.runtime = ContextRuntimeBase()
        self.runtime.ai_agent = self.agent
        self.runtime.messages = [
            {"role": "user", "content": "runtime context to summarize"},
        ]
        self.agent_response = None
        self.summary_chat = None
        self.summary_answer = None

    def exercise_both_paths(self) -> None:
        """Send one real request from Agent2LLM and one from summarization."""
        self.agent_response = self.agent.llm_model.call_llm_model([
            {"role": "user", "content": "agent2llm identity request"},
        ])
        self.agent.messages.append(
            {"role": "user", "content": "runtime context to summarize"}
        )
        self.summary_chat, self.summary_answer = self.runtime._summarize_messages(
            self.runtime.messages,
            extra_prompt="Summarize this runtime context.",
        )

    def state(self) -> dict[str, Any]:
        """Read the provider's actual request state over HTTP."""
        url = f"http://127.0.0.1:{self.server.server_port}/debug/state"
        with urllib.request.urlopen(url, timeout=3) as response:
            return json.load(response)

    def agent_handle(self):
        """Return the Agent2LLM model's primary pooled-client lease."""
        return self.agent.llm_model.snapshot_llm_model_leases()[0]

    def summary_handle(self):
        """Return the summary model's primary pooled-client lease."""
        assert self.summary_chat is not None
        return self.summary_chat.llm_model.snapshot_llm_model_leases()[0]

    def close(self) -> None:
        """Stop only this scenario's runtime components and mock provider."""
        if self.summary_chat is not None:
            self.summary_chat.close()
        self.agent.close()
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=5)
        if self.server_thread.is_alive():
            raise AssertionError("OpenAI client-reuse mock-server thread did not stop")
        default_openai_client_pool.close_all()


class AgentModelSummaryScenario(OpenAIClientReuseScenario):
    """Exercise runtime summarization through the active Agent2LLM model."""

    def __init__(self, monkeypatch: Any):
        """Configure model borrowing after the shared HTTP harness is ready."""
        super().__init__(monkeypatch)
        monkeypatch.setenv(
            "TOPSAILAI_CONTEXT_SUMMARY_PROCESSOR",
            "agent_llm_model",
        )
        self.borrowed_model = None
        self.borrowed_handle = None

    def exercise_borrowed_summary_and_later_request(self) -> None:
        """Summarize, close the borrowing wrapper, then reuse the agent model."""
        self.agent.messages.append(
            {"role": "user", "content": "runtime context to summarize"}
        )
        self.summary_chat, self.summary_answer = self.runtime._summarize_messages(
            self.runtime.messages,
            extra_prompt="Summarize this runtime context.",
        )
        self.borrowed_model = self.summary_chat.llm_model
        self.borrowed_handle = self.summary_handle()
        self.summary_chat.close()
        self.agent_response = self.agent.llm_model.call_llm_model([
            {"role": "user", "content": "agent2llm request after borrowed summary"},
        ])

    def close(self) -> None:
        """Avoid duplicate wrapper cleanup before closing the owning agent."""
        self.summary_chat = None
        super().close()
