"""Deterministic harness for hard-interrupt behavior in LLM chat retries."""

from __future__ import annotations

from unittest.mock import MagicMock

import openai

from topsailai.ai_base.exception import HardInterruptError
from topsailai.ai_base.llm_base import LLMModel


class HardInterruptHarness:
    """Drive the real LLMModel.chat path with controlled provider behavior."""

    def __init__(self, monkeypatch) -> None:
        """Create an isolated model, agent, and retry prompt for one scenario."""
        import topsailai.ai_base.llm_base as llm_module

        self.monkeypatch = monkeypatch
        self.llm_module = llm_module
        self.messages = [{"role": "user", "content": "BDD hard interrupt"}]
        self.retry_prompt = MagicMock(return_value=True)
        self.agent = MagicMock()
        self.error: BaseException | None = None

        monkeypatch.setattr(llm_module.LLMModelBase, "__init__", lambda _: None)
        monkeypatch.setattr(llm_module, "get_agent_object", lambda: self.agent)
        monkeypatch.setattr(llm_module, "input_yes_or_no", self.retry_prompt)
        monkeypatch.setattr(llm_module.thread_tool, "is_main_thread", lambda: True)

        self.model = self._create_model()

    def _create_model(self) -> LLMModel:
        """Create an LLM model with the minimal runtime state used by chat()."""
        model = LLMModel()
        model.models = []
        model.model = MagicMock()
        model.tokenStat = MagicMock()
        model.model_config = {"api_key": "bdd-test-key"}
        model.model_name = "bdd-test-model"
        model.temperature = 0.0
        model.max_tokens = 128
        model.top_p = 1.0
        model.frequency_penalty = 0.0
        model.content_senders = []
        model.hooks = {}
        return model

    def set_retry_answer(self, answer: str) -> None:
        """Set the answer that would be returned if a retry prompt appeared."""
        self.retry_prompt.return_value = answer == "yes"

    def arrange_stream_interrupt(self) -> None:
        """Arrange an interrupt after the first streaming chunk is received."""
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = "interrupted"
        chunk.choices[0].delta.tool_calls = None
        self.model.model.create.return_value = iter([chunk])
        self.agent._check_hard_interrupt.side_effect = [
            None,
            HardInterruptError("stream interrupted"),
        ]

    def arrange_retry_loop_interrupt(self) -> None:
        """Arrange one retryable failure followed by a retry-top interrupt."""
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].message.content = "not returned"
        self.model.model.create.return_value = response
        self.agent._check_hard_interrupt.side_effect = [
            None,
            HardInterruptError("retry interrupted"),
        ]
        self.monkeypatch.setattr(
            self.llm_module,
            "format_response",
            MagicMock(side_effect=openai.APIConnectionError(request=MagicMock())),
        )

    def execute_streaming_chat(self) -> None:
        """Execute streaming chat and retain the exception for BDD assertions."""
        self._capture(
            lambda: self.model.chat(self.messages, for_raw=True, for_stream=True)
        )

    def execute_non_streaming_chat(self) -> None:
        """Execute non-streaming chat and retain the exception for assertions."""
        self._capture(lambda: self.model.chat(self.messages))

    def _capture(self, operation) -> None:
        """Capture the control-flow exception without hiding unexpected success."""
        try:
            operation()
        except BaseException as error:
            self.error = error

    @property
    def request_count(self) -> int:
        """Return how many provider requests the scenario issued."""
        return self.model.model.create.call_count
