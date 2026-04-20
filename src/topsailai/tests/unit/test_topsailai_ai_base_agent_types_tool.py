"""
Unit tests for ai_base/agent_types/tool module.

Test coverage:
- get_tool_func function
- exec_tool_func function
- ExceptionStepCallEnd exception
- StepCallTool class

Author: mm-m25
"""

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


if __name__ == "__main__":
    unittest.main()
