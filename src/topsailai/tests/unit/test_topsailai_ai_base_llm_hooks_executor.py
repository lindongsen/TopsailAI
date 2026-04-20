import os
import unittest
from unittest.mock import patch, MagicMock
from topsailai.ai_base.llm_hooks.executor import get_hooks_runtime, hook_execute
from topsailai.utils.thread_local_tool import rid_all_thread_vars, set_thread_var, KEY_AGENT_OBJECT


class TestGetHooksRuntime(unittest.TestCase):
    """Test cases for get_hooks_runtime function."""

    def setUp(self):
        """Clear thread local storage and environment before each test to ensure test isolation."""
        rid_all_thread_vars()

    @patch.dict(os.environ, {"AI_MODEL": "kimi-v1"}, clear=True)
    def test_with_kimi_model(self):
        """Test hook selection based on kimi model name"""
        rid_all_thread_vars()

        result = get_hooks_runtime("TOPSAILAI_HOOK_AFTER_LLM_CHAT", "test content")
        self.assertEqual(result, ["topsailai.ai_base.llm_hooks.hook_after_chat.kimi"])

    @patch.dict(os.environ, {"AI_MODEL": "minimax-01"}, clear=True)
    def test_with_minimax_model(self):
        """Test hook selection based on minimax model name"""
        rid_all_thread_vars()

        result = get_hooks_runtime("TOPSAILAI_HOOK_AFTER_LLM_CHAT", "test content")
        self.assertEqual(result, ["topsailai.ai_base.llm_hooks.hook_after_chat.minimax"])

    @patch.dict(os.environ, {"AI_MODEL": "MiniMax-M2.5"}, clear=True)
    def test_with_minimax_model_before_chat(self):
        """Test hook selection for minimax before chat with MiniMax-M2.5 model"""
        rid_all_thread_vars()

        result = get_hooks_runtime("TOPSAILAI_HOOK_BEFORE_LLM_CHAT", "test content")
        self.assertEqual(result, ["topsailai.ai_base.llm_hooks.hook_before_chat.only_one_system_message"])

    @patch.dict(os.environ, {"AI_MODEL": "gpt-4"}, clear=True)
    def test_with_content_containing_minimax(self):
        """Test hook selection based on minimax keyword in content (when model doesn't match)"""
        rid_all_thread_vars()

        result = get_hooks_runtime("TOPSAILAI_HOOK_AFTER_LLM_CHAT", "minimax")
        self.assertIn("topsailai.ai_base.llm_hooks.hook_after_chat.minimax", result)

    @patch.dict(os.environ, {"AI_MODEL": "gpt-4"}, clear=True)
    def test_with_content_containing_tool_calls_section(self):
        """Test hook selection based on tool_calls_section_begin in content (when model doesn't match)"""
        rid_all_thread_vars()

        result = get_hooks_runtime("TOPSAILAI_HOOK_AFTER_LLM_CHAT", "some text |tool_calls_section_begin| more text")
        self.assertIn("topsailai.ai_base.llm_hooks.hook_after_chat.kimi", result)

    @patch.dict(os.environ, {"AI_MODEL": "gpt-4"}, clear=True)
    def test_no_matching_hook(self):
        """Test when no matching hook is found"""
        rid_all_thread_vars()

        result = get_hooks_runtime("TOPSAILAI_HOOK_AFTER_LLM_CHAT", "some random content")
        self.assertEqual(result, [])

    def test_with_agent_object(self):
        """Test hook selection when agent object is available"""
        rid_all_thread_vars()
        
        mock_agent = MagicMock()
        mock_agent.llm_model.model_name = "kimi-v1"
        set_thread_var(KEY_AGENT_OBJECT, mock_agent)
        
        try:
            result = get_hooks_runtime("TOPSAILAI_HOOK_AFTER_LLM_CHAT", "test content")
            self.assertEqual(result, ["topsailai.ai_base.llm_hooks.hook_after_chat.kimi"])
        finally:
            rid_all_thread_vars()

    @patch.dict(os.environ, {}, clear=True)
    def test_with_no_model(self):
        """Test when no model is available"""
        rid_all_thread_vars()

        result = get_hooks_runtime("TOPSAILAI_HOOK_AFTER_LLM_CHAT", "test content")
        self.assertEqual(result, [])

    @patch.dict(os.environ, {"AI_MODEL": "gpt-4"}, clear=True)
    def test_content_check_only_for_after_llm_chat(self):
        """Test that content-based check only works for TOPSAILAI_HOOK_AFTER_LLM_CHAT"""
        rid_all_thread_vars()

        # Content has 'minimax' but key is BEFORE_LLM_CHAT, so content check should not trigger
        result = get_hooks_runtime("TOPSAILAI_HOOK_BEFORE_LLM_CHAT", "minimax")
        self.assertEqual(result, [])


class TestHookExecute(unittest.TestCase):
    """Test cases for hook_execute function."""

    def setUp(self):
        """Clear thread local storage before each test to ensure test isolation."""
        rid_all_thread_vars()

    @patch.dict(os.environ, {}, clear=True)
    @patch('topsailai.ai_base.llm_hooks.executor.module_tool.get_var')
    @patch('topsailai.ai_base.llm_hooks.executor.get_hooks_runtime')
    @patch('topsailai.ai_base.llm_hooks.executor.env_tool.EnvReaderInstance.get_list_str')
    def test_execute_with_runtime_hooks(self, mock_get_list_str, mock_get_hooks, mock_get_var):
        """Test hook execution with runtime-determined hooks"""
        mock_get_list_str.return_value = None
        mock_get_hooks.return_value = ["topsailai.ai_base.llm_hooks.hook_after_chat.minimax"]

        mock_hook = MagicMock(return_value="modified content")
        mock_get_var.return_value = mock_hook

        result = hook_execute("TOPSAILAI_HOOK_AFTER_LLM_CHAT", "original content")
        self.assertEqual(result, "modified content")
        mock_hook.assert_called_once_with("original content")

    @patch.dict(os.environ, {}, clear=True)
    @patch('topsailai.ai_base.llm_hooks.executor.module_tool.get_var')
    @patch('topsailai.ai_base.llm_hooks.executor.env_tool.EnvReaderInstance.get_list_str')
    def test_execute_with_env_hooks(self, mock_get_list_str, mock_get_var):
        """Test hook execution with environment-configured hooks"""
        mock_get_list_str.return_value = ["topsailai.ai_base.llm_hooks.hook_after_chat.kimi"]

        mock_hook = MagicMock(return_value="env modified content")
        mock_get_var.return_value = mock_hook

        result = hook_execute("TOPSAILAI_HOOK_AFTER_LLM_CHAT", "original content")
        self.assertEqual(result, "env modified content")
        mock_hook.assert_called_once_with("original content")

    @patch.dict(os.environ, {}, clear=True)
    @patch('topsailai.ai_base.llm_hooks.executor.module_tool.get_var')
    @patch('topsailai.ai_base.llm_hooks.executor.get_hooks_runtime')
    @patch('topsailai.ai_base.llm_hooks.executor.env_tool.EnvReaderInstance.get_list_str')
    def test_execute_with_no_hooks(self, mock_get_list_str, mock_get_hooks, mock_get_var):
        """Test hook execution when no hooks are configured"""
        mock_get_list_str.return_value = None
        mock_get_hooks.return_value = []

        result = hook_execute("TOPSAILAI_HOOK_AFTER_LLM_CHAT", "original content")
        self.assertEqual(result, "original content")
        mock_get_var.assert_not_called()

    @patch.dict(os.environ, {}, clear=True)
    @patch('topsailai.ai_base.llm_hooks.executor.module_tool.get_var')
    @patch('topsailai.ai_base.llm_hooks.executor.get_hooks_runtime')
    @patch('topsailai.ai_base.llm_hooks.executor.env_tool.EnvReaderInstance.get_list_str')
    def test_execute_with_multiple_hooks(self, mock_get_list_str, mock_get_hooks, mock_get_var):
        """Test hook execution with multiple hooks"""
        mock_get_list_str.return_value = None
        mock_get_hooks.return_value = [
            "topsailai.ai_base.llm_hooks.hook_after_chat.hook1",
            "topsailai.ai_base.llm_hooks.hook_after_chat.hook2"
        ]

        mock_hook1 = MagicMock(return_value="after hook1")
        mock_hook2 = MagicMock(return_value="after hook2")
        mock_get_var.side_effect = [mock_hook1, mock_hook2]

        result = hook_execute("TOPSAILAI_HOOK_AFTER_LLM_CHAT", "original content")
        self.assertEqual(result, "after hook2")
        self.assertEqual(mock_hook1.call_count, 1)
        self.assertEqual(mock_hook2.call_count, 1)

    @patch.dict(os.environ, {}, clear=True)
    @patch('topsailai.ai_base.llm_hooks.executor.module_tool.get_var')
    @patch('topsailai.ai_base.llm_hooks.executor.get_hooks_runtime')
    @patch('topsailai.ai_base.llm_hooks.executor.env_tool.EnvReaderInstance.get_list_str')
    def test_execute_with_none_hook(self, mock_get_list_str, mock_get_hooks, mock_get_var):
        """Test hook execution when hook function is None"""
        mock_get_list_str.return_value = None
        mock_get_hooks.return_value = ["topsailai.ai_base.llm_hooks.hook_after_chat.hook1"]
        mock_get_var.return_value = None

        result = hook_execute("TOPSAILAI_HOOK_AFTER_LLM_CHAT", "original content")
        self.assertEqual(result, "original content")


if __name__ == '__main__':
    unittest.main()
