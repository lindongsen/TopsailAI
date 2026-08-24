"""Unit tests for per-response story-memory reference accounting."""

import os
from unittest import TestCase
from unittest.mock import patch

from topsailai.ai_base.agent_base import AgentRun
from topsailai.ai_base.tool_call import StepCallBase


class TestAgentRunMemoryReferences(TestCase):
    """Verify guarded citation accounting at the LLM-response boundary."""

    def setUp(self):
        """Create an AgentRun instance without initializing unrelated services."""
        self.agent = object.__new__(AgentRun)
        self.response = [
            {"step_name": "thought", "raw_text": "Use @memory[Known.md]."},
            {"step_name": "final_answer", "raw_text": "Again @memory[ known.MD ]."},
        ]

    @patch("topsailai.tools.memory_tool_utils.memory_stat.record_memory_event")
    @patch("topsailai.tools.story_memory_tool.list_memories")
    def test_records_one_cite_for_duplicate_refs_across_steps(
        self, list_memories, record_memory_event
    ):
        """Count a canonical memory at most once in one LLM response."""
        list_memories.return_value = ["Known.md"]

        self.agent._scan_memory_refs(self.response)

        record_memory_event.assert_called_once()
        workspace, memory_id, event = record_memory_event.call_args.args
        self.assertTrue(workspace)
        self.assertEqual((memory_id, event), ("Known.md", "cite"))

    @patch("topsailai.tools.memory_tool_utils.memory_stat.record_memory_event")
    @patch("topsailai.tools.story_memory_tool.list_memories")
    def test_unknown_and_ambiguous_refs_are_not_recorded(
        self, list_memories, record_memory_event
    ):
        """Ignore unresolved titles while preserving response processing."""
        list_memories.return_value = ["Clash.md", "clash.md"]
        response = [
            {
                "step_name": "thought",
                "raw_text": "@memory[CLASH.MD] and @memory[Missing.md]",
            }
        ]

        self.agent._scan_memory_refs(response)

        record_memory_event.assert_not_called()

    @patch("topsailai.tools.story_memory_tool.list_memories")
    def test_disabled_env_is_fast_noop(self, list_memories):
        """Skip imports, title enumeration, and writes when explicitly disabled."""
        with patch.dict(
            os.environ,
            {"TOPSAILAI_MEMORY_REFERENCE_SCAN_ENABLED": "0"},
        ):
            self.agent._scan_memory_refs(self.response)

        list_memories.assert_not_called()

    @patch("topsailai.tools.memory_tool_utils.memory_stat.record_memory_event")
    @patch("topsailai.tools.story_memory_tool.list_memories")
    def test_non_text_steps_are_ignored(self, list_memories, record_memory_event):
        """Scan only string raw_text values from parsed assistant steps."""
        list_memories.return_value = ["Known.md"]
        response = [
            {"step_name": "action", "raw_text": {"memory": "@memory[Known.md]"}},
            None,
        ]

        self.agent._scan_memory_refs(response)

        record_memory_event.assert_not_called()

    @patch("topsailai.ai_base.agent_base.logger.warning")
    @patch("topsailai.tools.story_memory_tool.list_memories")
    def test_accounting_error_is_logged_and_swallowed(
        self, list_memories, log_warning
    ):
        """Never let citation-accounting failures interrupt response delivery."""
        list_memories.side_effect = RuntimeError("unavailable")

        result = self.agent._scan_memory_refs(self.response)

        self.assertIsNone(result)
        log_warning.assert_called_once()
        self.assertIn(
            "Failed to record story-memory references",
            log_warning.call_args.args[0],
        )


class TestAgentRunMemoryReferenceChokepoint(TestCase):
    """Verify the scanner runs after persisting each parsed LLM response."""

    @patch("topsailai.ai_base.agent_base.get_tools_for_chat", return_value={})
    @patch("topsailai.ai_base.agent_base.env_tool")
    def test_run_scans_response_after_adding_assistant_message(
        self, env_tool, _get_tools
    ):
        """Invoke citation scanning once at the per-response chokepoint."""
        agent = object.__new__(AgentRun)
        response = [{"step_name": "final_answer", "raw_text": "done"}]
        rsp_message = type("ResponseMessage", (), {"tool_calls": None})()
        final_step = StepCallBase()
        final_step.code = final_step.CODE_TASK_FINAL
        final_step.result = "done"
        call_order = []
        agent.available_tools = {}
        agent.messages = []
        agent.new_session = lambda _message: None
        agent._check_hard_interrupt = lambda **_kwargs: None
        agent._inject_runtime_messages = lambda: None
        agent.llm_model = type(
            "LLMModel",
            (),
            {
                "chat": lambda _self, *_args, **_kwargs: (object(), response),
                "get_response_message": lambda _self, _rsp: rsp_message,
            },
        )()
        agent.add_assistant_message = (
            lambda *_args, **_kwargs: (
                agent.messages.append({"role": "assistant"}),
                call_order.append("add"),
            )
        )
        agent._scan_memory_refs = lambda _response: call_order.append("scan")
        env_tool.is_use_tool_calls.return_value = False

        result = agent._run(lambda *_args, **_kwargs: final_step, "task")

        self.assertEqual(result, "done")
        self.assertEqual(call_order, ["add", "scan"])
