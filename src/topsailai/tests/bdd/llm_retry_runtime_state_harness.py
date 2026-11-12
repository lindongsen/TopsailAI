"""Real HTTP/SSE harness for LLM retry Runtime Data BDD."""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from contextlib import ExitStack
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from topsailai.ai_base.exception import LLMRetryExhaustedError
from topsailai.ai_base.llm_base import LLMModel
from topsailai.ai_base.llm_control.llm_retry import LLMRetryInteractionPolicy
from topsailai.ai_base.llm_control.retry_runtime_state import RUNTIME_STATE_KEY
from topsailai.ai_base.runtime_data import RuntimeDataStore
from topsailai.tests.mock.llm_mock_server import MockServerConfig, create_server
from topsailai.utils.thread_local_tool import ctxm_set_agent


SUCCESS_RESPONSE = "runtime state recovered response"
MAX_ATTEMPTS = 18


def _skip_retry_backoff():
    """Skip production backoff while retaining every retry decision."""
    clock = MagicMock(wraps=time)
    clock.sleep = MagicMock(return_value=None)
    return patch("topsailai.ai_base.llm_base.time", clock)


class RetryRuntimeStateScenario:
    """Own one real provider, Agent Store, request thread, and evidence set."""

    def __init__(self, monkeypatch: Any):
        """Initialize isolated request state and loopback configuration."""
        self.monkeypatch = monkeypatch
        self.store = RuntimeDataStore(history_capacity=4)
        self.agent = SimpleNamespace(runtime=SimpleNamespace(runtime_data=self.store))
        self.server = None
        self.server_thread: threading.Thread | None = None
        self.request_thread: threading.Thread | None = None
        self.held_handle = None
        self.model: LLMModel | None = None
        self.result: str | None = None
        self.error: BaseException | None = None
        self.use_agent = True
        self.messages = [
            {"role": "system", "content": "Runtime Data BDD assistant"},
            {"role": "user", "content": "sensitive-prompt-sentinel"},
        ]
        self._configure_environment()

    def _configure_environment(self) -> None:
        """Configure production LLM code for one private streaming endpoint."""
        values = {
            "OPENAI_API_KEY": "sensitive-api-sentinel",
            "OPENAI_MODEL": "bdd-runtime-data-model",
            "LLM_RESPONSE_STREAM": "1",
            "TOPSAILAI_LLM_REQUEST_RETRY_STATE_THRESHOLD": "3",
            "TOPSAILAI_LLM_RESPONSE_EVENTS_ENABLED": "0",
            "TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT": "0",
            "TOPSAILAI_PRINT_TOOL_STAT": "0",
            "TOPSAILAI_INTERACTIVE_MODE": "0",
            "DEBUG": "0",
        }
        for key, value in values.items():
            self.monkeypatch.setenv(key, value)

    def start(self, failures: int, *, hold_success: bool = False) -> None:
        """Start request-indexed SSE failures followed by a success when present."""
        total = failures if failures == MAX_ATTEMPTS else failures + 1
        errors = tuple(f"provider retry failure {index}" for index in range(failures))
        errors += (None,) * (total - failures)
        responses = tuple((SUCCESS_RESPONSE,) for _ in range(total))
        delays = [0.0] * total
        if hold_success:
            delays[-1] = 3600.0
        self.server = create_server(MockServerConfig(
            port=0,
            request_body_capacity=32,
            lifecycle_capacity=32,
            stream_response_chunks=responses,
            stream_error_messages=errors,
            first_chunk_delays=tuple(delays),
        ))
        self.server_thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
            name="retry-runtime-state-bdd-server",
        )
        self.server_thread.start()
        host, port = self.server.server_address
        base_url = f"http://{host}:{port}/v1"
        self.monkeypatch.setenv("OPENAI_API_BASE", base_url)
        self.monkeypatch.setenv("OPENAI_BASE_URL", base_url)
        self.model = LLMModel()
        self.agent.runtime.llm_model = self.model

    def run_async(self, held_request_number: int) -> None:
        """Start the production request and wait for its successful attempt hold."""
        self.request_thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="retry-runtime-state-bdd-request",
        )
        self.request_thread.start()
        assert self.server.lifecycle_capture.wait_for_request(
            held_request_number, timeout=10
        ), "held provider request was not accepted"
        self.held_handle = self.server.lifecycle_capture.request_handle(
            held_request_number
        )
        assert self.held_handle.wait_for_phase(
            "first_item", timeout=10
        ), "successful provider request did not reach its hold"

    def run(self) -> None:
        """Run one request synchronously for final-state scenarios."""
        self._run()

    def _run(self) -> None:
        """Execute the real LLM request with optional Agent ownership."""
        assert self.model is not None
        policy = LLMRetryInteractionPolicy(
            interactive_enabled=False,
            max_manual_retry_cycles=0,
        )
        try:
            with ExitStack() as stack:
                stack.enter_context(_skip_retry_backoff())
                if self.use_agent:
                    stack.enter_context(ctxm_set_agent(self.agent))
                self.result = self.model.chat(
                    self.messages,
                    for_raw=True,
                    for_stream=True,
                    retry_interaction_policy=policy,
                )
        except BaseException as error:  # noqa: BLE001 - BDD asserts exact result
            self.error = error

    def release_and_join(self) -> None:
        """Release the exact held request and join the exact request thread."""
        assert self.held_handle is not None
        assert self.request_thread is not None
        self.held_handle.release_delay()
        self.request_thread.join(timeout=10)
        assert not self.request_thread.is_alive(), "LLM request thread did not stop"

    def provider_state(self) -> dict[str, Any]:
        """Return server-side request evidence from the debug endpoint."""
        assert self.server is not None
        host, port = self.server.server_address
        with urllib.request.urlopen(
            f"http://{host}:{port}/debug/state", timeout=5
        ) as response:
            return json.load(response)

    def active_retry_state(self):
        """Return the one public LLM retry state when active."""
        return self.store.get(RUNTIME_STATE_KEY)

    def retry_history(self):
        """Return bounded settled history for the LLM retry key."""
        return self.store.history(RUNTIME_STATE_KEY)

    def assert_no_sensitive_runtime_content(self) -> None:
        """Reject prompt, credentials, response content, and full error details."""
        encoded = json.dumps(
            [item.__dict__ for item in self.store.snapshot()]
            + [item.__dict__ for item in self.store.history()],
            sort_keys=True,
        )
        for sentinel in (
            "sensitive-prompt-sentinel",
            "sensitive-api-sentinel",
            SUCCESS_RESPONSE,
            "provider retry failure",
        ):
            assert sentinel not in encoded

    def assert_provider_messages_unchanged(self) -> None:
        """Verify Runtime Data never enters provider conversation messages."""
        records = self.provider_state()["request_bodies"]
        assert records
        assert all(record["parsed"] for record in records)
        assert all(record["body"]["messages"] == self.messages for record in records)
        encoded = json.dumps(records, sort_keys=True)
        assert RUNTIME_STATE_KEY not in encoded
        assert "failed_attempts" not in encoded

    def close(self) -> None:
        """Release and close every exact resource owned by this scenario."""
        if self.held_handle is not None:
            self.held_handle.release_delay()
        if self.request_thread is not None and self.request_thread.is_alive():
            self.request_thread.join(timeout=10)
            if self.request_thread.is_alive():
                raise AssertionError("retry Runtime Data request thread did not stop")
        if self.model is not None:
            self.model.close()
        if self.server is not None:
            self.server.stop_handlers(timeout=5)
            self.server.shutdown()
            self.server.server_close()
        if self.server_thread is not None:
            self.server_thread.join(timeout=5)
            if self.server_thread.is_alive():
                raise AssertionError("retry Runtime Data server thread did not stop")


__all__ = [
    "LLMRetryExhaustedError",
    "MAX_ATTEMPTS",
    "RetryRuntimeStateScenario",
    "SUCCESS_RESPONSE",
]
