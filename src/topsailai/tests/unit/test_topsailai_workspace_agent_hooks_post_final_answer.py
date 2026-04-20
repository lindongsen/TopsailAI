"""
Unit tests for workspace/agent/hooks/post_final_answer.py module.

Test coverage for:
- ENV_KEY constant
- call_scripts() function
- HOOKS dictionary

Author: mm-m25
"""

import pytest
from unittest.mock import patch, MagicMock


class TestEnvKey:
    """Tests for ENV_KEY constant."""

    def test_env_key_value(self):
        """Test ENV_KEY has correct value."""
        from src.topsailai.workspace.agent.hooks.post_final_answer import ENV_KEY

        assert ENV_KEY == "TOPSAILAI_HOOK_SCRIPTS_POST_FINAL_ANSWER"

    def test_env_key_is_string(self):
        """Test ENV_KEY is a string type."""
        from src.topsailai.workspace.agent.hooks.post_final_answer import ENV_KEY

        assert isinstance(ENV_KEY, str)


class TestCallScripts:
    """Tests for call_scripts() function."""

    def test_call_scripts_returns_dict(self):
        """Test call_scripts returns a dictionary."""
        from src.topsailai.workspace.agent.hooks.post_final_answer import call_scripts

        mock_self = MagicMock()
        mock_self.last_message = "test message"

        with patch('src.topsailai.workspace.agent.hooks.post_final_answer.hook_tool') as mock_hook_tool:
            mock_hook_tool.call_hook_scripts.return_value = {}
            result = call_scripts(mock_self)
            assert isinstance(result, dict)

    def test_call_scripts_with_string_message(self):
        """Test call_scripts with string last_message."""
        from src.topsailai.workspace.agent.hooks.post_final_answer import call_scripts

        mock_self = MagicMock()
        mock_self.last_message = "simple string message"

        with patch('src.topsailai.workspace.agent.hooks.post_final_answer.hook_tool') as mock_hook_tool, \
             patch('src.topsailai.workspace.agent.hooks.post_final_answer.json_tool') as mock_json_tool:
            mock_hook_tool.call_hook_scripts.return_value = {}
            mock_json_tool.safe_json_dump.return_value = '"simple string message"'

            result = call_scripts(mock_self)

            mock_json_tool.safe_json_dump.assert_called_once_with("simple string message")
            mock_hook_tool.call_hook_scripts.assert_called_once()

    def test_call_scripts_with_dict_message(self):
        """Test call_scripts with dict last_message."""
        from src.topsailai.workspace.agent.hooks.post_final_answer import call_scripts

        mock_self = MagicMock()
        mock_self.last_message = {"role": "assistant", "content": "hello"}

        with patch('src.topsailai.workspace.agent.hooks.post_final_answer.hook_tool') as mock_hook_tool, \
             patch('src.topsailai.workspace.agent.hooks.post_final_answer.json_tool') as mock_json_tool:
            mock_hook_tool.call_hook_scripts.return_value = {}
            mock_json_tool.safe_json_dump.return_value = '{"role": "assistant", "content": "hello"}'

            result = call_scripts(mock_self)

            mock_json_tool.safe_json_dump.assert_called_once_with({"role": "assistant", "content": "hello"})

    def test_call_scripts_with_empty_message(self):
        """Test call_scripts with empty string last_message."""
        from src.topsailai.workspace.agent.hooks.post_final_answer import call_scripts

        mock_self = MagicMock()
        mock_self.last_message = ""

        with patch('src.topsailai.workspace.agent.hooks.post_final_answer.hook_tool') as mock_hook_tool, \
             patch('src.topsailai.workspace.agent.hooks.post_final_answer.json_tool') as mock_json_tool:
            mock_hook_tool.call_hook_scripts.return_value = {}
            mock_json_tool.safe_json_dump.return_value = '""'

            result = call_scripts(mock_self)

            mock_json_tool.safe_json_dump.assert_called_once_with("")

    def test_call_scripts_with_none_message(self):
        """Test call_scripts with None last_message."""
        from src.topsailai.workspace.agent.hooks.post_final_answer import call_scripts

        mock_self = MagicMock()
        mock_self.last_message = None

        with patch('src.topsailai.workspace.agent.hooks.post_final_answer.hook_tool') as mock_hook_tool, \
             patch('src.topsailai.workspace.agent.hooks.post_final_answer.json_tool') as mock_json_tool:
            mock_hook_tool.call_hook_scripts.return_value = {}
            mock_json_tool.safe_json_dump.return_value = 'null'

            result = call_scripts(mock_self)

            mock_json_tool.safe_json_dump.assert_called_once_with(None)

    def test_call_scripts_with_special_characters(self):
        """Test call_scripts with special characters in message."""
        from src.topsailai.workspace.agent.hooks.post_final_answer import call_scripts

        mock_self = MagicMock()
        mock_self.last_message = "Test with special chars: <>&\"'{}[]"

        with patch('src.topsailai.workspace.agent.hooks.post_final_answer.hook_tool') as mock_hook_tool, \
             patch('src.topsailai.workspace.agent.hooks.post_final_answer.json_tool') as mock_json_tool:
            mock_hook_tool.call_hook_scripts.return_value = {}
            mock_json_tool.safe_json_dump.return_value = '"Test with special chars"'

            result = call_scripts(mock_self)

            mock_json_tool.safe_json_dump.assert_called_once()

    def test_call_scripts_with_unicode_content(self):
        """Test call_scripts with unicode content in message."""
        from src.topsailai.workspace.agent.hooks.post_final_answer import call_scripts

        mock_self = MagicMock()
        mock_self.last_message = "Hello 世界 🌍 émojis: 🎉"

        with patch('src.topsailai.workspace.agent.hooks.post_final_answer.hook_tool') as mock_hook_tool, \
             patch('src.topsailai.workspace.agent.hooks.post_final_answer.json_tool') as mock_json_tool:
            mock_hook_tool.call_hook_scripts.return_value = {}
            mock_json_tool.safe_json_dump.return_value = '"Hello 世界 🌍"'

            result = call_scripts(mock_self)

            mock_json_tool.safe_json_dump.assert_called_once_with("Hello 世界 🌍 émojis: 🎉")

    def test_call_scripts_env_key_passed(self):
        """Test call_scripts passes correct ENV_KEY to hook_tool."""
        from src.topsailai.workspace.agent.hooks.post_final_answer import call_scripts, ENV_KEY

        mock_self = MagicMock()
        mock_self.last_message = "test"

        with patch('src.topsailai.workspace.agent.hooks.post_final_answer.hook_tool') as mock_hook_tool, \
             patch('src.topsailai.workspace.agent.hooks.post_final_answer.json_tool') as mock_json_tool:
            mock_hook_tool.call_hook_scripts.return_value = {}
            mock_json_tool.safe_json_dump.return_value = '"test"'

            call_scripts(mock_self)

            call_args = mock_hook_tool.call_hook_scripts.call_args
            assert call_args[0][0] == ENV_KEY

    def test_call_scripts_env_info_structure(self):
        """Test call_scripts passes correct env_info structure."""
        from src.topsailai.workspace.agent.hooks.post_final_answer import call_scripts

        mock_self = MagicMock()
        mock_self.last_message = "test message"

        with patch('src.topsailai.workspace.agent.hooks.post_final_answer.hook_tool') as mock_hook_tool, \
             patch('src.topsailai.workspace.agent.hooks.post_final_answer.json_tool') as mock_json_tool:
            mock_hook_tool.call_hook_scripts.return_value = {}
            mock_json_tool.safe_json_dump.return_value = '"test message"'

            call_scripts(mock_self)

            # Check that call_hook_scripts was called with env_info containing TOPSAILAI_FINAL_ANSWER
            mock_hook_tool.call_hook_scripts.assert_called_once()
            call_kwargs = mock_hook_tool.call_hook_scripts.call_args[1]
            assert "env_info" in call_kwargs
            assert "TOPSAILAI_FINAL_ANSWER" in call_kwargs["env_info"]

    def test_call_scripts_hook_returns_results(self):
        """Test call_scripts returns hook execution results."""
        from src.topsailai.workspace.agent.hooks.post_final_answer import call_scripts

        mock_self = MagicMock()
        mock_self.last_message = "test"

        with patch('src.topsailai.workspace.agent.hooks.post_final_answer.hook_tool') as mock_hook_tool, \
             patch('src.topsailai.workspace.agent.hooks.post_final_answer.json_tool') as mock_json_tool:
            mock_hook_tool.call_hook_scripts.return_value = {
                "script1.py": (0, "success", ""),
                "script2.py": (0, "done", "")
            }
            mock_json_tool.safe_json_dump.return_value = '"test"'

            result = call_scripts(mock_self)

            assert "script1.py" in result
            assert "script2.py" in result


class TestHooks:
    """Tests for HOOKS dictionary."""

    def test_hooks_is_dict(self):
        """Test HOOKS is a dictionary."""
        from src.topsailai.workspace.agent.hooks.post_final_answer import HOOKS

        assert isinstance(HOOKS, dict)

    def test_hooks_contains_call_scripts(self):
        """Test HOOKS contains call_scripts key."""
        from src.topsailai.workspace.agent.hooks.post_final_answer import HOOKS, call_scripts

        assert "call_scripts" in HOOKS
        assert HOOKS["call_scripts"] == call_scripts

    def test_hooks_call_scripts_is_callable(self):
        """Test HOOKS['call_scripts'] is a callable function."""
        from src.topsailai.workspace.agent.hooks.post_final_answer import HOOKS

        assert callable(HOOKS["call_scripts"])

    def test_hooks_single_entry(self):
        """Test HOOKS has only one entry."""
        from src.topsailai.workspace.agent.hooks.post_final_answer import HOOKS

        assert len(HOOKS) == 1
