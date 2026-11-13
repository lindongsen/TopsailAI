"""Extended harness for event sources that need extra configuration.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-13
Purpose: Drive event sources that the base harness leaves disabled by default
"""

from __future__ import annotations

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
        **kwargs: Any,
    ) -> None:
        """Apply the extra switches after the base harness has started."""
        super().__init__(monkeypatch, directory, **kwargs)
        self.recording_agent: _RecordingAgent | None = None
        self.thought_matched: bool | None = None
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
        for key, value in values.items():
            monkeypatch.setenv(key, value)
        reset_event_collector()

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
