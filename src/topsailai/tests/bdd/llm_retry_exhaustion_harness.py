"""Real HTTP/SSE harness for LLM request retry exhaustion BDD."""

from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from contextlib import ExitStack, nullcontext
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

from topsailai.ai_base.exception import LLMRetryExhaustedError
from topsailai.ai_base.llm_base import LLMModel
from topsailai.ai_base.llm_control.llm_retry import LLMRetryInteractionPolicy
from topsailai.tests.mock.llm_mock_server import MockServerConfig, create_server
from topsailai.utils.env_tool import resolve_python_interpreter
from topsailai.workspace.agent.agent_shell_base import AgentChat

BUSY_RESPONSE = "服务器繁忙，请稍后再试。"
SUCCESS_RESPONSE = "fresh provider response"
MAX_ATTEMPTS = 18
MAX_MANUAL_RETRY_CYCLES = 7
BDD_MAX_MANUAL_RETRY_CYCLES = 2
BDD_MAX_TOTAL_ATTEMPTS = MAX_ATTEMPTS * (BDD_MAX_MANUAL_RETRY_CYCLES + 1)
SIGINT_RETRY_MENU_READY = "BDD_SIGINT_RETRY_MENU_READY"
SIGINT_CHILD_RESULT = "BDD_SIGINT_CHILD_RESULT="


class _ScenarioComplete(Exception):
    """Stop a continuous-chat BDD scenario after its successful fresh turn."""


@dataclass
class ServerOwner:
    """Own one scenario-local real HTTP server and its exact thread."""

    server: Any
    thread: threading.Thread

    @classmethod
    def start(
        cls,
        responses: tuple[str, ...],
        stream_errors: tuple[str | None, ...] | None = None,
    ) -> "ServerOwner":
        """Start a request-indexed SSE server on an ephemeral loopback port."""
        config = MockServerConfig(
            port=0,
            request_body_capacity=max(64, len(responses) + 1),
            stream_chunks=(SUCCESS_RESPONSE,),
            stream_response_chunks=tuple((response,) for response in responses),
            stream_error_messages=stream_errors,
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
        self.boundary_manual_cycles: int | None = None
        self.boundary_total_attempts: int | None = None
        self.child_process: subprocess.Popen[str] | None = None
        self.child_stdout = ""
        self.child_stderr = ""
        self.child_result: dict[str, Any] | None = None
        self.child_returncode: int | None = None
        self.child_reaped = False
        self.child_pipes_closed = False
        self.sigint_server_state: dict[str, Any] | None = None
        self.sigint_server_closed = False
        self.sigint_server_socket_closed = False
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

    def start_server(
        self,
        responses: tuple[str, ...],
        stream_errors: tuple[str | None, ...] | None = None,
    ) -> None:
        """Start the scenario server and point the production client at it."""
        self.server_owner = ServerOwner.start(responses, stream_errors)
        self.monkeypatch.setenv("OPENAI_API_BASE", self.server_owner.base_url)
        self.monkeypatch.setenv("OPENAI_BASE_URL", self.server_owner.base_url)
        self.model = LLMModel()

    def script_exhaustion_then_success(self) -> None:
        """Return one busy cycle and then one successful SSE response."""
        self.start_server((BUSY_RESPONSE,) * MAX_ATTEMPTS + (SUCCESS_RESPONSE,))

    def script_litellm_connection_error_then_success(self) -> None:
        """Return one LiteLLM SSE connection error followed by a completion."""
        self.start_server(
            (SUCCESS_RESPONSE, SUCCESS_RESPONSE),
            (
                "litellm.APIConnectionError: APIConnectionError: "
                "OpenAIException - 服务器繁忙，请稍后再试。",
                None,
            ),
        )

    def script_litellm_connection_error_exhaustion(self) -> None:
        """Return a LiteLLM SSE connection error for one automatic cycle."""
        message = (
            "litellm.APIConnectionError: APIConnectionError: "
            "OpenAIException - 服务器繁忙，请稍后再试。"
        )
        self.start_server(
            (SUCCESS_RESPONSE,) * MAX_ATTEMPTS,
            (message,) * MAX_ATTEMPTS,
        )

    def script_exhaustion(self) -> None:
        """Return busy content for every request in one bounded cycle."""
        self.start_server((BUSY_RESPONSE,) * MAX_ATTEMPTS)

    def script_total_bound_exhaustion(self) -> None:
        """Return busy content through the injected finite retry budget."""
        self.start_server((BUSY_RESPONSE,) * BDD_MAX_TOTAL_ATTEMPTS)

    def script_default_boundary_exhaustion(self) -> None:
        """Return busy content through the production default retry budget."""
        self.boundary_manual_cycles = MAX_MANUAL_RETRY_CYCLES
        self.boundary_total_attempts = MAX_ATTEMPTS * (MAX_MANUAL_RETRY_CYCLES + 1)
        self.start_server((BUSY_RESPONSE,) * self.boundary_total_attempts)

    def script_configured_boundary(
        self,
        manual_cycles: int,
        *,
        succeeds_on_final_attempt: bool = False,
    ) -> None:
        """Script one injected retry policy through its final permitted request."""
        total_attempts = MAX_ATTEMPTS * (manual_cycles + 1)
        responses = [BUSY_RESPONSE] * total_attempts
        if succeeds_on_final_attempt:
            responses[-1] = SUCCESS_RESPONSE
        self.boundary_manual_cycles = manual_cycles
        self.boundary_total_attempts = total_attempts
        self.start_server(tuple(responses))

    def run_configured_boundary(self) -> None:
        """Exercise the scripted policy using every configured Retry choice."""
        assert self.boundary_manual_cycles is not None
        self.run_direct(
            ["1"] * self.boundary_manual_cycles,
            max_manual_retry_cycles=self.boundary_manual_cycles,
        )

    def run_default_boundary(self) -> None:
        """Exercise every cycle from an unmodified production-default policy."""
        assert self.model is not None
        self.input_script = ScriptedInput(["1"] * MAX_MANUAL_RETRY_CYCLES)
        policy = LLMRetryInteractionPolicy(
            interactive_enabled=True,
            input_func=self.input_script,
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
        except BaseException as error:  # noqa: BLE001 - scenario asserts control signals
            self.error = error

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

    def run_subprocess_sigint_at_retry_menu(self) -> None:
        """Deliver SIGINT to an exact child blocked in the real Retry menu."""
        assert os.name == "posix"
        owner = ServerOwner.start((BUSY_RESPONSE,) * MAX_ATTEMPTS)
        self.server_owner = owner
        environment = os.environ.copy()
        environment.update({
            "OPENAI_API_KEY": "bdd-test-key",
            "OPENAI_MODEL": "bdd-retry-model",
            "OPENAI_API_BASE": owner.base_url,
            "OPENAI_BASE_URL": owner.base_url,
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
        })
        process = subprocess.Popen(
            [resolve_python_interpreter(), os.path.abspath(__file__), "--sigint-child"],
            cwd=os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            ),
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.child_process = process
        output_chunks: list[str] = []
        try:
            assert process.stdout is not None
            deadline = time.monotonic() + 15
            marker_seen = False
            while time.monotonic() < deadline:
                ready, _, _ = select.select([process.stdout], [], [], 0.2)
                if not ready:
                    if process.poll() is not None:
                        break
                    continue
                chunk = os.read(process.stdout.fileno(), 4096).decode(
                    errors="replace"
                )
                if not chunk:
                    break
                output_chunks.append(chunk)
                if SIGINT_RETRY_MENU_READY in "".join(output_chunks):
                    marker_seen = True
                    break
            if not marker_seen:
                if process.poll() is not None:
                    remaining_stdout, self.child_stderr = process.communicate(timeout=5)
                    self.child_stdout = "".join(output_chunks) + remaining_stdout
                    self.child_returncode = process.returncode
                    self.child_reaped = process.poll() is not None
                    raise AssertionError(
                        "child exited before reaching the Retry menu: "
                        f"{self.child_stderr.strip()}"
                    )
                raise AssertionError("child did not reach the Retry menu readiness marker")

            os.kill(process.pid, signal.SIGINT)
            remaining_stdout, self.child_stderr = process.communicate(timeout=10)
            self.child_stdout = "".join(output_chunks) + remaining_stdout
            self.child_returncode = process.returncode
            self.child_reaped = process.poll() is not None
        except BaseException:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            raise
        finally:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()
            self.child_pipes_closed = all(
                stream is None or stream.closed
                for stream in (process.stdin, process.stdout, process.stderr)
            )
            self.sigint_server_state = owner.state()
            owner.close()
            self.sigint_server_closed = not owner.thread.is_alive()
            self.sigint_server_socket_closed = owner.server.socket.fileno() == -1
            self.server_owner = None

        result_lines = [
            line for line in self.child_stdout.splitlines()
            if line.startswith(SIGINT_CHILD_RESULT)
        ]
        if len(result_lines) == 1:
            self.child_result = json.loads(result_lines[0][len(SIGINT_CHILD_RESULT):])

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


def _run_sigint_retry_menu_child() -> int:
    """Run the real Agent/HTTP retry path until the parent delivers SIGINT."""
    model = LLMModel()
    agent = RealTransportAgent(model)
    hook_instruction = MagicMock()
    ctx_rt_aiagent = MagicMock()
    ctx_rt_instruction = MagicMock()
    ctx_runtime_data = MagicMock()
    ctx_runtime_data.session_id = "bdd-sigint-child"
    ctx_runtime_data.session_data = None
    ctx_rt_aiagent.ai_agent = agent
    ctx_rt_aiagent.ctx_runtime_data = ctx_runtime_data

    def retry_menu_input(prompt: str) -> str:
        """Expose readiness only after production requests the Retry action."""
        if "LLM retry attempts exhausted." not in prompt:
            raise AssertionError(f"unexpected runtime input prompt: {prompt}")
        print(SIGINT_RETRY_MENU_READY, flush=True)
        return input()

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
            chat.call_hooks_post_succ_run = MagicMock()
            chat.call_hook_for_final_answer = MagicMock()
            chat.hook_for_answer = MagicMock()
            chat.hook_build_answer = MagicMock(side_effect=lambda answer, **_: answer)
            stack.enter_context(patch(
                "topsailai.workspace.agent.agent_shell_base.get_agent_runtime_input",
                return_value=retry_menu_input,
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
            answer = None
            error_result = None
            try:
                answer = chat._run(
                    message="original request",
                    times=0,
                    need_interactive=True,
                    need_confirm_abort=False,
                )
            except LLMRetryExhaustedError as error:
                error_result = {
                    "type": type(error).__name__,
                    "attempts": error.attempts,
                    "manual_cycle_count": error.manual_cycle_count,
                }
            result = {
                "answer": answer,
                "error": error_result,
                "run_messages": agent.run_messages,
                "fail_hooks": chat.call_hooks_post_fail_run.call_count,
                "success_hooks": chat.call_hooks_post_succ_run.call_count,
                "final_hooks": chat.call_hook_for_final_answer.call_count,
            }
            print(SIGINT_CHILD_RESULT + json.dumps(result), flush=True)
            return 0
    finally:
        model.close()


if __name__ == "__main__" and sys.argv[1:] == ["--sigint-child"]:
    raise SystemExit(_run_sigint_retry_menu_child())
