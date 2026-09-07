"""Real HTTP/SSE harness for LLM request retry exhaustion BDD."""

from __future__ import annotations

import json
import threading
import urllib.request
from contextlib import ExitStack, nullcontext
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

from topsailai.ai_base.exception import LLMRetryExhaustedError
from topsailai.ai_base.llm_base import LLMModel
from topsailai.ai_base.llm_retry import LLMRetryInteractionPolicy
from topsailai.tests.mock.llm_mock_server import MockServerConfig, create_server
from topsailai.workspace.agent.agent_shell_base import AgentChat

BUSY_RESPONSE = "服务器繁忙，请稍后再试。"
SUCCESS_RESPONSE = "fresh provider response"
MAX_ATTEMPTS = 18
MAX_MANUAL_RETRY_CYCLES = 7
BDD_MAX_MANUAL_RETRY_CYCLES = 2
BDD_MAX_TOTAL_ATTEMPTS = MAX_ATTEMPTS * (BDD_MAX_MANUAL_RETRY_CYCLES + 1)


class _ScenarioComplete(Exception):
    """Stop a continuous-chat BDD scenario after its successful fresh turn."""


@dataclass
class ServerOwner:
    """Own one scenario-local real HTTP server and its exact thread."""

    server: Any
    thread: threading.Thread

    @classmethod
    def start(cls, responses: tuple[str, ...]) -> "ServerOwner":
        """Start a request-indexed SSE server on an ephemeral loopback port."""
        config = MockServerConfig(
            port=0,
            request_body_capacity=max(64, len(responses) + 1),
            stream_chunks=(SUCCESS_RESPONSE,),
            stream_response_chunks=tuple((response,) for response in responses),
        )
        server = create_server(config)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return cls(server=server, thread=thread)

    @property
    def base_url(self) -> str:
        """Return the OpenAI-compatible endpoint for this server."""
        host, port = self.server.server_address
        return f"http://{host}:{port}/v1"

    def state(self) -> dict[str, Any]:
        """Read captured request evidence through the real debug endpoint."""
        host, port = self.server.server_address
        with urllib.request.urlopen(
            f"http://{host}:{port}/debug/state", timeout=5
        ) as response:
            return json.load(response)

    def close(self) -> None:
        """Stop only this server and prove its serving thread has exited."""
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            raise AssertionError("scenario mock-server thread did not stop")


class ScriptedInput:
    """Return scripted retry choices and record every production prompt."""

    def __init__(self, values: list[Any]):
        """Store values or exceptions in call order."""
        self.values = list(values)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        """Return the next value or raise the next scripted exception."""
        self.prompts.append(prompt)
        if not self.values:
            raise AssertionError("unexpected retry prompt")
        value = self.values.pop(0)
        if isinstance(value, BaseException):
            raise value
        return str(value)


class RealTransportAgent:
    """Delegate each Agent turn to one real streaming LLM request pipeline."""

    def __init__(self, model: LLMModel):
        """Expose the minimal AgentChat contract around the real model."""
        self.model = model
        self.agent_type = "react"
        self.agent_name = "bdd-retry-agent"
        self.hooks_after_init_prompt: list[Any] = []
        self.hooks_after_new_session: list[Any] = []
        self.hooks_pre_chat: list[Any] = []
        self.messages: list[dict[str, Any]] = []
        self.run_messages: list[str] = []

    def run(self, step_call: Any, message: str) -> str:
        """Send this fresh User2Agent turn through the real HTTP/SSE client."""
        self.run_messages.append(message)
        request_messages = [
            {"role": "system", "content": "You are a retry BDD assistant."},
            {"role": "user", "content": message},
        ]
        content = self.model.chat(
            request_messages,
            for_raw=True,
            for_stream=True,
            retry_interaction_policy=step_call.llm_retry_policy,
        )
        self.messages = request_messages + [
            {"role": "assistant", "content": content}
        ]
        return content

    def close(self) -> None:
        """Close the real model transport."""
        self.model.close()


class LLMRetryScenario:
    """Own scenario configuration, transport, inputs, and assertions."""

    def __init__(self, monkeypatch: Any):
        """Initialize isolated state; the server starts when scripted."""
        self.monkeypatch = monkeypatch
        self.server_owner: ServerOwner | None = None
        self.model: LLMModel | None = None
        self.input_script: ScriptedInput | None = None
        self.result: str | None = None
        self.error: BaseException | None = None
        self.agent: RealTransportAgent | None = None
        self.back_input_calls = 0
        self.server_thread_stopped = False
        self._configure_environment()

    def _configure_environment(self) -> None:
        """Configure the real client without introducing product variables."""
        values = {
            "OPENAI_API_KEY": "bdd-test-key",
            "OPENAI_MODEL": "bdd-retry-model",
            "LLM_RESPONSE_STREAM": "1",
            "TOPSAILAI_LLM_SPECIAL_RESPONSES_FOR_RETRY": json.dumps(
                [BUSY_RESPONSE], ensure_ascii=False
            ),
            "TOPSAILAI_LLM_RESPONSE_EVENTS_ENABLED": "0",
            "TOPSAILAI_LLM_FIRST_BYTE_TIMEOUT": "0",
            "TOPSAILAI_PRINT_TOOL_STAT": "0",
            "TOPSAILAI_ENABLE_SESSION_LOCK": "0",
            "TOPSAILAI_INTERACTIVE_MODE": "1",
            "TOPSAILAI_NEED_SYMBOL_FOR_ANSWER": "0",
            "DEBUG": "0",
        }
        for key, value in values.items():
            self.monkeypatch.setenv(key, value)

    def start_server(self, responses: tuple[str, ...]) -> None:
        """Start the scenario server and point the production client at it."""
        self.server_owner = ServerOwner.start(responses)
        self.monkeypatch.setenv("OPENAI_API_BASE", self.server_owner.base_url)
        self.monkeypatch.setenv("OPENAI_BASE_URL", self.server_owner.base_url)
        self.model = LLMModel()

    def script_exhaustion_then_success(self) -> None:
        """Return one busy cycle and then one successful SSE response."""
        self.start_server((BUSY_RESPONSE,) * MAX_ATTEMPTS + (SUCCESS_RESPONSE,))

    def script_exhaustion(self) -> None:
        """Return busy content for every request in one bounded cycle."""
        self.start_server((BUSY_RESPONSE,) * MAX_ATTEMPTS)

    def script_total_bound_exhaustion(self) -> None:
        """Return busy content through the injected finite retry budget."""
        self.start_server((BUSY_RESPONSE,) * BDD_MAX_TOTAL_ATTEMPTS)

    def run_direct(
        self,
        choices: list[Any] | None,
        *,
        allow_back: bool = False,
        input_available: bool = True,
        max_manual_retry_cycles: int = MAX_MANUAL_RETRY_CYCLES,
    ) -> None:
        """Run one production LLM chat call over real streaming HTTP/SSE."""
        assert self.model is not None
        self.input_script = ScriptedInput(choices or []) if input_available else None
        policy = LLMRetryInteractionPolicy(
            interactive_enabled=True,
            allow_back_to_chat=allow_back,
            input_func=self.input_script,
            max_manual_retry_cycles=max_manual_retry_cycles,
        )
        messages = [
            {"role": "system", "content": "You are a retry BDD assistant."},
            {"role": "user", "content": "original request"},
        ]
        try:
            with patch("topsailai.ai_base.llm_base.time.sleep", return_value=None):
                self.result = self.model.chat(
                    messages,
                    for_raw=True,
                    for_stream=True,
                    retry_interaction_policy=policy,
                )
        except BaseException as error:  # noqa: BLE001 - scenarios assert control signals
            self.error = error

    def run_back_to_fresh_message(self) -> None:
        """Drive Back through AgentChat, then send a new turn over real SSE.

        LLM Retry remains inside ``LLMModel.chat()`` and resends identical
        messages. Back is different: AgentChat abandons that turn and asks for
        a fresh User2Agent message before another ``ai_agent.run()`` occurs.
        """
        assert self.model is not None
        self.input_script = ScriptedInput(["invalid", "back"])
        self.agent = RealTransportAgent(self.model)
        hook_instruction = MagicMock()
        ctx_rt_aiagent = MagicMock()
        ctx_rt_instruction = MagicMock()
        ctx_runtime_data = MagicMock()
        ctx_runtime_data.session_id = "bdd-retry-session"
        ctx_runtime_data.session_data = None
        ctx_rt_aiagent.ai_agent = self.agent
        ctx_rt_aiagent.ctx_runtime_data = ctx_runtime_data
        fresh_inputs = ["   ", "continue", "fresh request"]

        def next_message(*, hook: Any) -> str:
            """Supply blank, formatted-empty, and then fresh User2Agent input."""
            self.back_input_calls += 1
            return fresh_inputs.pop(0)

        try:
            with ExitStack() as stack:
                stack.enter_context(patch(
                    "topsailai.workspace.agent.hooks.base.init.get_hooks",
                    return_value=[],
                ))
                stack.enter_context(patch(
                    "topsailai.workspace.agent.agent_chat_base.set_ai_agent"
                ))
                chat = AgentChat(hook_instruction, ctx_rt_aiagent, ctx_rt_instruction)
                chat._start_control_server = MagicMock()
                chat.call_hooks_pre_run = MagicMock()
                chat.call_hooks_post_fail_run = MagicMock()
                chat.call_hooks_post_succ_run = MagicMock(side_effect=_ScenarioComplete)
                chat.call_hook_for_final_answer = MagicMock()
                chat.hook_for_answer = MagicMock()
                chat.hook_build_answer = MagicMock(side_effect=lambda answer, **_: answer)
                stack.enter_context(patch(
                    "topsailai.workspace.agent.agent_shell_base.get_agent_runtime_input",
                    return_value=self.input_script,
                ))
                stack.enter_context(patch(
                    "topsailai.workspace.agent.agent_shell_base.input_message",
                    side_effect=next_message,
                ))
                stack.enter_context(patch(
                    "topsailai.workspace.agent.agent_shell_base.task_tool.ctxm_process_task",
                    side_effect=lambda _task: nullcontext(),
                ))
                stack.enter_context(patch(
                    "topsailai.workspace.agent.agent_shell_base.lock_tool.ctxm_void",
                    side_effect=lambda **_: nullcontext({}),
                ))
                stack.enter_context(patch(
                    "topsailai.workspace.agent.agent_shell_base.terminal_title.refresh_terminal_title"
                ))
                stack.enter_context(patch(
                    "topsailai.ai_base.llm_base.time.sleep", return_value=None
                ))
                try:
                    chat._run(
                        message="old request",
                        times=0,
                        need_interactive=True,
                        need_confirm_abort=False,
                    )
                except _ScenarioComplete:
                    self.result = chat.last_message
        except BaseException as error:  # noqa: BLE001 - scenario asserts exact outcome
            self.error = error

    def state(self) -> dict[str, Any]:
        """Return current provider-side request evidence."""
        assert self.server_owner is not None
        return self.server_owner.state()

    def request_bodies(self) -> list[dict[str, Any]]:
        """Return captured parsed OpenAI request bodies."""
        return [record["body"] for record in self.state()["request_bodies"]]

    def close(self) -> None:
        """Close model clients and the exact scenario server/thread."""
        if self.model is not None:
            self.model.close()
        if self.server_owner is not None:
            self.server_owner.close()
            self.server_thread_stopped = not self.server_owner.thread.is_alive()
