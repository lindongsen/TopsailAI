"""
Test module for workspace/agent/ subsystem.

Test Coverage:
- agent_constants.py: DEFAULT_HEAD_TAIL_OFFSET constant
- hooks/base/init.py: get_hooks function
- hooks/post_final_answer.py: call_scripts function

Author: mm-m25
"""

import inspect
import unittest
from unittest.mock import patch, MagicMock


class TestAgentConstants(unittest.TestCase):
    """Test cases for workspace/agent/agent_constants.py"""

    def test_default_head_tail_offset_value(self):
        """Verify DEFAULT_HEAD_TAIL_OFFSET is set to expected value 7."""
        from topsailai.workspace.agent.agent_constants import DEFAULT_HEAD_TAIL_OFFSET
        self.assertEqual(DEFAULT_HEAD_TAIL_OFFSET, 7)

    def test_default_head_tail_offset_type(self):
        """Verify DEFAULT_HEAD_TAIL_OFFSET is an integer."""
        from topsailai.workspace.agent.agent_constants import DEFAULT_HEAD_TAIL_OFFSET
        self.assertIsInstance(DEFAULT_HEAD_TAIL_OFFSET, int)


class TestGetHooks(unittest.TestCase):
    """Test cases for workspace/agent/hooks/base/init.py"""

    def test_get_hooks_returns_list(self):
        """Verify get_hooks returns a list."""
        from topsailai.workspace.agent.hooks.base.init import get_hooks
        result = get_hooks("pre_run")
        self.assertIsInstance(result, list)

    def test_get_hooks_with_valid_prefix(self):
        """Verify get_hooks returns hooks matching the prefix."""
        from topsailai.workspace.agent.hooks.base.init import get_hooks
        result = get_hooks("post_final_answer")
        self.assertIsInstance(result, list)

    def test_get_hooks_with_nonexistent_prefix(self):
        """Verify get_hooks returns empty list for non-existent prefix."""
        from topsailai.workspace.agent.hooks.base.init import get_hooks
        result = get_hooks("nonexistent_hook_prefix_xyz")
        self.assertIsInstance(result, list)

    def test_get_hooks_returns_functions(self):
        """Verify get_hooks returns callable functions."""
        from topsailai.workspace.agent.hooks.base.init import get_hooks
        result = get_hooks("post_final_answer")
        for item in result:
            self.assertTrue(callable(item))

    def test_get_hooks_empty_prefix(self):
        """Verify get_hooks handles empty prefix."""
        from topsailai.workspace.agent.hooks.base.init import get_hooks
        result = get_hooks("")
        self.assertIsInstance(result, list)


class TestCallScripts(unittest.TestCase):
    """Test cases for workspace/agent/hooks/post_final_answer.py"""

    def test_call_scripts_env_key(self):
        """Verify ENV_KEY is set correctly."""
        from topsailai.workspace.agent.hooks.post_final_answer import ENV_KEY
        self.assertEqual(ENV_KEY, "TOPSAILAI_HOOK_SCRIPTS_POST_FINAL_ANSWER")

    def test_call_scripts_is_callable(self):
        """Verify call_scripts function is callable."""
        from topsailai.workspace.agent.hooks.post_final_answer import call_scripts
        self.assertTrue(callable(call_scripts))

    @patch('topsailai.workspace.agent.hooks.post_final_answer.hook_tool')
    def test_call_scripts_with_mock(self, mock_hook_tool):
        """Verify call_scripts calls hook_tool.call_hook_scripts correctly."""
        from topsailai.workspace.agent.hooks.post_final_answer import call_scripts
        
        mock_hook_tool.call_hook_scripts.return_value = {"script1.py": "success"}
        mock_self = MagicMock()
        mock_self.last_message = "Test answer"
        
        result = call_scripts(mock_self)
        
        mock_hook_tool.call_hook_scripts.assert_called_once()
        call_args = mock_hook_tool.call_hook_scripts.call_args
        
        # First arg is positional
        self.assertEqual(call_args[0][0], "TOPSAILAI_HOOK_SCRIPTS_POST_FINAL_ANSWER")
        # Second arg is keyword
        self.assertIn("TOPSAILAI_FINAL_ANSWER", call_args.kwargs.get('env_info', {}))

    @patch('topsailai.workspace.agent.hooks.post_final_answer.hook_tool')
    def test_call_scripts_with_none_message(self, mock_hook_tool):
        """Verify call_scripts handles None last_message."""
        from topsailai.workspace.agent.hooks.post_final_answer import call_scripts
        
        mock_hook_tool.call_hook_scripts.return_value = {}
        mock_self = MagicMock()
        mock_self.last_message = None
        
        result = call_scripts(mock_self)
        mock_hook_tool.call_hook_scripts.assert_called_once()

    @patch('topsailai.workspace.agent.hooks.post_final_answer.hook_tool')
    def test_call_scripts_with_empty_message(self, mock_hook_tool):
        """Verify call_scripts handles empty last_message."""
        from topsailai.workspace.agent.hooks.post_final_answer import call_scripts
        
        mock_hook_tool.call_hook_scripts.return_value = {}
        mock_self = MagicMock()
        mock_self.last_message = ""
        
        result = call_scripts(mock_self)
        mock_hook_tool.call_hook_scripts.assert_called_once()

    @patch('topsailai.workspace.agent.hooks.post_final_answer.hook_tool')
    def test_call_scripts_with_special_characters(self, mock_hook_tool):
        """Verify call_scripts handles special characters in message."""
        from topsailai.workspace.agent.hooks.post_final_answer import call_scripts
        
        mock_hook_tool.call_hook_scripts.return_value = {}
        mock_self = MagicMock()
        mock_self.last_message = 'Special chars: "quotes" \\backslash\\ {braces} [brackets]'
        
        result = call_scripts(mock_self)
        mock_hook_tool.call_hook_scripts.assert_called_once()

    @patch('topsailai.workspace.agent.hooks.post_final_answer.hook_tool')
    def test_call_scripts_with_unicode(self, mock_hook_tool):
        """Verify call_scripts handles unicode characters."""
        from topsailai.workspace.agent.hooks.post_final_answer import call_scripts
        
        mock_hook_tool.call_hook_scripts.return_value = {}
        mock_self = MagicMock()
        mock_self.last_message = "Unicode: 你好世界 🌍 émojis 🎉"
        
        result = call_scripts(mock_self)
        mock_hook_tool.call_hook_scripts.assert_called_once()

    @patch('topsailai.workspace.agent.hooks.post_final_answer.hook_tool')
    def test_call_scripts_with_multiline(self, mock_hook_tool):
        """Verify call_scripts handles multiline messages."""
        from topsailai.workspace.agent.hooks.post_final_answer import call_scripts
        
        mock_hook_tool.call_hook_scripts.return_value = {}
        mock_self = MagicMock()
        mock_self.last_message = "Line 1\nLine 2\nLine 3"
        
        result = call_scripts(mock_self)
        mock_hook_tool.call_hook_scripts.assert_called_once()


class TestHooksDict(unittest.TestCase):
    """Test cases for HOOKS dictionary in post_final_answer.py"""

    def test_hooks_dict_exists(self):
        """Verify HOOKS dictionary exists."""
        from topsailai.workspace.agent.hooks.post_final_answer import HOOKS
        self.assertIsInstance(HOOKS, dict)

    def test_hooks_dict_has_call_scripts(self):
        """Verify HOOKS contains call_scripts key."""
        from topsailai.workspace.agent.hooks.post_final_answer import HOOKS
        self.assertIn("call_scripts", HOOKS)

    def test_hooks_dict_call_scripts_is_callable(self):
        """Verify HOOKS['call_scripts'] is callable."""
        from topsailai.workspace.agent.hooks.post_final_answer import HOOKS
        self.assertTrue(callable(HOOKS["call_scripts"]))


class TestAgentChatBaseImports(unittest.TestCase):
    """Test cases for AgentChatBase imports and basic structure."""

    def test_agent_chat_base_import(self):
        """Verify AgentChatBase can be imported."""
        from topsailai.workspace.agent.agent_chat_base import AgentChatBase
        self.assertTrue(inspect.isclass(AgentChatBase))

    def test_agent_chat_base_has_required_attributes(self):
        """Verify AgentChatBase has required attributes in __init__ signature."""
        from topsailai.workspace.agent.agent_chat_base import AgentChatBase
        
        sig = inspect.signature(AgentChatBase.__init__)
        params = list(sig.parameters.keys())
        
        self.assertIn('hook_instruction', params)
        self.assertIn('ctx_rt_aiagent', params)
        self.assertIn('ctx_rt_instruction', params)

    def test_agent_chat_base_has_properties(self):
        """Verify AgentChatBase has required properties."""
        from topsailai.workspace.agent.agent_chat_base import AgentChatBase
        
        self.assertTrue(hasattr(AgentChatBase, 'agent_name'))
        self.assertTrue(hasattr(AgentChatBase, 'messages'))
        self.assertTrue(hasattr(AgentChatBase, 'ctx_runtime_data'))

    def test_agent_chat_base_has_methods(self):
        """Verify AgentChatBase has required methods."""
        from topsailai.workspace.agent.agent_chat_base import AgentChatBase
        
        self.assertTrue(hasattr(AgentChatBase, 'call_hooks_pre_run'))
        self.assertTrue(hasattr(AgentChatBase, 'call_hook_for_final_answer'))
        self.assertTrue(hasattr(AgentChatBase, 'hook_build_answer'))
        self.assertTrue(hasattr(AgentChatBase, 'hook_for_answer'))


class TestAgentChatImports(unittest.TestCase):
    """Test cases for AgentChat imports and basic structure."""

    def test_agent_chat_import(self):
        """Verify AgentChat can be imported."""
        from topsailai.workspace.agent.agent_shell_base import AgentChat
        self.assertTrue(inspect.isclass(AgentChat))

    def test_agent_chat_inherits_from_base(self):
        """Verify AgentChat inherits from AgentChatBase."""
        from topsailai.workspace.agent.agent_shell_base import AgentChat
        from topsailai.workspace.agent.agent_chat_base import AgentChatBase
        
        self.assertTrue(issubclass(AgentChat, AgentChatBase))

    def test_agent_chat_has_run_method(self):
        """Verify AgentChat has run method."""
        from topsailai.workspace.agent.agent_shell_base import AgentChat
        
        self.assertTrue(hasattr(AgentChat, 'run'))
        self.assertTrue(callable(getattr(AgentChat, 'run')))


if __name__ == '__main__':
    unittest.main()
