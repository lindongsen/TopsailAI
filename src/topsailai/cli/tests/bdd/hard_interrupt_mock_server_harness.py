"""HTTP/SSE integration harness for hard-interrupt retry behavior."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import openai

from topsailai.ai_base.exception import HardInterruptError
from topsailai.ai_base.llm_base import LLMModel
from topsailai.tests.mock.llm_mock_server import MockServerConfig, create_server


class HardInterruptMockServerHarness:
    """Drive real LLMModel streaming through the official HTTP client."""

    def __init__(self, monkeypatch) -> None:
        """Start an SSE mock server and construct a real OpenAI-backed model."""
        import topsailai.ai_base.llm_base as llm_module

        self.monkeypatch = monkeypatch
        self.llm_module = llm_module
        self.server = create_server(MockServerConfig(
            port=0,
            stream_chunks=("HTTP stream chunk",),
        ))
        self.server_thread = threading.Thread(
            target=self.server.serve_forever,
            name="bdd-hard-interrupt-llm-mock-server",
            daemon=True,
        )
        self.server_thread.start()
        base_url = f"http://127.0.0.1:{self.server.server_port}/v1"
        monkeypatch.setenv("OPENAI_API_BASE", base_url)
        monkeypatch.setenv("OPENAI_BASE_URL", base_url)
        monkeypatch.setenv("OPENAI_API_KEY", "mock")
        monkeypatch.setenv("OPENAI_MODEL", "topsailai-mock")
        monkeypatch.setenv("LLM_RESPONSE_STREAM", "1")
        monkeypatch.setenv("TOPSAILAI_LLM_RESPONSE_EVENTS_ENABLED", "0")
        monkeypatch.setenv("TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT", "0")
        self.retry_prompt = MagicMock(return_value=True)
        self.agent = MagicMock()
        self.error: BaseException | None = None
        monkeypatch.setattr(llm_module, "get_agent_object", lambda: self.agent)
        monkeypatch.setattr(llm_module, "input_yes_or_no", self.retry_prompt)
        monkeypatch.setattr(llm_module.thread_tool, "is_main_thread", lambda: True)
        self.model = LLMModel()
        self.messages = [{"role": "user", "content": "BDD HTTP hard interrupt"}]

    def set_retry_answer(self, answer: str) -> None:
        """Set the answer that would be returned if retry were prompted."""
        self.retry_prompt.return_value = answer == "yes"

    def arrange_stream_interrupt(self) -> None:
        """Raise after the first SSE content chunk reaches production code."""
        self.agent._check_hard_interrupt.side_effect = [
            None,
            HardInterruptError("HTTP stream interrupted"),
        ]

    def arrange_retry_loop_interrupt(self) -> None:
        """Finish one SSE request, then interrupt the next retry-loop check."""
        self.agent._check_hard_interrupt.side_effect = [
            None,
            None,
            None,
            HardInterruptError("HTTP retry interrupted"),
        ]
        self.monkeypatch.setattr(
            self.model,
            "fix_response_content",
            MagicMock(side_effect=openai.APIConnectionError(request=MagicMock())),
        )

    def execute_streaming_chat(self) -> None:
        """Run the production streaming chat and retain its exception."""
        try:
            self.model.chat(self.messages, for_raw=True, for_stream=True)
        except BaseException as error:
            self.error = error

    @property
    def request_count(self) -> int:
        """Return the number of completion requests observed by the server."""
        return self.server.prompt_cache.state()["total_requests"]

    def close(self) -> None:
        """Stop the exact model thread and HTTP server owned by this scenario."""
        self.model.tokenStat.flag_running = False
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=2)
