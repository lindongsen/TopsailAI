"""Real HTTP/SSE harness for the sliding-window summary guard BDD.

The guard is a bottom-line safety net: when the most recent LLM requests are
dominated by summary requests, the turn must end instead of continuing to burn
tokens. These scenarios drive the production request boundary over a real
loopback provider so the client, transport and guard wiring all stay inside the
assertion boundary, and they assert the provider-side request count to prove the
guard fires *before* the offending request is sent.
"""

from __future__ import annotations

import json
import threading
import urllib.request
from typing import Any

from topsailai.ai_base.exception import SummaryWindowLimitError
from topsailai.ai_base.llm_base import LLMModel
from topsailai.ai_base.llm_control.llm_retry import LLMRetryInteractionPolicy
from topsailai.ai_base.llm_control.summary_window_guard import SummaryWindowGuard
from topsailai.tests.mock.llm_mock_server import MockServerConfig, create_server
from topsailai.utils.thread_local_tool import ctxm_set_agent

SUCCESS_RESPONSE = "summary window response"

# Explicit marker for one summary request. The scenario states the request's
# purpose directly instead of deriving it from the return shape, because the
# return shape is shared by unrelated callers such as multimodal recognition.
SUMMARY_REQUEST = True

# Explicit marker for one ordinary agent request, which must never count.
ORDINARY_REQUEST = False


class _LLMModelName(object):
    """Minimal model handle exposing only the model name."""

    model_name = "bdd-summary-window-model"


class _Runtime(object):
    """Minimal runtime exposing the model name the hook resolver reads."""

    def __init__(self):
        """Expose one model name through the production attribute path."""
        self.llm_model = _LLMModelName()


class _Agent(object):
    """Minimal agent that owns the guard, as the production agent does.

    The request boundary also reads the model name from the active agent when
    it resolves model-specific hooks, so the stub must expose the same
    ``runtime.llm_model.model_name`` shape the real agent has.
    """

    def __init__(self, window_size: int, max_summaries: int):
        """Attach one guard with explicit settings and a model-name contract."""
        self._summary_window_guard = SummaryWindowGuard(
            window_size=window_size, max_summaries=max_summaries
        )
        self.runtime = _Runtime()

    def _check_hard_interrupt(self):
        """Accept the interrupt probe the request boundary performs."""
        return None


class SummaryWindowGuardScenario:
    """Own one real-HTTP guard scenario and all of its evidence."""

    def __init__(self, monkeypatch: Any):
        """Initialize isolated configuration for one scenario."""
        self.monkeypatch = monkeypatch
        self.server = None
        self.thread: threading.Thread | None = None
        self.model: LLMModel | None = None
        self.agent: _Agent | None = None
        self.error: BaseException | None = None
        self.completed_requests = 0
        self._configure_environment()

    def _configure_environment(self) -> None:
        """Configure only the loopback provider and deterministic runtime flags."""
        values = {
            "OPENAI_API_KEY": "bdd-test-key",
            "OPENAI_MODEL": "bdd-summary-window-model",
            "LLM_RESPONSE_STREAM": "0",
            "TOPSAILAI_LLM_RESPONSE_EVENTS_ENABLED": "0",
            "TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT": "0",
            "TOPSAILAI_PRINT_TOOL_STAT": "0",
            "TOPSAILAI_INTERACTIVE_MODE": "0",
            "TOPSAILAI_LLM_REQUEST_WALL_CLOCK_BUDGET_SEC": "0",
            "DEBUG": "0",
        }
        for key, value in values.items():
            self.monkeypatch.setenv(key, value)

    def start(self, window_size: int = 10, max_summaries: int = 3) -> None:
        """Start one loopback provider and build the agent-owned guard."""
        config = MockServerConfig(
            port=0,
            request_body_capacity=64,
            reply=SUCCESS_RESPONSE,
            complete_response_replies=(SUCCESS_RESPONSE,) * 64,
        )
        self.server = create_server(config)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        base_url = f"http://{host}:{port}/v1"
        self.monkeypatch.setenv("OPENAI_API_BASE", base_url)
        self.monkeypatch.setenv("OPENAI_BASE_URL", base_url)
        self.model = LLMModel()
        self.agent = _Agent(window_size=window_size, max_summaries=max_summaries)

    def _send(self, is_summary: bool) -> None:
        """Send one request through the production boundary with its marker."""
        assert self.model is not None
        assert self.agent is not None
        policy = LLMRetryInteractionPolicy(
            interactive_enabled=False,
            max_manual_retry_cycles=0,
        )
        messages = [{"role": "user", "content": "summarize the conversation"}]
        with ctxm_set_agent(self.agent):
            if is_summary:
                self.model.chat(
                    messages,
                    is_summary_request=True,
                    retry_interaction_policy=policy,
                )
            else:
                self.model.chat(
                    messages,
                    for_response=True,
                    retry_interaction_policy=policy,
                )
        self.completed_requests += 1

    def run_sequence(self, markers: tuple[bool, ...]) -> None:
        """Send each request in order, stopping at the first guard termination."""
        for is_summary in markers:
            try:
                self._send(is_summary)
            except SummaryWindowLimitError as error:
                self.error = error
                return

    def run_three_summaries(self) -> None:
        """Send exactly three summary requests, which must stay below the limit."""
        self.run_sequence((SUMMARY_REQUEST,) * 3)

    def run_four_summaries(self) -> None:
        """Send four summary requests, where the fourth must terminate the turn."""
        self.run_sequence((SUMMARY_REQUEST,) * 4)

    def run_interleaved(self) -> None:
        """Send summary traffic interleaved with ordinary agent requests."""
        self.run_sequence(
            (
                SUMMARY_REQUEST, ORDINARY_REQUEST,
                SUMMARY_REQUEST, ORDINARY_REQUEST,
                SUMMARY_REQUEST, ORDINARY_REQUEST,
                SUMMARY_REQUEST, ORDINARY_REQUEST,
                SUMMARY_REQUEST, ORDINARY_REQUEST,
                SUMMARY_REQUEST, ORDINARY_REQUEST,
                SUMMARY_REQUEST, ORDINARY_REQUEST,
                SUMMARY_REQUEST, ORDINARY_REQUEST,
            )
        )

    def run_ordinary_only(self) -> None:
        """Send only ordinary agent requests, which must never terminate."""
        self.run_sequence((ORDINARY_REQUEST,) * 12)

    def run_disabled(self) -> None:
        """Send summary traffic with the guard disabled by a zero limit."""
        self.run_sequence((SUMMARY_REQUEST,) * 6)

    def run_retry_storm(self, failures: int = 12) -> None:
        """Send one summary request that the provider fails many times.

        This reproduces the incident shape: a single logical summary request
        retried repeatedly. Counting only the logical request recorded it once,
        so the window never exceeded the limit and the turn never ended. The
        provider really returns the scripted errors, so every retry is a real
        HTTP attempt, and only the backoff wait is skipped to keep the scenario
        fast.

        The provider sees nine requests, not four, because the OpenAI SDK
        retries each failed HTTP attempt internally before the outer retry loop
        observes the failure. Three outer attempts therefore reach the provider
        three times each. The fourth outer attempt is stopped by the guard
        before it is sent, so the provider never receives the remaining nine
        scripted failures. That difference is exactly what the guard
        contributes, and it is why the scenario asserts the provider count.
        """
        assert self.model is not None
        assert self.agent is not None
        self._restart_server_with_errors(failures)
        policy = LLMRetryInteractionPolicy(
            interactive_enabled=False,
            max_manual_retry_cycles=0,
        )
        messages = [{"role": "user", "content": "summarize the conversation"}]
        with self._no_backoff():
            with ctxm_set_agent(self.agent):
                try:
                    self.model.chat(
                        messages,
                        is_summary_request=True,
                        for_stream=True,
                        retry_interaction_policy=policy,
                    )
                except SummaryWindowLimitError as error:
                    self.error = error

    def _restart_server_with_errors(self, failures: int) -> None:
        """Replace the provider with one that fails the first N attempts."""
        self._stop_server()
        config = MockServerConfig(
            port=0,
            request_body_capacity=64,
            reply=SUCCESS_RESPONSE,
            complete_response_replies=(SUCCESS_RESPONSE,) * 64,
            # Streaming must be enabled or the mock rejects the request with
            # 400 before it can serve any scripted error.
            stream_chunks=(SUCCESS_RESPONSE,),
            stream_http_error_responses=((500, "scripted retry storm"),) * failures,
        )
        self.server = create_server(config)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        base_url = f"http://{host}:{port}/v1"
        self.monkeypatch.setenv("OPENAI_API_BASE", base_url)
        self.monkeypatch.setenv("OPENAI_BASE_URL", base_url)
        # The model captured the previous endpoint when it was built, so it must
        # be rebuilt against the new port or every attempt fails to connect.
        if self.model is not None:
            self.model.close()
        self.model = LLMModel()

    def _stop_server(self) -> None:
        """Stop the current provider and its exact serving thread."""
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None
        if self.thread is not None:
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                raise AssertionError("summary-window BDD server thread did not stop")
            self.thread = None

    def _no_backoff(self):
        """Skip retry backoff sleeps so the scenario stays fast."""
        from unittest.mock import patch

        return patch("topsailai.ai_base.llm_base.time.sleep")

    def state(self) -> dict[str, Any]:
        """Read provider-side request evidence through the debug endpoint."""
        assert self.server is not None
        host, port = self.server.server_address
        with urllib.request.urlopen(
            f"http://{host}:{port}/debug/state", timeout=5
        ) as response:
            return json.load(response)

    def provider_request_count(self) -> int:
        """Return how many requests actually reached the provider."""
        return len(self.state()["request_bodies"])

    def window_snapshot(self) -> list[bool]:
        """Return the recorded summary markers, oldest first."""
        assert self.agent is not None
        return self.agent._summary_window_guard.snapshot()

    def close(self) -> None:
        """Close the model, exact server, and exact serving thread."""
        if self.model is not None:
            self.model.close()
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                raise AssertionError("summary-window BDD server thread did not stop")
