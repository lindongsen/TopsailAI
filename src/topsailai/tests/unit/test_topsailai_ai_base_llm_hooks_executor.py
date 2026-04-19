"""
Unit tests for topsailai.ai_base.llm_hooks.executor module.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-04-19
Purpose: Test LLM hooks executor functionality
"""

import pytest
from unittest.mock import patch, MagicMock

from src.topsailai.ai_base.llm_hooks.executor import (
    get_hooks_runtime,
    hook_execute,
)


class TestGetHooksRuntime:
    """Test get_hooks_runtime function"""
    
    def test_with_kimi_model_after_chat_hook(self):
        """Test runtime hook selection for kimi model with after chat hook"""
        result = get_hooks_runtime("TOPSAILAI_HOOK_AFTER_LLM_CHAT", "some content")
        assert "topsailai.ai_base.llm_hooks.hook_after_chat.kimi" in result
    
    def test_with_kimi_model_before_chat_hook(self):
        """Test runtime hook selection for kimi model with before chat hook returns empty"""
        result = get_hooks_runtime("TOPSAILAI_HOOK_BEFORE_LLM_CHAT", "some content")
        assert result == []
    
    def test_with_minimax_model_after_chat_hook(self):
        """Test runtime hook selection for minimax model with after chat hook"""
        with patch('topsailai.ai_base.llm_hooks.executor.env_tool.EnvReaderInstance') as mock_env:
            mock_env.get.return_value = "minimax-model"
            result = get_hooks_runtime("TOPSAILAI_HOOK_AFTER_LLM_CHAT", "some content")
            assert "topsailai.ai_base.llm_hooks.hook_after_chat.minimax" in result
    
    def test_with_minimax_model_before_chat_hook(self):
        """Test runtime hook selection for minimax model with before chat hook"""
        with patch('topsailai.ai_base.llm_hooks.executor.env_tool.EnvReaderInstance') as mock_env:
            mock_env.get.return_value = "MiniMax-M2.5"
            result = get_hooks_runtime("TOPSAILAI_HOOK_BEFORE_LLM_CHAT", "some content")
            assert "topsailai.ai_base.llm_hooks.hook_before_chat.only_one_system_message" in result
    
    def test_with_content_containing_tool_calls_section(self):
        """Test hook selection based on content pattern"""
        result = get_hooks_runtime("TOPSAILAI_HOOK_AFTER_LLM_CHAT", "|tool_calls_section_begin|")
        assert "topsailai.ai_base.llm_hooks.hook_after_chat.kimi" in result
    
    def test_with_content_containing_minimax(self):
        """Test hook selection based on minimax keyword in content"""
        with patch('topsailai.ai_base.llm_hooks.executor.env_tool.EnvReaderInstance') as mock_env:
            mock_env.get.return_value = None
            result = get_hooks_runtime("TOPSAILAI_HOOK_AFTER_LLM_CHAT", "minimax")
            assert "topsailai.ai_base.llm_hooks.hook_after_chat.minimax" in result
    
    def test_with_no_matching_hook(self):
        """Test returns empty list when no hook matches"""
        with patch('topsailai.ai_base.llm_hooks.executor.env_tool.EnvReaderInstance') as mock_env:
            mock_env.get.return_value = None
            result = get_hooks_runtime("TOPSAILAI_HOOK_UNKNOWN", "some content")
            assert result == []
    
    def test_with_empty_content(self):
        """Test with empty content string returns kimi hook by default"""
        result = get_hooks_runtime("TOPSAILAI_HOOK_AFTER_LLM_CHAT", "")
        # Empty content defaults to kimi hook
        assert "topsailai.ai_base.llm_hooks.hook_after_chat.kimi" in result


class TestHookExecute:
    """Test hook_execute function"""
    
    def test_execute_with_env_var_hooks(self):
        """Test hook execution with hooks from environment variable"""
        with patch('topsailai.ai_base.llm_hooks.executor.env_tool.EnvReaderInstance') as mock_env:
            mock_env.get_list_str.return_value = ["topsailai.ai_base.llm_hooks.hook_after_chat.minimax"]
            mock_env.get.return_value = None
            
            with patch('topsailai.ai_base.llm_hooks.executor.module_tool.get_var') as mock_get_var:
                mock_hook = MagicMock(return_value="modified content")
                mock_get_var.return_value = mock_hook
                
                result = hook_execute("TOPSAILAI_HOOK_AFTER_LLM_CHAT", "original content")
                assert result == "modified content"
                mock_hook.assert_called_once_with("original content")
    
    def test_execute_with_runtime_hooks(self):
        """Test hook execution with runtime-determined hooks"""
        with patch('topsailai.ai_base.llm_hooks.executor.env_tool.EnvReaderInstance') as mock_env:
            mock_env.get_list_str.return_value = None
            mock_env.get.return_value = None
            
            with patch('topsailai.ai_base.llm_hooks.executor.module_tool.get_var') as mock_get_var:
                mock_hook = MagicMock(return_value="modified content")
                mock_get_var.return_value = mock_hook
                
                result = hook_execute("TOPSAILAI_HOOK_AFTER_LLM_CHAT", "original content")
                assert result == "modified content"
    
    def test_execute_with_no_hooks(self):
        """Test hook execution returns original content when no hooks configured"""
        with patch('topsailai.ai_base.llm_hooks.executor.env_tool.EnvReaderInstance') as mock_env:
            mock_env.get_list_str.return_value = None
            mock_env.get.return_value = None
            
            result = hook_execute("TOPSAILAI_HOOK_AFTER_LLM_CHAT", "original content")
            assert result == "original content"
    
    def test_execute_with_list_content(self):
        """Test hook execution with list content"""
        with patch('topsailai.ai_base.llm_hooks.executor.env_tool.EnvReaderInstance') as mock_env:
            mock_env.get_list_str.return_value = None
            mock_env.get.return_value = None
            
            content_list = [{"step_name": "thought", "raw_text": "hello"}]
            result = hook_execute("TOPSAILAI_HOOK_AFTER_LLM_CHAT", content_list)
            assert result == content_list
    
    def test_execute_with_multiple_hooks(self):
        """Test hook execution chains multiple hooks"""
        with patch('topsailai.ai_base.llm_hooks.executor.env_tool.EnvReaderInstance') as mock_env:
            mock_env.get_list_str.return_value = [
                "topsailai.ai_base.llm_hooks.hook_after_chat.kimi",
                "topsailai.ai_base.llm_hooks.hook_after_chat.minimax"
            ]
            mock_env.get.return_value = None
            
            with patch('topsailai.ai_base.llm_hooks.executor.module_tool.get_var') as mock_get_var:
                mock_hook1 = MagicMock(side_effect=lambda x: x + "_after_hook1")
                mock_hook2 = MagicMock(side_effect=lambda x: x + "_after_hook2")
                
                def get_var_side_effect(module_path, var_name):
                    if "kimi" in module_path:
                        return mock_hook1
                    return mock_hook2
                
                mock_get_var.side_effect = get_var_side_effect
                
                result = hook_execute("TOPSAILAI_HOOK_AFTER_LLM_CHAT", "content")
                assert result == "content_after_hook1_after_hook2"


class TestHookExecuteEdgeCases:
    """Test hook_execute edge cases"""
    
    def test_execute_with_none_hook_function(self):
        """Test hook execution skips hooks that return None"""
        with patch('topsailai.ai_base.llm_hooks.executor.env_tool.EnvReaderInstance') as mock_env:
            mock_env.get_list_str.return_value = ["some.hook.path"]
            mock_env.get.return_value = None
            
            with patch('topsailai.ai_base.llm_hooks.executor.module_tool.get_var') as mock_get_var:
                mock_get_var.return_value = None
                
                result = hook_execute("TOPSAILAI_HOOK_AFTER_LLM_CHAT", "content")
                assert result == "content"
    
    def test_execute_with_empty_hook_list(self):
        """Test hook execution with empty hook list"""
        with patch('topsailai.ai_base.llm_hooks.executor.env_tool.EnvReaderInstance') as mock_env:
            mock_env.get_list_str.return_value = []
            mock_env.get.return_value = None
            
            result = hook_execute("TOPSAILAI_HOOK_AFTER_LLM_CHAT", "content")
            assert result == "content"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
