"""Real HTTP/SSE harness for bounded null-response recovery BDD."""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from contextlib import ExitStack
from typing import Any
from unittest.mock import MagicMock, patch

from topsailai.ai_base.llm_base import LLMModel
from topsailai.ai_base.llm_control.llm_retry import LLMRetryInteractionPolicy
from topsailai.tests.mock.llm_mock_server import MockServerConfig, create_server

SUCCESS_RESPONSE = "recovered response"
DEFAULT_RECOVERY_MESSAGE = "continue"
MAX_ATTEMPTS = 18


def _skip_retry_backoff():
    """Skip this request's retry delays without changing global sleep."""
    clock = MagicMock(wraps=time)
    clock.sleep = MagicMock(return_value=None)
    return patch("topsailai.ai_base.llm_base.time", clock)


class NullResponseRecoveryScenario:
    """Own one real-HTTP recovery scenario and all of its evidence."""

    def __init__(self, monkeypatch: Any):
        """Initialize isolated configuration and caller-owned messages."""
        self.monkeypatch = monkeypatch
        self.server = None
        self.thread: threading.Thread | None = None
        self.model: LLMModel | None = None
        self.result: str | None = None
        self.error: BaseException | None = None
        self.initial_messages = [
            {"role": "system", "content": "You are a recovery BDD assistant."},
            {"role": "user", "content": DEFAULT_RECOVERY_MESSAGE},
            {"role": "user", "content": "finish the original task"},
        ]
        self.messages = [dict(message) for message in self.initial_messages]
        self.recovery_message = DEFAULT_RECOVERY_MESSAGE
        self._configure_environment()

    def _configure_environment(self) -> None:
        """Configure only the loopback provider and deterministic runtime flags."""
        values = {
            "OPENAI_API_KEY": "bdd-test-key",
            "OPENAI_MODEL": "bdd-null-recovery-model",
            "LLM_RESPONSE_STREAM": "1",
            "TOPSAILAI_LLM_NULL_RESPONSE_RECOVERY_ENABLED": "1",
            "TOPSAILAI_LLM_NULL_RESPONSE_RECOVERY_MESSAGE": "continue",
            "TOPSAILAI_LLM_RESPONSE_EVENTS_ENABLED": "0",
            "TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT": "0",
            "TOPSAILAI_PRINT_TOOL_STAT": "0",
            "TOPSAILAI_INTERACTIVE_MODE": "0",
            "DEBUG": "0",
        }
        for key, value in values.items():
            self.monkeypatch.setenv(key, value)

    def start(
        self,
        responses: tuple[str, ...],
        *,
        stream_errors: tuple[str | None, ...] | None = None,
    ) -> None:
        """Start one request-indexed SSE server on an ephemeral loopback port."""
        config = MockServerConfig(
            port=0,
            request_body_capacity=max(32, len(responses) + 1),
            stream_chunks=(SUCCESS_RESPONSE,),
            stream_response_chunks=tuple((response,) for response in responses),
            stream_error_messages=stream_errors,
        )
        self.server = create_server(config)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        base_url = f"http://{host}:{port}/v1"
        self.monkeypatch.setenv("OPENAI_API_BASE", base_url)
        self.monkeypatch.setenv("OPENAI_BASE_URL", base_url)
        self.model = LLMModel()

    def script_continuous_streak(self) -> None:
        """Return five blank responses before one successful retry."""
        self.start(("", "", "", "", "", SUCCESS_RESPONSE))

    def script_separate_streaks(self) -> None:
        """Separate two three-blank streaks with a provider stream error."""
        responses = ("", "", "", "", "", "", "", SUCCESS_RESPONSE)
        errors = (None, None, None, "provider interrupted this streak", None, None, None, None)
        self.start(responses, stream_errors=errors)

    def script_disabled(self) -> None:
        """Disable recovery while preserving normal blank-response retries."""
        self.monkeypatch.setenv("TOPSAILAI_LLM_NULL_RESPONSE_RECOVERY_ENABLED", "0")
        self.start(("", "", "", "", SUCCESS_RESPONSE))

    def script_configured(self, configured: str) -> None:
        """Use configured content, including blank fallback values."""
        self.monkeypatch.setenv(
            "TOPSAILAI_LLM_NULL_RESPONSE_RECOVERY_MESSAGE", configured
        )
        self.recovery_message = configured if configured.strip() else DEFAULT_RECOVERY_MESSAGE
        self.start(("", "", "", "", SUCCESS_RESPONSE))

    def script_exhaustion(self) -> None:
        """Return blank content for the complete bounded automatic retry cycle."""
        self.start(("",) * MAX_ATTEMPTS)

    def run(self) -> None:
        """Run the production chat path and retain its success or failure."""
        assert self.model is not None
        policy = LLMRetryInteractionPolicy(
            interactive_enabled=False,
            max_manual_retry_cycles=0,
        )
        try:
            with ExitStack() as stack:
                stack.enter_context(_skip_retry_backoff())
                self.result = self.model.chat(
                    self.messages,
                    for_raw=True,
                    for_stream=True,
                    retry_interaction_policy=policy,
                )
        except BaseException as error:  # noqa: BLE001 - BDD asserts exact outcome
            self.error = error

    def state(self) -> dict[str, Any]:
        """Read provider-side request evidence through the debug endpoint."""
        assert self.server is not None
        host, port = self.server.server_address
        with urllib.request.urlopen(
            f"http://{host}:{port}/debug/state", timeout=5
        ) as response:
            return json.load(response)

    def request_messages(self) -> list[list[dict[str, Any]]]:
        """Return every parsed provider-side messages array in request order."""
        records = self.state()["request_bodies"]
        assert all(record["parsed"] for record in records)
        return [record["body"]["messages"] for record in records]

    def temporary_message_count(
        self, request_messages: list[dict[str, Any]], content: str | None = None
    ) -> int:
        """Count messages beyond identical caller-owned content by value and position."""
        expected_content = self.recovery_message if content is None else content
        extras = request_messages[len(self.initial_messages):]
        return sum(
            message == {"role": "user", "content": expected_content}
            for message in extras
        )

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
                raise AssertionError("null-response BDD server thread did not stop")
