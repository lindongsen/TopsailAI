"""In-process driver for cached-token behavior against the LLM mock server."""

from __future__ import annotations

import threading
from types import MethodType, SimpleNamespace
from typing import Any

from topsailai.ai_base.llm_base import LLMModel
from topsailai.tests.mock.llm_mock_server import MockServerConfig, create_server
from topsailai.workspace.context.agent2llm import ContextRuntimeAgent2LLM


class _HarnessAgent:
    """Provide the minimal real context-runtime contract needed by summarization."""

    def __init__(self, model: LLMModel, messages: list[dict[str, Any]]):
        """Attach a real model and mutable Agent2LLM messages."""
        self.llm_model = model
        self.messages = list(messages)
        self.agent_type = "react"

    @staticmethod
    def get_work_memory_first_position() -> int:
        """Treat the complete harness message list as working memory."""
        return 0


class CachedTokensHarness:
    """Drive real HTTP requests and the real Agent2LLM summary rebuild path."""

    def __init__(self, monkeypatch):
        """Start an isolated mock endpoint and construct the real LLM client."""
        self.server = create_server(MockServerConfig(port=0, reply="Mock summary"))
        self.server_thread = threading.Thread(
            target=self.server.serve_forever,
            name="bdd-llm-mock-server",
            daemon=True,
        )
        self.server_thread.start()
        base_url = f"http://127.0.0.1:{self.server.server_port}/v1"
        monkeypatch.setenv("OPENAI_API_BASE", base_url)
        monkeypatch.setenv("OPENAI_BASE_URL", base_url)
        monkeypatch.setenv("OPENAI_API_KEY", "mock")
        monkeypatch.setenv("OPENAI_MODEL", "topsailai-mock")
        monkeypatch.setenv("LLM_RESPONSE_STREAM", "0")
        monkeypatch.setenv("TOPSAILAI_LLM_RESPONSE_EVENTS_ENABLED", "0")
        monkeypatch.setenv("TOPSAILAI_CTX_SUMMARY_KEEP_SESSION_MESSAGES", "0")
        monkeypatch.setenv("TOPSAILAI_CONTEXT_MESSAGES_HEAD_OFFSET_TO_KEEP", "0")
        monkeypatch.setenv("TOPSAILAI_CONTEXT_MESSAGES_TAIL_OFFSET_TO_KEEP", "0")
        self.model = LLMModel()
        self.messages: list[dict[str, Any]] = []
        self.last_response = None
        self.last_summary_message_count: int | None = None

    @staticmethod
    def stable_messages() -> list[dict[str, Any]]:
        """Return a conversation with a stable leading system and task prefix."""
        return [
            {"role": "system", "content": "cache behavior system prompt"},
            {
                "role": "user",
                "content": {"step_name": "task", "raw_text": "analyze cache behavior"},
            },
            {"role": "assistant", "content": "first result"},
            {"role": "user", "content": "continue"},
        ]

    def request(self, messages: list[dict[str, Any]]) -> int | None:
        """Send one non-streaming request through TopsailAI and return cache usage."""
        self.messages = list(messages)
        self.last_response, _ = self.model.call_llm_model(self.messages)
        return self.model.tokenStat.current_cached_tokens

    def summarize(self) -> str | None:
        """Rebuild Agent2LLM context while replacing only summary generation."""
        agent = _HarnessAgent(self.model, self.messages)
        runtime = ContextRuntimeAgent2LLM()
        runtime.ai_agent = agent
        runtime.messages = [self.messages[0]] if self.messages else []

        summary_message = {"role": "assistant", "content": "Mock summary"}
        summary_chat = SimpleNamespace(
            prompt_ctl=SimpleNamespace(messages=[summary_message])
        )

        def _deterministic_summary(_runtime, _messages):
            """Return a deterministic summary while preserving the rebuild logic."""
            return summary_chat, "Mock summary"

        runtime._summarize_messages = MethodType(_deterministic_summary, runtime)
        answer = runtime.summarize_messages_for_processing(force=True)
        self.messages = list(agent.messages)
        self.last_summary_message_count = len(self.messages) if answer else None
        return answer

    @property
    def cached_tokens(self) -> int | None:
        """Return the currently observable cached-token statistic."""
        return self.model.tokenStat.current_cached_tokens

    @property
    def uncached_tokens(self) -> int | None:
        """Return the currently observable uncached-token statistic."""
        return self.model.tokenStat.uncached_tokens

    def response_cached_tokens(self) -> int:
        """Return cached tokens reported by the mock response for the last request."""
        return self.last_response.usage.prompt_tokens_details.cached_tokens

    def response_prompt_tokens(self) -> int:
        """Return total prompt tokens reported for the most recent request."""
        return self.last_response.usage.prompt_tokens

    def last_cache_result(self) -> dict[str, int]:
        """Return the mock server's cache metadata for the most recent request."""
        return self.server.prompt_cache.state()["requests"][-1]

    def close(self) -> None:
        """Stop the exact server and TokenStat thread created by this harness."""
        self.model.tokenStat.flag_running = False
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=2)
