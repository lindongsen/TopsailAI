"""Real-HTTP harness for context-summary cached-token warnings."""

from __future__ import annotations

import json
import threading
import urllib.request
from typing import Any

from tests.mock.llm_mock_server import MockServerConfig, create_server
from topsailai.ai_base.agent_base import AgentRun
from topsailai.ai_base.llm_pool.openai_client_pool import default_openai_client_pool
from topsailai.workspace.context.base import ContextRuntimeBase


class SummarizeCachedTokenWarningScenario:
    """Own one production summary runtime and one private mock provider."""

    def __init__(self, monkeypatch: Any, mode: str):
        """Configure deterministic cache behavior for one scenario mode."""
        self.monkeypatch = monkeypatch
        self.mode = mode
        default_openai_client_pool.close_all()
        response_content = json.dumps([
            {"step_name": "final_answer", "raw_text": "Summary response"}
        ])
        self.server = create_server(MockServerConfig(
            port=0,
            reply=response_content,
            stream_chunks=(response_content,),
            report_cache_usage=mode != "missing",
        ))
        self.server_thread = threading.Thread(
            target=self.server.serve_forever,
            name="bdd-summarize-cache-warning-server",
            daemon=True,
        )
        self.server_thread.start()
        base_url = f"http://127.0.0.1:{self.server.server_port}/v1"
        values = {
            "OPENAI_API_BASE": base_url,
            "OPENAI_BASE_URL": base_url,
            "OPENAI_API_KEY": "mock-summarize-cache-warning",
            "OPENAI_MODEL": "topsailai-summarize-cache-warning",
            "LLM_RESPONSE_STREAM": "0",
            "TOPSAILAI_CONTEXT_SUMMARY_MODE": "runtime",
            "TOPSAILAI_CONTEXT_SUMMARY_PROCESSOR": "agent_llm_model",
            "TOPSAILAI_INTERACTIVE_MODE": "0",
            "TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT": "0",
            "TOPSAILAI_LLM_RESPONSE_EVENTS_ENABLED": "0",
            "TOPSAILAI_MODEL_SETTINGS": "",
            "TOPSAILAI_USE_TOOL_CALLS": "0",
            "TOPSAILAI_USE_TOOL_CALLS_MODEL_PREFIXES": "",
        }
        for key, value in values.items():
            monkeypatch.setenv(key, value)
        monkeypatch.setattr(
            "topsailai.workspace.llm_shell.record_project_history",
            lambda _session_id: None,
        )
        self.warnings: list[str] = []
        monkeypatch.setattr(
            "topsailai.workspace.context.base.print_tool.print_warning",
            self.warnings.append,
        )
        self.agent = AgentRun(
            system_prompt="You are the cached-token warning test agent.",
            tools={},
            agent_name="BDDSummarizeCachedTokenWarning",
        )
        self.runtime = ContextRuntimeBase()
        self.runtime.ai_agent = self.agent
        self.runtime.messages = []
        self.before: int | None = None
        self.after: int | None = None
        self.summary_chat = None
        self.summary_answer = None

    @staticmethod
    def _messages(label: str) -> list[dict[str, str]]:
        """Return a stable provider request prefix for cache comparisons."""
        return [
            {"role": "system", "content": f"Cache warning system {label}"},
            {"role": "user", "content": f"Runtime context {label}"},
        ]

    def _request(self, messages: list[dict[str, str]]) -> None:
        """Send one production non-streaming request through the OpenAI client."""
        response, content = self.agent.llm_model.call_llm_model(
            messages,
            tools=None,
            tool_choice="auto",
        )
        assert response is not None
        assert content

    def exercise(self) -> None:
        """Establish the selected relation, then run production summarization."""
        if self.mode == "decrease":
            warm_messages = self._messages("warm")
            self._request(warm_messages)
            self._request(warm_messages)
            self.agent.messages = self._messages("different")
        elif self.mode == "increase":
            self.agent.messages = self._messages("shared")
            self._request(self.agent.messages)
        elif self.mode == "equal":
            self._request(self._messages("warm"))
            self.agent.messages = self._messages("different")
        elif self.mode == "missing":
            self.agent.messages = self._messages("missing-usage")
        else:
            raise ValueError(f"unknown scenario mode: {self.mode}")

        self.before = self.agent.llm_model.tokenStat.current_cached_tokens
        self.summary_chat, self.summary_answer = self.runtime._summarize_messages(
            self.agent.messages,
            extra_prompt="Summarize this runtime context for the cache warning test.",
        )
        self.after = self.agent.llm_model.tokenStat.current_cached_tokens

    def expected_request_count(self) -> int:
        """Return warm-up requests plus the single summary request."""
        return {"decrease": 3, "increase": 2, "equal": 2, "missing": 1}[self.mode]

    def state(self) -> dict[str, Any]:
        """Read provider request bodies and cache accounting over HTTP."""
        url = f"http://127.0.0.1:{self.server.server_port}/debug/state"
        with urllib.request.urlopen(url, timeout=3) as response:
            return json.load(response)

    def close(self) -> None:
        """Close the borrowed wrapper, owning agent, server, and exact thread."""
        if self.summary_chat is not None:
            self.summary_chat.close()
        self.agent.close()
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=5)
        if self.server_thread.is_alive():
            raise AssertionError("summarize cache-warning mock-server thread did not stop")
        default_openai_client_pool.close_all()
