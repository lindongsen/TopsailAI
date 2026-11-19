"""Real HTTP/SSE harness for severe-repetition turn recovery BDD."""

from contextlib import ExitStack, nullcontext
from typing import Any
from unittest.mock import MagicMock, patch

from topsailai.ai_base.llm_control.exception import LLMSevereRepetitionError
from topsailai.workspace.agent.agent_shell_base import AgentChat
from tests.bdd.llm_retry_exhaustion_harness import (
    LLMRetryScenario,
    RealTransportAgent,
    ScriptedInput,
    SUCCESS_RESPONSE,
    _ScenarioComplete,
    _skip_retry_backoff,
)

REPETITIVE_RESPONSE = (
    "<result>\n"
    "<name>file_tool-write_file</name>\n"
    "<output>OK</output>\n"
    "</result>\n"
) * 20


class SevereRepetitionScenario(LLMRetryScenario):
    """Drive severe repetition through the production HTTP and AgentChat paths."""

    def __init__(self, monkeypatch: Any):
        """Initialize isolated scenario state and enable repetition refusal."""
        super().__init__(monkeypatch)
        monkeypatch.setenv("TOPSAILAI_MAX_COMPLETION_TOKENS", "1")
        monkeypatch.setenv("TOPSAILAI_REFUSE_SEVERE_REPETITION", "1")
        monkeypatch.setenv("TOPSAILAI_SEVERE_REPETITION_MAX_CONSECUTIVE", "2")
        self.fresh_input_calls = 0
        self.failure_hook_calls = 0

    def script_interactive_recovery(self) -> None:
        """Return two verdict-producing responses and one fresh completion."""
        self.start_server(
            (REPETITIVE_RESPONSE, REPETITIVE_RESPONSE, SUCCESS_RESPONSE)
        )

    def script_non_interactive_failure(self) -> None:
        """Return only the two responses needed for the specialized verdict."""
        self.start_server((REPETITIVE_RESPONSE, REPETITIVE_RESPONSE))

    def run_interactive_recovery(self) -> None:
        """Abandon the repetitive turn and complete one fresh interactive turn."""
        assert self.model is not None
        self.input_script = ScriptedInput([])
        self.agent = RealTransportAgent(self.model)
        chat = self._build_chat("bdd-severe-repetition-session")
        fresh_inputs = ["fresh request"]

        def next_message(*, hook: Any) -> str:
            """Return the next User2Agent message after the failed turn."""
            self.fresh_input_calls += 1
            return fresh_inputs.pop(0)

        try:
            with self._run_context(chat, next_message=next_message):
                try:
                    chat._run(
                        message="old request",
                        times=1,
                        need_interactive=True,
                        need_confirm_abort=False,
                    )
                except _ScenarioComplete:
                    self.result = chat.last_message
            self.failure_hook_calls = chat.call_hooks_post_fail_run.call_count
        except BaseException as error:  # noqa: BLE001 - scenario asserts outcome
            self.error = error

    def run_non_interactive_failure(self) -> None:
        """Exercise the unchanged non-interactive fail-fast boundary."""
        assert self.model is not None
        self.input_script = ScriptedInput([])
        self.agent = RealTransportAgent(self.model)
        chat = self._build_chat("bdd-severe-repetition-fatal-session")

        try:
            with self._run_context(chat):
                chat._run(
                    message="old request",
                    times=1,
                    need_interactive=False,
                    need_confirm_abort=False,
                )
        except BaseException as error:  # noqa: BLE001 - scenario asserts outcome
            self.error = error

    def _build_chat(self, session_id: str) -> AgentChat:
        """Build the minimal production AgentChat boundary for this scenario."""
        hook_instruction = MagicMock()
        ctx_rt_aiagent = MagicMock()
        ctx_rt_instruction = MagicMock()
        ctx_runtime_data = MagicMock()
        ctx_runtime_data.session_id = session_id
        ctx_runtime_data.session_data = None
        ctx_rt_aiagent.ai_agent = self.agent
        ctx_rt_aiagent.ctx_runtime_data = ctx_runtime_data
        chat = AgentChat(hook_instruction, ctx_rt_aiagent, ctx_rt_instruction)
        chat._start_control_server = MagicMock()
        chat.call_hooks_pre_run = MagicMock()
        chat.call_hooks_post_fail_run = MagicMock()
        chat.call_hooks_post_succ_run = MagicMock(side_effect=_ScenarioComplete)
        chat.call_hook_for_final_answer = MagicMock()
        chat.hook_for_answer = MagicMock()
        chat.hook_build_answer = MagicMock(side_effect=lambda answer, **_: answer)
        return chat

    def _run_context(self, chat: AgentChat, *, next_message: Any = None) -> ExitStack:
        """Return patches that isolate infrastructure while retaining business flow."""
        stack = ExitStack()
        stack.enter_context(patch(
            "topsailai.workspace.agent.hooks.base.init.get_hooks",
            return_value=[],
        ))
        stack.enter_context(patch(
            "topsailai.workspace.agent.agent_chat_base.set_ai_agent"
        ))
        stack.enter_context(patch(
            "topsailai.workspace.agent.agent_shell_base.get_agent_runtime_input",
            return_value=self.input_script,
        ))
        if next_message is not None:
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
        stack.enter_context(_skip_retry_backoff())
        return stack

    def assert_specialized_error(self) -> LLMSevereRepetitionError:
        """Return the expected specialized error or fail with its actual shape."""
        assert isinstance(self.error, LLMSevereRepetitionError), repr(self.error)
        return self.error
