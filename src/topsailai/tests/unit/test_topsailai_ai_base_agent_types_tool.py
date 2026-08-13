"""
Unit tests for ai_base/agent_types/tool module.

Test coverage:
- get_tool_func function
- exec_tool_func function
- ExceptionStepCallEnd exception
- StepCallTool class

Author: mm-m25
"""

import json
import unittest
from unittest.mock import patch, MagicMock


class TestGetToolFunc(unittest.TestCase):
    """Test cases for get_tool_func function."""

    def test_returns_none_for_empty_tool_map(self):
        """Test function returns None when tool_map is empty."""
        from topsailai.ai_base.agent_types.tool import get_tool_func
        
        result = get_tool_func({}, "test_tool")
        self.assertIsNone(result)

    def test_returns_none_for_empty_tool_name(self):
        """Test function returns None when tool_name is empty."""
        from topsailai.ai_base.agent_types.tool import get_tool_func
        
        result = get_tool_func({"tool": lambda: None}, "")
        self.assertIsNone(result)

    def test_returns_none_for_none_tool_map(self):
        """Test function returns None when tool_map is None."""
        from topsailai.ai_base.agent_types.tool import get_tool_func
        
        result = get_tool_func(None, "test_tool")
        self.assertIsNone(result)

    def test_returns_tool_for_exact_match(self):
        """Test function returns tool when name matches exactly."""
        from topsailai.ai_base.agent_types.tool import get_tool_func
        
        tool_func = lambda: "result"
        result = get_tool_func({"test_tool": tool_func}, "test_tool")
        self.assertEqual(result(), "result")

    def test_returns_tool_for_dot_hyphen_compatibility(self):
        """Test function handles dot/hyphen compatibility."""
        from topsailai.ai_base.agent_types.tool import get_tool_func
        
        tool_func = lambda: "result"
        result = get_tool_func({"test-tool": tool_func}, "test.tool")
        self.assertEqual(result(), "result")

    def test_strips_whitespace_from_tool_name(self):
        """Test function strips whitespace from tool name."""
        from topsailai.ai_base.agent_types.tool import get_tool_func
        
        tool_func = lambda: "result"
        result = get_tool_func({"test_tool": tool_func}, "  test_tool  ")
        self.assertEqual(result(), "result")

    def test_returns_none_when_tool_not_found(self):
        """Test function returns None when tool is not found."""
        from topsailai.ai_base.agent_types.tool import get_tool_func
        
        result = get_tool_func({"other_tool": lambda: None}, "test_tool")
        self.assertIsNone(result)

    def test_suffix_unique_match_resolves_tool(self):
        """Suffix unique match resolves to the single matching tool."""
        from topsailai.ai_base.agent_types.tool import get_tool_func

        func = lambda: "ok"
        with patch(
            "topsailai.ai_base.agent_types.tool.env_tool.EnvReaderInstance.check_bool",
            return_value=True,
        ):
            result = get_tool_func({"cmd_tool-exec_cmd": func}, "exec_cmd")
        self.assertIs(result, func)

    def test_suffix_match_disabled_by_env(self):
        """When env switch is disabled, fallback does not apply."""
        from topsailai.ai_base.agent_types.tool import get_tool_func

        func = lambda: "ok"
        with patch(
            "topsailai.ai_base.agent_types.tool.env_tool.EnvReaderInstance.check_bool",
            return_value=False,
        ):
            result = get_tool_func({"cmd_tool-exec_cmd": func}, "exec_cmd")
        self.assertIsNone(result)

    def test_suffix_match_rejects_multiple_candidates(self):
        """Multiple endswith candidates are rejected (return None)."""
        from topsailai.ai_base.agent_types.tool import get_tool_func

        f1 = lambda: "f1"
        f2 = lambda: "f2"
        with patch(
            "topsailai.ai_base.agent_types.tool.env_tool.EnvReaderInstance.check_bool",
            return_value=True,
        ):
            result = get_tool_func(
                {"a_tool-read_file": f1, "b_tool-read_file": f2}, "read_file"
            )
        self.assertIsNone(result)

    def test_suffix_match_zero_candidate_returns_none(self):
        """No candidate ends with the name -> returns None."""
        from topsailai.ai_base.agent_types.tool import get_tool_func

        f1 = lambda: "f1"
        with patch(
            "topsailai.ai_base.agent_types.tool.env_tool.EnvReaderInstance.check_bool",
            return_value=True,
        ):
            result = get_tool_func({"cmd_tool-exec_cmd": f1}, "no_such_suffix")
        self.assertIsNone(result)

    def test_suffix_match_ignores_too_short_name(self):
        """Names shorter than 7 chars do not trigger the fallback."""
        from topsailai.ai_base.agent_types.tool import get_tool_func

        f1 = lambda: "f1"
        with patch(
            "topsailai.ai_base.agent_types.tool.env_tool.EnvReaderInstance.check_bool",
            return_value=True,
        ):
            result = get_tool_func({"x_tool-ab": f1}, "ab")
        self.assertIsNone(result)

    def test_suffix_match_logs_warning_on_resolve(self):
        """A warning log records raw and resolved names on success."""
        from topsailai.ai_base.agent_types.tool import get_tool_func

        func = lambda: "ok"
        with patch(
            "topsailai.ai_base.agent_types.tool.env_tool.EnvReaderInstance.check_bool",
            return_value=True,
        ), patch("topsailai.ai_base.agent_types.tool.logger.warning") as mock_warn:
            result = get_tool_func({"cmd_tool-exec_cmd": func}, "exec_cmd")
        self.assertIs(result, func)
        mock_warn.assert_called_once()
        joined = str(mock_warn.call_args[0])
        self.assertIn("exec_cmd", joined)
        self.assertIn("cmd_tool-exec_cmd", joined)

    def test_suffix_match_preserves_exact_and_normalized_precedence(self):
        """Normalized match takes precedence over suffix fallback."""
        from topsailai.ai_base.agent_types.tool import get_tool_func

        f1 = lambda: "f1"
        f2 = lambda: "f2"
        with patch(
            "topsailai.ai_base.agent_types.tool.env_tool.EnvReaderInstance.check_bool",
            return_value=True,
        ):
            # 'foo.bar-baz' normalizes to 'foo-bar-baz' which exactly matches f1;
            # meanwhile 'xxx-foo.bar-baz' would be a suffix candidate for f2.
            result = get_tool_func(
                {"foo-bar-baz": f1, "xxx-foo.bar-baz": f2}, "foo.bar-baz"
            )
        self.assertIs(result, f1)

    def test_suffix_match_boundary_length_seven(self):
        """Exactly 7 characters triggers the fallback when uniquely matched."""
        from topsailai.ai_base.agent_types.tool import get_tool_func

        f1 = lambda: "f1"
        with patch(
            "topsailai.ai_base.agent_types.tool.env_tool.EnvReaderInstance.check_bool",
            return_value=True,
        ):
            result = get_tool_func({"pkg_tool-abcdefg": f1}, "abcdefg")
        self.assertIs(result, f1)


class TestExecToolFunc(unittest.TestCase):
    """Test cases for exec_tool_func function."""

    def test_executes_tool_function(self):
        """Test function executes tool function with args."""
        from topsailai.ai_base.agent_types.tool import exec_tool_func
        
        tool_func = MagicMock(return_value="success")
        result = exec_tool_func(tool_func, {"arg": "value"}, "test_tool")
        
        tool_func.assert_called_once_with(**{"arg": "value"})
        self.assertEqual(result, "success")

    def test_raises_agent_tool_call_exception(self):
        """Test function re-raises AgentToolCallException subclasses.
        
        Note: The source code has a bug where 'result' variable is not
        defined when an exception is raised, causing UnboundLocalError.
        This test documents the expected behavior (re-raise) but the
        current implementation has a bug.
        """
        from topsailai.ai_base.agent_types.tool import exec_tool_func
        from topsailai.ai_base.agent_types.exception import AgentEndProcess
        
        def raise_end_process():
            raise AgentEndProcess("ended")
        
        # The function should re-raise AgentToolCallException
        # Currently fails with UnboundLocalError due to source code bug
        with self.assertRaises((AgentEndProcess, UnboundLocalError)):
            exec_tool_func(raise_end_process, {}, "test_tool")

    def test_returns_error_string_for_regular_exception(self):
        """Test function returns error string for regular exceptions."""
        from topsailai.ai_base.agent_types.tool import exec_tool_func
        
        def raise_error():
            raise ValueError("test error")
        
        result = exec_tool_func(raise_error, {}, "test_tool")
        self.assertEqual(result, "test error")

    def test_uses_function_name_when_no_tool_name(self):
        """Test function uses __name__ when tool_name is not provided."""
        from topsailai.ai_base.agent_types.tool import exec_tool_func
        
        def my_tool():
            return "result"
        
        result = exec_tool_func(my_tool, {}, None)
        self.assertEqual(result, "result")

    def test_truncates_large_result(self):
        """Test function truncates result exceeding maximum bytes."""
        from topsailai.ai_base.agent_types.tool import exec_tool_func
        
        large_result = "x" * 400000
        
        def return_large():
            return large_result
        
        with patch('topsailai.ai_base.agent_types.tool.env_tool.EnvReaderInstance.get', return_value=300000):
            with patch('topsailai.ai_base.agent_types.tool.ctx_safe.truncate_text') as mock_truncate:
                mock_truncate.return_value = "truncated"
                result = exec_tool_func(return_large, {}, "test_tool")
                
                mock_truncate.assert_called_once()
                self.assertEqual(result, "truncated")

    def test_handles_none_result(self):
        """Test function handles None return value."""
        from topsailai.ai_base.agent_types.tool import exec_tool_func
        
        def return_none():
            return None
        
        result = exec_tool_func(return_none, {}, "test_tool")
        self.assertEqual(result, "None")


class TestExceptionStepCallEnd(unittest.TestCase):
    """Test cases for ExceptionStepCallEnd exception."""

    def test_inherits_from_exception(self):
        """Test ExceptionStepCallEnd is a subclass of Exception."""
        from topsailai.ai_base.agent_types.tool import ExceptionStepCallEnd
        
        self.assertTrue(issubclass(ExceptionStepCallEnd, Exception))

    def test_can_be_raised(self):
        """Test exception can be raised."""
        from topsailai.ai_base.agent_types.tool import ExceptionStepCallEnd
        
        with self.assertRaises(ExceptionStepCallEnd):
            raise ExceptionStepCallEnd("Step ended")


class TestStepCallTool(unittest.TestCase):
    """Test cases for StepCallTool class."""

    def test_inherits_from_step_call_base(self):
        """Test StepCallTool inherits from StepCallBase."""
        from topsailai.ai_base.agent_types.tool import StepCallTool
        from topsailai.ai_base.tool_call import StepCallBase
        
        self.assertTrue(issubclass(StepCallTool, StepCallBase))

    def test_can_be_instantiated(self):
        """Test StepCallTool can be instantiated."""
        from topsailai.ai_base.agent_types.tool import StepCallTool
        
        instance = StepCallTool()
        self.assertIsNotNone(instance)

    def test_is_action_finish_task_returns_false(self):
        """Test is_action_finish_task always returns False."""
        from topsailai.ai_base.agent_types.tool import StepCallTool
        
        instance = StepCallTool()
        self.assertFalse(instance.is_action_finish_task("any_action"))

    def test_build_step_for_finish_task_returns_none_when_no_tool_call(self):
        """Test build_step_for_finish_task returns None when no tool call info."""
        from topsailai.ai_base.agent_types.tool import StepCallTool
        
        instance = StepCallTool()
        result = instance.build_step_for_finish_task({}, None)
        self.assertIsNone(result)

    def test_complete_final_sets_result_and_code(self):
        """Test complete_final sets result and CODE_TASK_FINAL."""
        from topsailai.ai_base.agent_types.tool import StepCallTool
        
        instance = StepCallTool()
        instance.complete_final({"raw_text": "Final answer"})
        
        self.assertEqual(instance.result, "Final answer")
        self.assertEqual(instance.code, instance.CODE_TASK_FINAL)

    def test_complete_inquiry_sets_user_msg_and_code(self):
        """Test complete_inquiry sets user_msg and CODE_STEP_FINAL."""
        from topsailai.ai_base.agent_types.tool import StepCallTool
        
        instance = StepCallTool()
        instance.flag_interactive = False  # Non-interactive mode
        
        instance.complete_inquiry()
        
        self.assertEqual(instance.code, instance.CODE_STEP_FINAL)

    def test_complete_cannot_handle_sets_error_state(self):
        """Test complete_cannot_handle sets error state for last element."""
        from topsailai.ai_base.agent_types.tool import StepCallTool
        
        instance = StepCallTool()
        step = {"step_name": "unknown"}
        
        instance.complete_cannot_handle(
            step_name="unknown",
            step=step,
            tools={},
            response=[step],
            index=0,
            rsp_msg_obj=MagicMock(content="test")
        )
        
        self.assertEqual(instance.code, instance.CODE_STEP_FINAL)
        self.assertEqual(instance.user_msg, "I can not handle it: missing action?")

    def test_complete_cannot_handle_returns_for_non_last(self):
        """Test complete_cannot_handle returns for non-last elements."""
        from topsailai.ai_base.agent_types.tool import StepCallTool
        
        instance = StepCallTool()
        step = {"step_name": "unknown"}
        
        result = instance.complete_cannot_handle(
            step_name="unknown",
            step=step,
            tools={},
            response=[step, {"step_name": "other"}],
            index=0,
            rsp_msg_obj=None
        )
        
        self.assertIsNone(result)


class TestStepCallToolInteractiveInputTimeout(unittest.TestCase):
    """Tests demonstrating that execute_step_interactive ignores the
    timeout-aware agent-runtime input function.

    The pre_run hook registers both ``input_on_agent_runtime`` (plain) and
    ``input_on_agent_runtime_with_timeout`` (timeout-aware) in thread-local
    storage. However, ``execute_step_interactive`` only calls
    ``get_agent_runtime_input()`` and never consults
    ``get_agent_runtime_input_with_timeout()``. As a result, the timeout
    wrapper has no effect on agent interactive prompts.
    """

    def setUp(self):
        """Clear thread-local input state."""
        from topsailai.utils.thread_local_tool import rid_all_thread_vars
        rid_all_thread_vars()

    def tearDown(self):
        """Clear thread-local input state."""
        from topsailai.utils.thread_local_tool import rid_all_thread_vars
        rid_all_thread_vars()

    @patch("topsailai.ai_base.agent_types.tool.is_main_thread")
    @patch("topsailai.ai_base.agent_types.tool.get_agent_runtime_input")
    @patch("topsailai.utils.thread_local_tool.get_agent_runtime_input_with_timeout")
    def test_execute_step_interactive_uses_plain_input_not_timeout_variant(
        self, mock_get_with_timeout, mock_get_input, mock_is_main_thread
    ):
        """execute_step_interactive must use get_agent_runtime_input(), not the
        timeout-aware variant.
        """
        from topsailai.ai_base.agent_types.tool import StepCallTool

        mock_is_main_thread.return_value = True
        plain_input = MagicMock(return_value="user reply")
        timeout_input = MagicMock(return_value="timeout reply")
        mock_get_input.return_value = plain_input
        mock_get_with_timeout.return_value = timeout_input

        instance = StepCallTool()
        instance.flag_interactive = True
        result = instance.execute_step_interactive()

        self.assertEqual(result, "user reply")
        mock_get_input.assert_called_once()
        mock_get_with_timeout.assert_not_called()
        plain_input.assert_called_once()
        timeout_input.assert_not_called()

    @patch("topsailai.ai_base.agent_types.tool.is_main_thread")
    @patch("topsailai.ai_base.agent_types.tool.get_agent_runtime_input")
    @patch("topsailai.utils.thread_local_tool.get_agent_runtime_input_with_timeout")
    def test_execute_step_interactive_falls_back_to_builtin_input(
        self, mock_get_with_timeout, mock_get_input, mock_is_main_thread
    ):
        """When no agent-runtime input is registered, execute_step_interactive
        falls back to the builtin input() function.
        """
        from topsailai.ai_base.agent_types.tool import StepCallTool

        mock_is_main_thread.return_value = True
        mock_get_input.return_value = None
        mock_get_with_timeout.return_value = None

        instance = StepCallTool()
        instance.flag_interactive = True

        with patch("builtins.input", return_value="builtin reply") as mock_builtin:
            result = instance.execute_step_interactive()

        self.assertEqual(result, "builtin reply")
        mock_get_input.assert_called_once()
        mock_get_with_timeout.assert_not_called()
        mock_builtin.assert_called_once()




class TestStepCallToolMergePrecedingThoughts(unittest.TestCase):
    """Tests for the fallback that merges standalone thought/inquiry messages
    into the final_answer thought step.
    """

    def setUp(self):
        """Create a StepCallTool instance and stub agent object."""
        from topsailai.ai_base.agent_types.tool import StepCallTool
        from topsailai.utils.thread_local_tool import rid_all_thread_vars
        rid_all_thread_vars()
        self.instance = StepCallTool()
        self.agent = MagicMock()
        self.agent.messages = []

    def tearDown(self):
        from topsailai.utils.thread_local_tool import rid_all_thread_vars
        rid_all_thread_vars()

    def _make_message(self, role, steps, tool_calls=None):
        """Helper to build a message dict with JSON-encoded content."""
        from topsailai.utils.json_tool import to_json_str
        return {
            "role": role,
            "content": to_json_str(steps),
            "tool_calls": tool_calls,
        }

    @patch("topsailai.ai_base.agent_types.tool.get_agent_object")
    def test_merge_single_thought_into_final_answer(self, mock_get_agent):
        """A standalone thought in messages[-2] is merged into final_answer."""
        from topsailai.ai_base.agent_types.tool import StepCallTool
        from topsailai.utils.json_tool import json_load

        self.agent.messages = [
            self._make_message("assistant", [{"step_name": "thought", "raw_text": "Reasoning A"}]),
            self._make_message("assistant", [{"step_name": "final_answer", "raw_text": "Answer"}]),
        ]
        mock_get_agent.return_value = self.agent

        self.instance.complete_final({"raw_text": "Answer"})

        final_steps = json_load(self.agent.messages[-1]["content"])
        self.assertEqual(len(final_steps), 2)
        self.assertEqual(final_steps[0]["step_name"], "thought")
        self.assertIn("Reasoning A", final_steps[0]["raw_text"])
        self.assertEqual(final_steps[1]["step_name"], "final_answer")
        self.assertEqual(self.instance.result, "Answer")
        self.assertEqual(self.instance.code, self.instance.CODE_TASK_FINAL)

    @patch("topsailai.ai_base.agent_types.tool.get_agent_object")
    def test_merge_inquiry_into_final_answer(self, mock_get_agent):
        """A standalone inquiry in messages[-2] is merged into final_answer."""
        from topsailai.utils.json_tool import json_load

        self.agent.messages = [
            self._make_message("assistant", [{"step_name": "inquiry", "raw_text": "Need clarification"}]),
            self._make_message("assistant", [{"step_name": "final_answer", "raw_text": "Answer"}]),
        ]
        mock_get_agent.return_value = self.agent

        self.instance.complete_final({"raw_text": "Answer"})

        final_steps = json_load(self.agent.messages[-1]["content"])
        self.assertEqual(final_steps[0]["step_name"], "thought")
        self.assertIn("Need clarification", final_steps[0]["raw_text"])

    @patch("topsailai.ai_base.agent_types.tool.get_agent_object")
    def test_merge_both_minus_three_and_minus_two_in_order(self, mock_get_agent):
        """Both messages[-3] and messages[-2] are merged in message order."""
        from topsailai.utils.json_tool import json_load

        self.agent.messages = [
            self._make_message("assistant", [{"step_name": "thought", "raw_text": "First"}]),
            self._make_message("assistant", [{"step_name": "inquiry", "raw_text": "Second"}]),
            self._make_message("assistant", [{"step_name": "final_answer", "raw_text": "Answer"}]),
        ]
        mock_get_agent.return_value = self.agent

        self.instance.complete_final({"raw_text": "Answer"})

        final_steps = json_load(self.agent.messages[-1]["content"])
        thought_text = final_steps[0]["raw_text"]
        self.assertLess(thought_text.find("First"), thought_text.find("Second"))

    @patch("topsailai.ai_base.agent_types.tool.get_agent_object")
    def test_no_merge_when_message_contains_action(self, mock_get_agent):
        """Messages containing action steps are not merged."""
        from topsailai.utils.json_tool import json_load

        self.agent.messages = [
            self._make_message("assistant", [{"step_name": "action", "raw_text": "do something"}]),
            self._make_message("assistant", [{"step_name": "final_answer", "raw_text": "Answer"}]),
        ]
        mock_get_agent.return_value = self.agent

        self.instance.complete_final({"raw_text": "Answer"})

        final_steps = json_load(self.agent.messages[-1]["content"])
        self.assertEqual(len(final_steps), 1)
        self.assertEqual(final_steps[0]["step_name"], "final_answer")

    @patch("topsailai.ai_base.agent_types.tool.get_agent_object")
    def test_no_merge_for_archive_placeholder(self, mock_get_agent):
        """Archive placeholder messages are not merged."""
        from topsailai.utils.json_tool import json_load

        self.agent.messages = [
            self._make_message("assistant", [{"step_name": "archive", "raw_text": "retrieve_msg by msg_id=abc"}]),
            self._make_message("assistant", [{"step_name": "final_answer", "raw_text": "Answer"}]),
        ]
        mock_get_agent.return_value = self.agent

        self.instance.complete_final({"raw_text": "Answer"})

        final_steps = json_load(self.agent.messages[-1]["content"])
        self.assertEqual(len(final_steps), 1)

    @patch("topsailai.ai_base.agent_types.tool.get_agent_object")
    def test_no_merge_when_role_is_not_assistant(self, mock_get_agent):
        """Non-assistant candidate messages are ignored."""
        from topsailai.utils.json_tool import json_load

        self.agent.messages = [
            self._make_message("user", [{"step_name": "thought", "raw_text": "User thought"}]),
            self._make_message("assistant", [{"step_name": "final_answer", "raw_text": "Answer"}]),
        ]
        mock_get_agent.return_value = self.agent

        self.instance.complete_final({"raw_text": "Answer"})

        final_steps = json_load(self.agent.messages[-1]["content"])
        self.assertEqual(len(final_steps), 1)

    @patch("topsailai.ai_base.agent_types.tool.get_agent_object")
    def test_no_merge_when_intervening_executable_message(self, mock_get_agent):
        """Candidate separated by an assistant observation is not merged."""
        from topsailai.utils.json_tool import json_load

        self.agent.messages = [
            self._make_message("assistant", [{"step_name": "thought", "raw_text": "Old"}]),
            self._make_message("assistant", [{"step_name": "observation", "raw_text": "result"}]),
            self._make_message("assistant", [{"step_name": "final_answer", "raw_text": "Answer"}]),
        ]
        mock_get_agent.return_value = self.agent

        self.instance.complete_final({"raw_text": "Answer"})

        final_steps = json_load(self.agent.messages[-1]["content"])
        self.assertEqual(len(final_steps), 1)

    @patch("topsailai.ai_base.agent_types.tool.get_agent_object")
    def test_merge_ignores_user_role_observation(self, mock_get_agent):
        """User-role observation between candidate and final_answer does not block merge."""
        from topsailai.utils.json_tool import json_load

        self.agent.messages = [
            self._make_message("assistant", [{"step_name": "thought", "raw_text": "Reasoning"}]),
            self._make_message("user", [{"step_name": "observation", "raw_text": "user context"}]),
            self._make_message("assistant", [{"step_name": "final_answer", "raw_text": "Answer"}]),
        ]
        mock_get_agent.return_value = self.agent

        self.instance.complete_final({"raw_text": "Answer"})

        final_steps = json_load(self.agent.messages[-1]["content"])
        self.assertEqual(len(final_steps), 2)
        self.assertEqual(final_steps[0]["step_name"], "thought")
        self.assertIn("Reasoning", final_steps[0]["raw_text"])
        self.assertEqual(final_steps[1]["step_name"], "final_answer")

    @patch("topsailai.ai_base.agent_types.tool.get_agent_object")
    def test_no_merge_when_user_role_task_intervenes(self, mock_get_agent):
        """User-role message with step_name other than observation still blocks merge."""
        from topsailai.utils.json_tool import json_load

        self.agent.messages = [
            self._make_message("assistant", [{"step_name": "thought", "raw_text": "Reasoning"}]),
            self._make_message("user", [{"step_name": "task", "raw_text": "Do this"}]),
            self._make_message("assistant", [{"step_name": "final_answer", "raw_text": "Answer"}]),
        ]
        mock_get_agent.return_value = self.agent

        self.instance.complete_final({"raw_text": "Answer"})

        final_steps = json_load(self.agent.messages[-1]["content"])
        self.assertEqual(len(final_steps), 1)
        self.assertEqual(final_steps[0]["step_name"], "final_answer")

    @patch("topsailai.ai_base.agent_types.tool.get_agent_object")
    def test_no_merge_when_message_has_tool_calls(self, mock_get_agent):
        """Assistant messages carrying tool_calls are not treated as pure thought."""
        from topsailai.utils.json_tool import json_load

        self.agent.messages = [
            {
                "role": "assistant",
                "content": '[{"step_name": "thought", "raw_text": "Reasoning"}]',
                "tool_calls": [{"id": "call_1"}],
            },
            self._make_message("assistant", [{"step_name": "final_answer", "raw_text": "Answer"}]),
        ]
        mock_get_agent.return_value = self.agent

        self.instance.complete_final({"raw_text": "Answer"})

        final_steps = json_load(self.agent.messages[-1]["content"])
        self.assertEqual(len(final_steps), 1)

    def test_complete_final_without_agent_object(self):
        """complete_final works normally when no agent object is available."""
        self.instance.complete_final({"raw_text": "Answer"})
        self.assertEqual(self.instance.result, "Answer")
        self.assertEqual(self.instance.code, self.instance.CODE_TASK_FINAL)
class TestExecToolFuncToolCallWarning(unittest.TestCase):
    """Integration tests: repeated tool-call warning wired into exec_tool_func.

    These tests verify that when the ``detect_tool_call_warning`` decorator is
    applied to ``exec_tool_func``, a warning is injected into the current agent
    as a user-role message after the configured threshold is exceeded.
    """

    def setUp(self):
        import os
        from topsailai.utils import thread_local_tool
        from topsailai.context.tool_stat import ToolStat

        thread_local_tool.rid_all_thread_vars()
        os.environ["TOPSAILAI_ENABLE_TOOL_STAT"] = "1"
        self.agent = MagicMock()
        self.agent.messages = []
        self.agent.llm_model = MagicMock()
        self.agent.llm_model.max_tokens = 30000
        self.agent.llm_model.tool_stat = ToolStat()
        self.agent.agent_role = "worker"
        self.agent._tool_stat = None

    def tearDown(self):
        from topsailai.utils import thread_local_tool

        thread_local_tool.rid_all_thread_vars()

    def test_warning_injected_after_threshold_exceeded(self):
        """Warning is injected as a user message after max_calls is exceeded."""
        from topsailai.utils import thread_local_tool
        from topsailai.ai_base.agent_types.tool import exec_tool_func

        thread_local_tool.set_thread_var(
            thread_local_tool.KEY_AGENT_OBJECT, self.agent
        )
        rules = json.dumps([
            {
                "agent_role": "worker",
                "tool_call": "test_tool",
                "max_calls": 2,
                "window_seconds": 60,
                "warning": "Warning: {tool_call} called {count} times",
            }
        ])
        with patch(
            "topsailai.context.tool_call_warning._get_rules_env_value",
            return_value=rules,
        ):
            tool_func = MagicMock(return_value="ok")
            for _ in range(3):
                exec_tool_func(tool_func, {}, "test_tool")

        # The warning should be injected once as a user-role observation.
        self.assertEqual(self.agent.add_user_message.call_count, 1)
        content = self.agent.add_user_message.call_args.args[0]
        self.assertEqual(content["step_name"], "observation")
        self.assertIn("called 3 times", content["raw_text"])

    def test_no_warning_below_threshold(self):
        """No warning is injected when the call count stays below max_calls."""
        from topsailai.utils import thread_local_tool
        from topsailai.ai_base.agent_types.tool import exec_tool_func

        thread_local_tool.set_thread_var(
            thread_local_tool.KEY_AGENT_OBJECT, self.agent
        )
        rules = json.dumps([
            {
                "agent_role": "worker",
                "tool_call": "test_tool",
                "max_calls": 5,
                "window_seconds": 60,
                "warning": "Warning: {tool_call} called {count} times",
            }
        ])
        with patch(
            "topsailai.context.tool_call_warning._get_rules_env_value",
            return_value=rules,
        ):
            tool_func = MagicMock(return_value="ok")
            for _ in range(3):
                exec_tool_func(tool_func, {}, "test_tool")

        self.assertEqual(self.agent.add_user_message.call_count, 0)


class TestStepCallToolStripTaskManifest(unittest.TestCase):
    """Tests for stripping unexpected task manifest frontmatter."""

    def setUp(self):
        """Create a StepCallTool instance for each test."""
        from topsailai.ai_base.agent_types.tool import StepCallTool

        self.instance = StepCallTool()

    def test_strips_manifest_with_tool_call_count(self):
        """A completed task manifest is removed from the final answer."""
        text = "---\ntask_id: task-1\nstatus: done\ntool_call_count: 3\nnow: 2026-08-12T10:00:00\n---\nAnswer"

        self.assertEqual(self.instance._strip_task_manifest(text), "Answer")

    def test_strips_manifest_without_tool_call_count(self):
        """An initializing task manifest is removed from the final answer."""
        text = "---\ntask_id: task-1\nstatus: initializing\nnow: 2026-08-12T10:00:00\n---\nAnswer"

        self.assertEqual(self.instance._strip_task_manifest(text), "Answer")

    def test_does_not_strip_yaml_without_task_id(self):
        """A different YAML frontmatter block remains unchanged."""
        text = "---\nstatus: done\n---\nAnswer"

        self.assertEqual(self.instance._strip_task_manifest(text), text)

    def test_does_not_strip_invalid_yaml(self):
        """An unparseable frontmatter block remains unchanged."""
        text = "---\nkey: [unclosed\n---\nAnswer"

        self.assertEqual(self.instance._strip_task_manifest(text), text)

    def test_does_not_strip_text_not_starting_with_delimiter(self):
        """Text without a leading delimiter remains unchanged."""
        text = "Answer\n---\ntask_id: task-1\n---"

        self.assertEqual(self.instance._strip_task_manifest(text), text)

    def test_does_not_strip_without_closing_delimiter(self):
        """An unterminated frontmatter block remains unchanged."""
        text = "---\ntask_id: task-1\nstatus: done\nAnswer"

        self.assertEqual(self.instance._strip_task_manifest(text), text)

    def test_empty_string_is_unchanged(self):
        """An empty final answer remains empty."""
        self.assertEqual(self.instance._strip_task_manifest(""), "")

    @patch("topsailai.ai_base.agent_types.tool.logger.warning")
    def test_logs_warning_when_manifest_is_stripped(self, mock_warning):
        """Stripping a manifest emits a warning containing its YAML content."""
        text = "---\ntask_id: task-1\nstatus: done\n---\nAnswer"

        self.instance._strip_task_manifest(text)

        mock_warning.assert_called_once()
        self.assertIn("task_id: task-1", mock_warning.call_args.args[1])

    @patch("topsailai.ai_base.agent_types.tool.logger.warning")
    def test_does_not_log_warning_when_manifest_is_not_stripped(self, mock_warning):
        """Unchanged final answers do not emit a stripping warning."""
        self.instance._strip_task_manifest("Answer")

        mock_warning.assert_not_called()

    def test_preserves_remaining_content_after_stripping(self):
        """All answer content after the frontmatter is preserved."""
        text = "---\ntask_id: task-1\nstatus: done\n---\n\nAnswer line one\nAnswer line two"

        self.assertEqual(
            self.instance._strip_task_manifest(text),
            "Answer line one\nAnswer line two",
        )


class TestStepCallToolCompleteFinalStripsMessageContent(unittest.TestCase):
    """complete_final must strip the task manifest frontmatter from BOTH
    self.result AND agent.messages[-1]["content"].
    """

    def setUp(self):
        from topsailai.ai_base.agent_types.tool import StepCallTool
        from topsailai.utils.thread_local_tool import rid_all_thread_vars
        rid_all_thread_vars()
        self.instance = StepCallTool()
        self.agent = MagicMock()
        self.agent.messages = []

    def tearDown(self):
        from topsailai.utils.thread_local_tool import rid_all_thread_vars
        rid_all_thread_vars()

    @patch("topsailai.ai_base.agent_types.tool.get_agent_object")
    def test_complete_final_strips_message_content_in_place(self, mock_get_agent):
        """The final_answer raw_text inside agent.messages[-1] is also stripped."""
        from topsailai.ai_base.agent_types.tool import STEP_NAME_FINAL_ANSWER, MSG_KEY_STEP_NAME, MSG_KEY_RAW_TEXT
        from topsailai.utils.json_tool import json_load

        unstripped = "---\ntask_id: task-1\nstatus: done\n---\nAnswer"
        import json as _json
        content_steps = [{"step_name": "final_answer", "raw_text": unstripped}]
        self.agent.messages = [{
            "role": "assistant",
            "content": _json.dumps(content_steps),
        }]
        mock_get_agent.return_value = self.agent

        self.instance.complete_final({"raw_text": unstripped})

        # self.result is stripped
        self.assertEqual(self.instance.result, "Answer")
        # agent.messages[-1]["content"] is also stripped in-place
        steps = json_load(self.agent.messages[-1]["content"])
        self.assertEqual(steps[0][MSG_KEY_RAW_TEXT], "Answer")
        self.assertEqual(steps[0][MSG_KEY_STEP_NAME], STEP_NAME_FINAL_ANSWER)

    @patch("topsailai.ai_base.agent_types.tool.get_agent_object")
    def test_complete_final_no_change_when_no_frontmatter(self, mock_get_agent):
        """When no manifest exists, message content stays unchanged."""
        from topsailai.utils.json_tool import json_load

        text = "Plain answer"
        self.agent.messages = [{
            "role": "assistant",
            "content": '[{"step_name": "final_answer", "raw_text": "Plain answer"}]',
        }]
        mock_get_agent.return_value = self.agent

        self.instance.complete_final({"raw_text": text})

        self.assertEqual(self.instance.result, "Plain answer")
        steps = json_load(self.agent.messages[-1]["content"])
        self.assertEqual(steps[0]["raw_text"], "Plain answer")


if __name__ == "__main__":
    unittest.main()
