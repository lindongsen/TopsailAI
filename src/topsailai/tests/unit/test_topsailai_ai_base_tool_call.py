"""
Unit tests for ai_base/tool_call module.

Test coverage:
- ToolCallInfo class (data structure for tool call information)
- StepCallBase class (base class for step call return values)
- Status codes (CODE_TASK_FINAL, CODE_STEP_FINAL, CODE_TASK_FAILED)
- get_tool_call_info method (extraction from various sources)

Author: mm-m25
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch


class TestToolCallInfo(unittest.TestCase):
    """Test cases for ToolCallInfo class."""

    def test_init_empty_values(self):
        """Test ToolCallInfo initializes with empty function name and args."""
        from topsailai.ai_base.tool_call import ToolCallInfo
        
        info = ToolCallInfo()
        self.assertEqual(info.func_name, "")
        self.assertEqual(info.func_args, {})

    def test_set_func_name(self):
        """Test setting function name on ToolCallInfo."""
        from topsailai.ai_base.tool_call import ToolCallInfo
        
        info = ToolCallInfo()
        info.func_name = "test_function"
        self.assertEqual(info.func_name, "test_function")

    def test_set_func_args(self):
        """Test setting function arguments on ToolCallInfo."""
        from topsailai.ai_base.tool_call import ToolCallInfo
        
        info = ToolCallInfo()
        info.func_args = {"arg1": "value1", "arg2": 42}
        self.assertEqual(info.func_args["arg1"], "value1")
        self.assertEqual(info.func_args["arg2"], 42)


class TestStepCallBaseStatusCodes(unittest.TestCase):
    """Test cases for StepCallBase status codes."""

    def test_code_task_final_value(self):
        """Test CODE_TASK_FINAL has correct value (0)."""
        from topsailai.ai_base.tool_call import StepCallBase
        self.assertEqual(StepCallBase.CODE_TASK_FINAL, 0)

    def test_code_step_final_value(self):
        """Test CODE_STEP_FINAL has correct value (1)."""
        from topsailai.ai_base.tool_call import StepCallBase
        self.assertEqual(StepCallBase.CODE_STEP_FINAL, 1)

    def test_code_task_failed_value(self):
        """Test CODE_TASK_FAILED has correct value (-1)."""
        from topsailai.ai_base.tool_call import StepCallBase
        self.assertEqual(StepCallBase.CODE_TASK_FAILED, -1)


class TestStepCallBaseInit(unittest.TestCase):
    """Test cases for StepCallBase initialization."""

    def setUp(self):
        """Set up test environment."""
        # Store original env vars
        self.original_env = os.environ.get("TOPSAILAI_CHAT_INTERACTIVE_MODE")
        os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)
        
        # Clear module cache
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("topsailai")]
        for mod in modules_to_clear:
            del sys.modules[mod]

    def tearDown(self):
        """Restore environment after tests."""
        if self.original_env is not None:
            os.environ["TOPSAILAI_CHAT_INTERACTIVE_MODE"] = self.original_env
        else:
            os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)

    def test_init_default_interactive_false(self):
        """Test StepCallBase initializes with flag_interactive=False by default."""
        from topsailai.ai_base.tool_call import StepCallBase
        
        step_call = StepCallBase()
        self.assertFalse(step_call.flag_interactive)

    def test_init_interactive_mode_from_env(self):
        """Test StepCallBase initializes with flag_interactive=True when env var is set."""
        from topsailai.ai_base.tool_call import StepCallBase
        
        # Set env var to enable interactive mode
        os.environ["TOPSAILAI_CHAT_INTERACTIVE_MODE"] = "true"
        
        # Clear module cache to force re-import with new env
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("topsailai")]
        for mod in modules_to_clear:
            del sys.modules[mod]
        
        step_call = StepCallBase()
        self.assertTrue(step_call.flag_interactive)

    def test_init_result_attributes_initialized(self):
        """Test StepCallBase initializes result attributes to None."""
        from topsailai.ai_base.tool_call import StepCallBase
        
        step_call = StepCallBase()
        self.assertIsNone(step_call.code)
        self.assertIsNone(step_call.user_msg)
        self.assertIsNone(step_call.tool_msg)
        self.assertIsNone(step_call.result)


class TestStepCallBaseReset(unittest.TestCase):
    """Test cases for StepCallBase __reset method."""

    def setUp(self):
        """Set up test environment."""
        self.original_env = os.environ.get("TOPSAILAI_CHAT_INTERACTIVE_MODE")
        os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)
        
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("topsailai")]
        for mod in modules_to_clear:
            del sys.modules[mod]

    def tearDown(self):
        """Restore environment after tests."""
        if self.original_env is not None:
            os.environ["TOPSAILAI_CHAT_INTERACTIVE_MODE"] = self.original_env
        else:
            os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)

    def test_reset_clears_all_result_attributes(self):
        """Test __reset clears all result attributes to None."""
        from topsailai.ai_base.tool_call import StepCallBase
        
        step_call = StepCallBase()
        # Set some values
        step_call.code = 0
        step_call.user_msg = "test user"
        step_call.tool_msg = "test tool"
        step_call.result = "test result"
        
        # Call reset
        step_call._StepCallBase__reset()
        
        # Verify all are None
        self.assertIsNone(step_call.code)
        self.assertIsNone(step_call.user_msg)
        self.assertIsNone(step_call.tool_msg)
        self.assertIsNone(step_call.result)


class TestGetToolCallInfo(unittest.TestCase):
    """Test cases for get_tool_call_info method."""

    def setUp(self):
        """Set up test environment."""
        self.original_env = os.environ.get("TOPSAILAI_CHAT_INTERACTIVE_MODE")
        os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)
        
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("topsailai")]
        for mod in modules_to_clear:
            del sys.modules[mod]

    def tearDown(self):
        """Restore environment after tests."""
        if self.original_env is not None:
            os.environ["TOPSAILAI_CHAT_INTERACTIVE_MODE"] = self.original_env
        else:
            os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)

    def test_get_tool_call_info_from_rsp_msg_obj(self):
        """Test extraction from response message object."""
        from topsailai.ai_base.tool_call import StepCallBase, ToolCallInfo
        
        # Create mock response message object
        mock_function = MagicMock()
        mock_function.name = "test_function"
        mock_function.arguments = '{"arg1": "value1"}'
        
        mock_tool_call = MagicMock()
        mock_tool_call.function = mock_function
        
        rsp_msg_obj = MagicMock()
        rsp_msg_obj.tool_calls = [mock_tool_call]
        
        step_call = StepCallBase()
        result = step_call.get_tool_call_info({}, rsp_msg_obj)
        
        self.assertIsInstance(result, ToolCallInfo)
        self.assertEqual(result.func_name, "test_function")
        self.assertEqual(result.func_args["arg1"], "value1")

    def test_get_tool_call_info_from_step_dict(self):
        """Test extraction from step dictionary."""
        from topsailai.ai_base.tool_call import StepCallBase, ToolCallInfo
        
        step = {
            "tool_call": "step_function",
            "tool_args": {"arg2": 123}
        }
        
        step_call = StepCallBase()
        result = step_call.get_tool_call_info(step, None)
        
        self.assertIsInstance(result, ToolCallInfo)
        self.assertEqual(result.func_name, "step_function")
        self.assertEqual(result.func_args["arg2"], 123)

    def test_get_tool_call_info_from_raw_text(self):
        """Test extraction from raw_text field."""
        from topsailai.ai_base.tool_call import StepCallBase, ToolCallInfo
        
        step = {
            "raw_text": '{"tool_call": "raw_function", "tool_args": {"arg3": true}}'
        }
        
        step_call = StepCallBase()
        result = step_call.get_tool_call_info(step, None)
        
        self.assertIsInstance(result, ToolCallInfo)
        self.assertEqual(result.func_name, "raw_function")
        self.assertEqual(result.func_args["arg3"], True)

    def test_get_tool_call_info_returns_none_when_no_tool(self):
        """Test returns None when no tool call information is found."""
        from topsailai.ai_base.tool_call import StepCallBase
        
        step = {"some_other_field": "value"}
        
        step_call = StepCallBase()
        result = step_call.get_tool_call_info(step, None)
        
        self.assertIsNone(result)

    def test_get_tool_call_info_empty_step(self):
        """Test returns None for empty step dictionary."""
        from topsailai.ai_base.tool_call import StepCallBase
        
        step_call = StepCallBase()
        result = step_call.get_tool_call_info({}, None)
        
        self.assertIsNone(result)


class TestStepCallBaseExecute(unittest.TestCase):
    """Test cases for _execute method (should raise NotImplementedError)."""

    def setUp(self):
        """Set up test environment."""
        self.original_env = os.environ.get("TOPSAILAI_CHAT_INTERACTIVE_MODE")
        os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)
        
        modules_to_clear = [k for k in sys.modules.keys() if k.startswith("topsailai")]
        for mod in modules_to_clear:
            del sys.modules[mod]

    def tearDown(self):
        """Restore environment after tests."""
        if self.original_env is not None:
            os.environ["TOPSAILAI_CHAT_INTERACTIVE_MODE"] = self.original_env
        else:
            os.environ.pop("TOPSAILAI_CHAT_INTERACTIVE_MODE", None)

    def test_execute_raises_not_implemented(self):
        """Test _execute raises NotImplementedError when called directly."""
        from topsailai.ai_base.tool_call import StepCallBase
        
        step_call = StepCallBase()
        
        with self.assertRaises(NotImplementedError):
            step_call._execute({}, {}, [], 0, None)


if __name__ == "__main__":
    unittest.main()
