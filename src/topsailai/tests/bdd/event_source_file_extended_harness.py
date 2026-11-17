"""Extended harness for event sources that need extra configuration.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-13
Purpose: Drive event sources that the base harness leaves disabled by default
"""

from __future__ import annotations

import sys
from typing import Any

from tests.bdd.event_source_file_harness import EventSourceFileHarness
from topsailai.events import reset_event_collector


class _RecordingAgent:
    """Minimal agent that records injected observations instead of writing files."""

    def __init__(self) -> None:
        """Create an agent that keeps injections in memory."""
        self.agent_role = "worker"
        self.runtime = None
        self.messages: list[Any] = []
        self.injected: list[Any] = []

    def add_user_message(self, content: Any, need_print: bool = False) -> None:
        """Record one injected observation without touching the real context."""
        self.injected.append(content)


class ExtendedEventSourceHarness(EventSourceFileHarness):
    """Base harness plus the switches the remaining event sources need.
    The base harness deliberately disables raw response events and leaves the
    warning features unconfigured. This subclass keeps that default intact for
    the original scenarios and only turns on what a scenario asks for.
    """

    def __init__(
        self,
        monkeypatch: Any,
        directory,
        *,
        response_events_enabled: bool = False,
        tool_warning_rules: str = "",
        thought_pattern_enabled: bool = False,
        thought_pattern_rules: str = "",
        summary_events_enabled: bool = False,
        **kwargs: Any,
    ) -> None:
        """Apply the extra switches after the base harness has started."""
        super().__init__(monkeypatch, directory, **kwargs)
        self.recording_agent: _RecordingAgent | None = None
        self.thought_matched: bool | None = None
        self.summary_result: str | None = None
        self.summary_chat = None
        values = {
            "TOPSAILAI_LLM_RESPONSE_EVENTS_ENABLED": (
                "1" if response_events_enabled else "0"
            ),
            "TOPSAILAI_LLM_RESPONSE_EVENTS_INCLUDE_RAW": "0",
            "TOPSAILAI_TOOL_CALL_WARNING_RULES": tool_warning_rules,
            "TOPSAILAI_THOUGHT_LINE_PATTERN_ENABLED": (
                "1" if thought_pattern_enabled else "0"
            ),
            "TOPSAILAI_THOUGHT_LINE_PATTERN_RULES": thought_pattern_rules,
        }
        if summary_events_enabled:
            values.update(self._summary_values())
        for key, value in values.items():
            monkeypatch.setenv(key, value)
        reset_event_collector()

    @staticmethod
    def _summary_values() -> dict[str, str]:
        """Return the switches a real summary cycle needs.

        The summary path always streams, so the provider must be able to
        answer a streaming request; the base harness only does that when the
        scenario supplies chunks. Every keep-offset and token reserve is
        zeroed so the rebuilt context is predictable, and the model context
        ceiling is zero so the quantity trigger cannot block the cycle.
        """
        return {
            "TOPSAILAI_CONTEXT_SUMMARY_MODE": "runtime",
            "TOPSAILAI_CONTEXT_SUMMARY_PROCESSOR": "agent_llm_model",
            "TOPSAILAI_MODEL_MAX_CONTEXT_DEFAULT": "0",
            "TOPSAILAI_CTX_SUMMARY_KEEP_FIRST_TASK_MESSAGE": "0",
            "TOPSAILAI_CTX_SUMMARY_KEEP_SESSION_MESSAGES": "0",
            "TOPSAILAI_CONTEXT_MESSAGES_HEAD_OFFSET_TO_KEEP": "0",
            "TOPSAILAI_CONTEXT_MESSAGES_TAIL_OFFSET_TO_KEEP": "0",
            "TOPSAILAI_AGENT2LLM_SUMMARY_TOKEN_RESERVE": "0",
            "TOPSAILAI_USER2AGENT_SUMMARY_TOKEN_RESERVE": "0",
            "TOPSAILAI_USE_TOOL_CALLS": "0",
            "TOPSAILAI_DISABLED_TOOLS": "*",
            "TOPSAILAI_DISABLED_SKILLS": "*",
            "TOPSAILAI_ENABLE_SESSION_TEE_OUT": "0",
            "TOPSAILAI_TERMINAL_TITLE_ENABLED": "0",
            "TOPSAILAI_AUTO_SESSION_NAME_ENABLED": "0",
            "TOPSAILAI_AGENT2LLM_INJECT_MESSAGE_ENABLED": "0",
        }

    def run_summary(self) -> None:
        """Drive one real User2Agent summary cycle through the real Hook Points."""
        from topsailai.workspace import agent_shell

        task_root = self.directory / "task"
        task_root.mkdir(exist_ok=True)
        for name, module in tuple(sys.modules.items()):
            if name.startswith("topsailai.") and hasattr(
                module, "FOLDER_WORKSPACE_TASK"
            ):
                self.monkeypatch.setattr(
                    module, "FOLDER_WORKSPACE_TASK", str(task_root), raising=False
                )
        self.monkeypatch.setattr(
            agent_shell, "get_message", lambda *a, **k: "", raising=False
        )
        chat = agent_shell.get_agent_chat(
            system_prompt="bdd summary observation",
            agent_name="BDDSUMMARY",
            session_id="",
            message="",
            tool_map={},
            need_input_message=False,
            need_print_session=False,
            need_set_agent_name_to_thread_local=False,
            need_project_workspace_lock=False,
        )
        self.summary_chat = chat
        runtime = chat.ctx_runtime_data
        messages = [
            {"role": "user", "content": "bdd summary context task"},
            {"role": "assistant", "content": "bdd summary context details " * 100},
            {"role": "user", "content": "bdd latest user request"},
        ]
        runtime.messages = list(messages)
        runtime.ai_agent.messages = list(messages)
        self.summary_result = runtime.summarize_messages_for_processed(force=True)

    def execute_tool_repeatedly(self, times: int = 2) -> None:
        """Run the same real tool call several times under one scenario agent."""
        from topsailai.ai_base.agent_types.tool import exec_tool_func
        from topsailai.utils.thread_local_tool import ctxm_set_agent

        def _bdd_tool(path: str = "") -> str:
            """Return a marker so the recorded result is predictable."""
            return f"read {path}"

        agent = _RecordingAgent()
        with ctxm_set_agent(agent):
            for _ in range(times):
                exec_tool_func(
                    _bdd_tool, {"path": self.tool_argument}, tool_name="bdd_tool"
                )
        self.recording_agent = agent

    def close(self) -> None:
        """Close the scenario's summary chat before the base harness resources."""
        chat = self.summary_chat
        self.summary_chat = None
        if chat is not None:
            chat.ai_agent.close()
        super().close()

    def evaluate_thought(self, text: str) -> None:
        """Run the real thought line-pattern evaluation under a scenario agent."""
        from topsailai.context import thought_line_pattern
        from topsailai.utils.thread_local_tool import ctxm_set_agent

        agent = _RecordingAgent()
        with ctxm_set_agent(agent):
            self.thought_matched = thought_line_pattern.evaluate_and_maybe_inject(
                text, step_type="thought"
            )
        self.recording_agent = agent
