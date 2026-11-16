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

# One summary request is a raw-mode request, which is how the production
# summarizer calls the model.
SUMMARY_MODE = "raw"

# One ordinary agent request, which must never count toward the limit.
ORDINARY_MODE = "response_and_parsed"


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

    def _send(self, mode: str) -> None:
        """Send one request through the production boundary in the given mode."""
        assert self.model is not None
        assert self.agent is not None
        policy = LLMRetryInteractionPolicy(
            interactive_enabled=False,
            max_manual_retry_cycles=0,
        )
        messages = [{"role": "user", "content": "summarize the conversation"}]
        with ctxm_set_agent(self.agent):
            if mode == SUMMARY_MODE:
                self.model.chat(
                    messages,
                    for_raw=True,
                    retry_interaction_policy=policy,
                )
            else:
                self.model.chat(
                    messages,
                    for_response=True,
                    retry_interaction_policy=policy,
                )
        self.completed_requests += 1

    def run_sequence(self, modes: tuple[str, ...]) -> None:
        """Send each request in order, stopping at the first guard termination."""
        for mode in modes:
            try:
                self._send(mode)
            except SummaryWindowLimitError as error:
                self.error = error
                return

    def run_three_summaries(self) -> None:
        """Send exactly three summary requests, which must stay below the limit."""
        self.run_sequence((SUMMARY_MODE,) * 3)

    def run_four_summaries(self) -> None:
        """Send four summary requests, where the fourth must terminate the turn."""
        self.run_sequence((SUMMARY_MODE,) * 4)

    def run_interleaved(self) -> None:
        """Send summary traffic interleaved with ordinary agent requests."""
        self.run_sequence(
            (
                SUMMARY_MODE, ORDINARY_MODE,
                SUMMARY_MODE, ORDINARY_MODE,
                SUMMARY_MODE, ORDINARY_MODE,
                SUMMARY_MODE, ORDINARY_MODE,
                SUMMARY_MODE, ORDINARY_MODE,
                SUMMARY_MODE, ORDINARY_MODE,
                SUMMARY_MODE, ORDINARY_MODE,
                SUMMARY_MODE, ORDINARY_MODE,
            )
        )

    def run_ordinary_only(self) -> None:
        """Send only ordinary agent requests, which must never terminate."""
        self.run_sequence((ORDINARY_MODE,) * 12)

    def run_disabled(self) -> None:
        """Send summary traffic with the guard disabled by a zero limit."""
        self.run_sequence((SUMMARY_MODE,) * 6)

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

    def window_snapshot(self) -> list[str]:
        """Return the recorded return modes, oldest first."""
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
