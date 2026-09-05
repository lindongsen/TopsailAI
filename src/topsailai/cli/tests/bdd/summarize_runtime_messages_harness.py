"""Real-HTTP harness for Agent2LLM runtime summary input fidelity."""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import threading
from typing import Any

from topsailai.ai_base.llm_base import LLMModel
from topsailai.tests.mock.llm_mock_server import MockServerConfig, create_server
from topsailai.workspace.context.agent2llm import ContextRuntimeAgent2LLM


class _HarnessAgent:
    """Provide the Agent2LLM contract required by context summarization."""

    def __init__(self, model: LLMModel, messages: list[dict[str, Any]]):
        """Attach a real model and mutable runtime messages."""
        self.llm_model = model
        self.messages = list(messages)
        self.agent_type = "react"

    @staticmethod
    def get_work_memory_first_position() -> int:
        """Exclude the leading system message from wrapper working memory."""
        return 1


class _WarningCapture(logging.Handler):
    """Capture warning-or-higher records emitted during summarization."""

    def __init__(self) -> None:
        """Initialize an empty warning record list."""
        super().__init__(level=logging.WARNING)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        """Retain one warning record without changing production logging."""
        self.records.append(record)


class _TrackedContextRuntimeAgent2LLM(ContextRuntimeAgent2LLM):
    """Expose the production-created summary chat for exact test cleanup."""

    def __init__(self) -> None:
        """Initialize runtime state and an empty summary-chat reference."""
        super().__init__()
        self.summary_chat = None

    def _summarize_runtime_messages(self, messages, prompt=None, extra_prompt=None):
        """Delegate production summarization and retain its owned chat object."""
        result = super()._summarize_runtime_messages(
            messages,
            prompt=prompt,
            extra_prompt=extra_prompt,
        )
        self.summary_chat = result[0]
        return result


class SummarizeRuntimeMessagesHarness:
    """Drive runtime summarization through the real OpenAI HTTP client."""

    def __init__(self, monkeypatch) -> None:
        """Start one loopback mock server and configure runtime summary mode."""
        self.server = create_server(MockServerConfig(
            port=0,
            stream_chunks=("Mock runtime summary",),
        ))
        self.server_thread = threading.Thread(
            target=self.server.serve_forever,
            name="bdd-runtime-summary-llm-mock-server",
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
        monkeypatch.setenv("TOPSAILAI_CONTEXT_SUMMARY_MODE", "runtime")
        monkeypatch.setenv("TOPSAILAI_CTX_SUMMARY_KEEP_SESSION_MESSAGES", "0")
        monkeypatch.setenv("TOPSAILAI_CONTEXT_MESSAGES_HEAD_OFFSET_TO_KEEP", "0")
        monkeypatch.setenv("TOPSAILAI_CONTEXT_MESSAGES_TAIL_OFFSET_TO_KEEP", "0")
        monkeypatch.setenv("TOPSAILAI_MODEL_MAX_CONTEXT_DEFAULT", "0")
        self.model = LLMModel()
        self.runtime_messages = [
            {"role": "system", "content": "BDD runtime-only system context"},
            {
                "role": "user",
                "content": {"step_name": "task", "raw_text": "summarize runtime context"},
            },
            {"role": "assistant", "content": "runtime analysis α"},
            {"role": "user", "content": "runtime follow-up β"},
        ]
        self.session_messages = [
            {"role": "user", "content": "distinct persisted User2Agent message"}
        ]
        self.agent = _HarnessAgent(self.model, self.runtime_messages)
        self.runtime = _TrackedContextRuntimeAgent2LLM()
        self.runtime.ai_agent = self.agent
        self.runtime.session_id = "bdd-runtime-summary-session"
        self.runtime.messages = copy.deepcopy(self.session_messages)
        self.pre_summary_messages: list[dict[str, Any]] = []
        self.pre_summary_hash = ""
        self.transmitted_prefix_hash = ""
        self.transmitted_messages: list[dict[str, Any]] = []
        self.warning_messages: list[str] = []
        self.answer: str | None = None

    @staticmethod
    def messages_hash(messages: list[dict[str, Any]]) -> str:
        """Return SHA-256 over canonical UTF-8 JSON for a message sequence."""
        serialized = json.dumps(
            messages,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def summarize(self) -> None:
        """Capture the runtime sequence and execute production summarization."""
        self.pre_summary_messages = copy.deepcopy(self.agent.messages)
        self.pre_summary_hash = self.messages_hash(self.pre_summary_messages)
        warning_capture = _WarningCapture()
        root_logger = logging.getLogger()
        root_logger.addHandler(warning_capture)
        try:
            self.answer = self.runtime.summarize_messages_for_processing(force=True)
        finally:
            root_logger.removeHandler(warning_capture)
        self.warning_messages = [record.getMessage() for record in warning_capture.records]

        state = self.server.request_body_capture.state()
        records = state["request_bodies"]
        assert records and records[-1]["parsed"], records
        self.transmitted_messages = records[-1]["body"]["messages"]
        self.transmitted_prefix_hash = self.messages_hash(self.transmitted_messages[:-1])

    @property
    def request_count(self) -> int:
        """Return the number of valid summary requests observed by the server."""
        return self.server.prompt_cache.state()["total_requests"]

    def close(self) -> None:
        """Close both models, the server socket, and the owned server thread."""
        if self.runtime.summary_chat is not None:
            self.runtime.summary_chat.close()
        self.model.close()
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=2)
        assert not self.server_thread.is_alive(), "runtime summary mock server did not stop"
