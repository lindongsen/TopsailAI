"""HTTP/SSE integration harness for llm_mock_server streaming behavior."""

from __future__ import annotations

import json
import threading
import urllib.request
from unittest.mock import MagicMock

from topsailai.ai_base.llm_base import LLMModel
from topsailai.tests.mock.llm_mock_server import (
    LLMMockRequestHandler,
    MockServerConfig,
    create_server,
)


class _CountingRequestHandler(LLMMockRequestHandler):
    """Count every POST before delegating to the original mock handler."""

    def do_POST(self) -> None:
        """Count the POST even when the mock server rejects it with 400."""
        self.server.post_count += 1
        super().do_POST()


class StreamingMockServerHarness:
    """Drive real LLMModel streaming through the official HTTP client."""

    def __init__(self, monkeypatch, stream_chunks=("Hello ", "streaming ", "world")) -> None:
        """Start an SSE mock server and construct a real OpenAI-backed model.

        ``stream_chunks=None`` configures the server with streaming disabled
        so that a ``stream=true`` request is rejected with HTTP 400.
        """
        self.monkeypatch = monkeypatch
        self.server = create_server(MockServerConfig(
            port=0,
            stream_chunks=stream_chunks,
        ))
        # Count POSTs at the HTTP layer because requests rejected with 400
        # never reach the mock server's prompt-cache accounting.
        self.server.post_count = 0
        self.server.RequestHandlerClass = _CountingRequestHandler
        self.server_thread = threading.Thread(
            target=self.server.serve_forever,
            name="bdd-streaming-llm-mock-server",
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
        self.agent = MagicMock()
        self.error: BaseException | None = None
        self.result: tuple | None = None
        import topsailai.ai_base.llm_base as llm_module

        self.llm_module = llm_module
        monkeypatch.setattr(llm_module, "get_agent_object", lambda: self.agent)
        monkeypatch.setattr(llm_module.thread_tool, "is_main_thread", lambda: True)
        self.model = LLMModel()
        self.messages = [{"role": "user", "content": "BDD streaming mock server"}]

    def execute_streaming_chat(self) -> str:
        """Run the production streaming chat and return its raw content."""
        return self.model.chat(self.messages, for_raw=True, for_stream=True)

    def execute_streaming_chat_direct(self) -> None:
        """Call call_llm_model_by_stream directly, bypassing the chat retry loop."""
        try:
            self.result = self.model.call_llm_model_by_stream(self.messages)
        except BaseException as error:
            self.error = error

    def get_state(self) -> dict:
        """Return the full /debug/state snapshot from the mock server."""
        with urllib.request.urlopen(
            f"http://127.0.0.1:{self.server.server_port}/debug/state",
            timeout=5,
        ) as response:
            return json.loads(response.read().decode("utf-8"))

    @property
    def request_count(self) -> int:
        """Return the number of POST requests observed at the HTTP layer."""
        return self.server.post_count

    def close(self) -> None:
        """Stop the exact model thread and HTTP server owned by this scenario."""
        self.model.tokenStat.flag_running = False
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=2)
