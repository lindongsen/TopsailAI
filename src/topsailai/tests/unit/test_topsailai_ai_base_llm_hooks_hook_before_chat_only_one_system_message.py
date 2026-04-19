"""
Unit tests for topsailai.ai_base.llm_hooks.hook_before_chat.only_one_system_message module.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-04-19
Purpose: Test hook to ensure only one system message exists in conversation
"""

import pytest
from topsailai.ai_base.llm_hooks.hook_before_chat.only_one_system_message import (
    hook_execute,
)


class TestHookExecute:
    """Test hook_execute function"""

    def test_multiple_system_messages_merged(self):
        """Test that when multiple system messages exist, they are merged into one"""
        messages = [
            {"role": "system", "content": "First system message"},
            {"role": "user", "content": "User message"},
            {"role": "system", "content": "Second system message"},
            {"role": "assistant", "content": "Assistant response"},
        ]
        result = hook_execute(messages)
        
        system_messages = [m for m in result if m.get("role") == "system"]
        assert len(system_messages) == 1
        # Merged content should contain both messages
        assert "First system message" in system_messages[0]["content"]
        assert "Second system message" in system_messages[0]["content"]

    def test_single_system_message_unchanged(self):
        """Test that a single system message is not modified"""
        messages = [
            {"role": "system", "content": "Only system message"},
            {"role": "user", "content": "User message"},
        ]
        result = hook_execute(messages)
        
        assert len(result) == 2
        assert result[0]["role"] == "system"

    def test_no_system_message_adds_default(self):
        """Test that when no system message exists, a default one is added"""
        messages = [
            {"role": "user", "content": "User message"},
            {"role": "assistant", "content": "Assistant response"},
        ]
        result = hook_execute(messages)
        
        system_messages = [m for m in result if m.get("role") == "system"]
        assert len(system_messages) == 1

    def test_system_message_not_first(self):
        """Test handling when system message is not the first"""
        messages = [
            {"role": "user", "content": "User message"},
            {"role": "system", "content": "System message"},
        ]
        result = hook_execute(messages)
        
        system_messages = [m for m in result if m.get("role") == "system"]
        assert len(system_messages) == 1

    def test_empty_messages_list_adds_default(self):
        """Test with empty messages list adds default system message"""
        result = hook_execute([])
        
        # Should add a default system message
        assert len(result) == 1
        assert result[0]["role"] == "system"

    def test_messages_without_role_key(self):
        """Test handling of messages without role key"""
        messages = [
            {"content": "Message without role"},
            {"role": "system", "content": "System message"},
        ]
        result = hook_execute(messages)
        
        # Should handle gracefully
        assert isinstance(result, list)

    def test_system_message_with_additional_fields(self):
        """Test system message with additional metadata fields"""
        messages = [
            {"role": "system", "content": "System message", "name": "sys", "metadata": {"key": "value"}},
            {"role": "system", "content": "Duplicate system", "name": "sys2"},
            {"role": "user", "content": "User message"},
        ]
        result = hook_execute(messages)
        
        system_messages = [m for m in result if m.get("role") == "system"]
        assert len(system_messages) == 1
        # Content should be merged
        assert "System message" in system_messages[0]["content"]


class TestHookExecuteEdgeCases:
    """Test hook_execute edge cases"""

    def test_all_system_messages_merged(self):
        """Test with multiple system messages throughout conversation"""
        messages = [
            {"role": "system", "content": "First"},
            {"role": "user", "content": "User 1"},
            {"role": "system", "content": "Second"},
            {"role": "assistant", "content": "Assistant 1"},
            {"role": "system", "content": "Third"},
        ]
        result = hook_execute(messages)
        
        system_messages = [m for m in result if m.get("role") == "system"]
        assert len(system_messages) == 1
        # All content should be merged
        assert "First" in system_messages[0]["content"]
        assert "Second" in system_messages[0]["content"]
        assert "Third" in system_messages[0]["content"]

    def test_only_system_messages(self):
        """Test with only system messages"""
        messages = [
            {"role": "system", "content": "First"},
            {"role": "system", "content": "Second"},
        ]
        result = hook_execute(messages)
        
        system_messages = [m for m in result if m.get("role") == "system"]
        assert len(system_messages) == 1

    def test_none_input(self):
        """Test with None input"""
        result = hook_execute(None)
        assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
