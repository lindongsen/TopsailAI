"""
Test module for workspace/plugin_instruction/ module.

This module provides comprehensive unit tests for the plugin instruction system,
including agent, cache, env, skill, skill_repo, and stat components.

Author: AI
Maintainer: AI
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock, mock_open


class TestPluginInstructionCache(unittest.TestCase):
    """Test cases for workspace/plugin_instruction/base/cache.py module."""

    def test_set_ai_agent_with_valid_agent(self):
        """Test setting a valid AI agent to the global cache."""
        from topsailai.workspace.plugin_instruction.base.cache import (
            set_ai_agent,
            get_ai_agent,
            g_ai_agent,
        )
        # Reset global state
        import topsailai.workspace.plugin_instruction.base.cache as cache_module
        cache_module.g_ai_agent = None

        mock_agent = MagicMock()
        mock_agent.messages = [{"content": "system"}, {"content": "env"}]

        set_ai_agent(mock_agent)

        result = get_ai_agent()
        self.assertIsNotNone(result)
        self.assertEqual(result, mock_agent)

        # Cleanup
        cache_module.g_ai_agent = None

    def test_set_ai_agent_with_none_preserves_existing(self):
        """Test setting None to the global cache preserves existing value.
        
        Note: set_ai_agent has a guard 'if agent:' that prevents setting None.
        The global variable remains unchanged when None is passed.
        """
        from topsailai.workspace.plugin_instruction.base.cache import (
            set_ai_agent,
            get_ai_agent,
        )
        import topsailai.workspace.plugin_instruction.base.cache as cache_module
        cache_module.g_ai_agent = MagicMock()

        set_ai_agent(None)

        # The global remains unchanged due to 'if agent:' guard
        result = get_ai_agent()
        self.assertIsNotNone(result)

        # Cleanup
        cache_module.g_ai_agent = None

    def test_get_ai_agent_when_not_set(self):
        """Test getting AI agent when it has not been set."""
        from topsailai.workspace.plugin_instruction.base.cache import (
            get_ai_agent,
        )
        import topsailai.workspace.plugin_instruction.base.cache as cache_module
        cache_module.g_ai_agent = None

        result = get_ai_agent()
        self.assertIsNone(result)

    def test_get_ai_agent_returns_agent_instance(self):
        """Test that get_ai_agent returns the correct agent instance."""
        from topsailai.workspace.plugin_instruction.base.cache import (
            set_ai_agent,
            get_ai_agent,
        )
        import topsailai.workspace.plugin_instruction.base.cache as cache_module
        cache_module.g_ai_agent = None

        mock_agent = MagicMock()
        mock_agent.messages = []

        set_ai_agent(mock_agent)
        result = get_ai_agent()

        self.assertIs(result, mock_agent)

        # Cleanup
        cache_module.g_ai_agent = None


class TestPluginInstructionEnv(unittest.TestCase):
    """Test cases for workspace/plugin_instruction/env.py module."""

    def test_set_env_with_valid_key_value(self):
        """Test setting a valid environment variable."""
        from topsailai.workspace.plugin_instruction.env import set_env

        test_key = "TOPSAILAI_TEST_KEY"
        test_value = "test_value_123"

        # Clean up before test
        if test_key in os.environ:
            del os.environ[test_key]

        set_env(test_key, test_value)

        self.assertEqual(os.environ.get(test_key), test_value)

        # Cleanup
        if test_key in os.environ:
            del os.environ[test_key]

    def test_set_env_converts_to_string(self):
        """Test that set_env converts key and value to strings."""
        from topsailai.workspace.plugin_instruction.env import set_env

        test_key = 12345
        test_value = 67890

        set_env(test_key, test_value)

        self.assertEqual(os.environ.get("12345"), "67890")

        # Cleanup
        if "12345" in os.environ:
            del os.environ["12345"]

    def test_set_env_with_empty_key(self):
        """Test setting environment with empty key."""
        from topsailai.workspace.plugin_instruction.env import set_env

        # Should not raise exception
        set_env("", "value")

    def test_get_env_with_existing_key(self):
        """Test getting an existing environment variable."""
        from topsailai.workspace.plugin_instruction.env import get_env

        test_key = "PATH"
        result = get_env(test_key)

        self.assertIsNotNone(result)
        self.assertIsInstance(result, str)

    def test_get_env_with_nonexistent_key(self):
        """Test getting a non-existent environment variable."""
        from topsailai.workspace.plugin_instruction.env import get_env

        result = get_env("TOPSAILAI_NONEXISTENT_KEY_12345")
        self.assertIsNone(result)

    def test_get_env_converts_key_to_string(self):
        """Test that get_env converts key to string."""
        from topsailai.workspace.plugin_instruction.env import get_env

        result = get_env(12345)
        self.assertIsNone(result)

    def test_env_instructions_dict_exists(self):
        """Test that INSTRUCTIONS dict exists with correct keys."""
        from topsailai.workspace.plugin_instruction.env import INSTRUCTIONS

        self.assertIsInstance(INSTRUCTIONS, dict)
        self.assertIn("set", INSTRUCTIONS)
        self.assertIn("get", INSTRUCTIONS)
        self.assertTrue(callable(INSTRUCTIONS["set"]))
        self.assertTrue(callable(INSTRUCTIONS["get"]))


class TestPluginInstructionAgent(unittest.TestCase):
    """Test cases for workspace/plugin_instruction/agent.py module."""

    def test_instructions_dict_exists(self):
        """Test that INSTRUCTIONS dict exists with correct keys."""
        from topsailai.workspace.plugin_instruction.agent import INSTRUCTIONS

        self.assertIsInstance(INSTRUCTIONS, dict)
        self.assertIn("system_prompt", INSTRUCTIONS)
        self.assertIn("env_prompt", INSTRUCTIONS)
        self.assertIn("tool_prompt", INSTRUCTIONS)
        self.assertIn("tools", INSTRUCTIONS)

    def test_instructions_are_callable(self):
        """Test that all instruction functions are callable."""
        from topsailai.workspace.plugin_instruction.agent import INSTRUCTIONS

        for key, func in INSTRUCTIONS.items():
            self.assertTrue(
                callable(func),
                f"INSTRUCTIONS['{key}'] should be callable"
            )

    def test_get_system_prompt_with_no_agent(self):
        """Test get_system_prompt when no agent is set."""
        from topsailai.workspace.plugin_instruction.agent import get_system_prompt
        from topsailai.workspace.plugin_instruction.base.cache import (
            set_ai_agent,
        )
        import topsailai.workspace.plugin_instruction.base.cache as cache_module
        cache_module.g_ai_agent = None

        # Should not raise exception
        result = get_system_prompt()
        self.assertIsNone(result)

    def test_get_env_prompt_with_no_agent(self):
        """Test get_env_prompt when no agent is set."""
        from topsailai.workspace.plugin_instruction.agent import get_env_prompt
        import topsailai.workspace.plugin_instruction.base.cache as cache_module
        cache_module.g_ai_agent = None

        # Should not raise exception
        result = get_env_prompt()
        self.assertIsNone(result)

    def test_get_tool_prompt_with_no_agent(self):
        """Test get_tool_prompt when no agent is set."""
        from topsailai.workspace.plugin_instruction.agent import get_tool_prompt
        import topsailai.workspace.plugin_instruction.base.cache as cache_module
        cache_module.g_ai_agent = None

        # Should not raise exception
        result = get_tool_prompt()
        self.assertIsNone(result)

    def test_get_tools_with_no_agent(self):
        """Test get_tools when no agent is set."""
        from topsailai.workspace.plugin_instruction.agent import get_tools
        import topsailai.workspace.plugin_instruction.base.cache as cache_module
        cache_module.g_ai_agent = None

        # Should not raise exception
        result = get_tools()
        self.assertIsNone(result)

    def test_get_system_prompt_with_mock_agent(self):
        """Test get_system_prompt with a mock agent."""
        from topsailai.workspace.plugin_instruction.agent import get_system_prompt
        from topsailai.workspace.plugin_instruction.base.cache import (
            set_ai_agent,
        )
        import topsailai.workspace.plugin_instruction.base.cache as cache_module

        mock_agent = MagicMock()
        mock_agent.messages = [
            {"content": "You are a helpful assistant"},
            {"content": "Environment info"},
            {"content": "Tools info"},
        ]

        cache_module.g_ai_agent = mock_agent

        # Should not raise exception
        result = get_system_prompt()
        self.assertIsNone(result)

        # Cleanup
        cache_module.g_ai_agent = None


class TestPluginInstructionSkill(unittest.TestCase):
    """Test cases for workspace/plugin_instruction/skill.py module."""

    def test_instructions_dict_exists(self):
        """Test that INSTRUCTIONS dict exists with correct keys."""
        from topsailai.workspace.plugin_instruction.skill import INSTRUCTIONS

        self.assertIsInstance(INSTRUCTIONS, dict)
        self.assertIn("show", INSTRUCTIONS)
        self.assertIn("load", INSTRUCTIONS)
        self.assertIn("unload", INSTRUCTIONS)
        self.assertIn("hooks", INSTRUCTIONS)

    def test_instructions_are_callable(self):
        """Test that all instruction functions are callable."""
        from topsailai.workspace.plugin_instruction.skill import INSTRUCTIONS

        for key, func in INSTRUCTIONS.items():
            self.assertTrue(
                callable(func),
                f"INSTRUCTIONS['{key}'] should be callable"
            )

    def test_show_skills_with_no_skills(self):
        """Test show_skills when no skills are loaded."""
        from topsailai.workspace.plugin_instruction.skill import show_skills

        # Should not raise exception
        show_skills()

    def test_show_skills_with_word_filter(self):
        """Test show_skills with word filter."""
        from topsailai.workspace.plugin_instruction.skill import show_skills

        # Should not raise exception
        show_skills(word="test")

    def test_show_hooks(self):
        """Test show_hooks function."""
        from topsailai.workspace.plugin_instruction.skill import show_hooks

        # Should not raise exception
        show_hooks()


class TestPluginInstructionSkillRepo(unittest.TestCase):
    """Test cases for workspace/plugin_instruction/skill_repo.py module."""

    def test_instructions_dict_exists(self):
        """Test that INSTRUCTIONS dict exists with correct keys."""
        from topsailai.workspace.plugin_instruction.skill_repo import INSTRUCTIONS

        self.assertIsInstance(INSTRUCTIONS, dict)
        self.assertIn("list", INSTRUCTIONS)
        self.assertIn("install", INSTRUCTIONS)
        self.assertIn("uninstall", INSTRUCTIONS)

    def test_instructions_are_callable(self):
        """Test that all instruction functions are callable."""
        from topsailai.workspace.plugin_instruction.skill_repo import INSTRUCTIONS

        for key, func in INSTRUCTIONS.items():
            self.assertTrue(
                callable(func),
                f"INSTRUCTIONS['{key}'] should be callable"
            )


class TestPluginInstructionStat(unittest.TestCase):
    """Test cases for workspace/plugin_instruction/stat.py module."""

    def test_instructions_dict_exists(self):
        """Test that INSTRUCTIONS dict exists with correct keys."""
        from topsailai.workspace.plugin_instruction.stat import INSTRUCTIONS

        self.assertIsInstance(INSTRUCTIONS, dict)
        self.assertIn("tool_call", INSTRUCTIONS)
        self.assertIn("tool_call_errors", INSTRUCTIONS)
        self.assertIn("tool_call_reset", INSTRUCTIONS)
        self.assertIn("tool_call_log", INSTRUCTIONS)

    def test_instructions_are_callable(self):
        """Test that all instruction functions are callable."""
        from topsailai.workspace.plugin_instruction.stat import INSTRUCTIONS

        for key, func in INSTRUCTIONS.items():
            self.assertTrue(
                callable(func),
                f"INSTRUCTIONS['{key}'] should be callable"
            )

    def test_show_tool_call_stat_no_data(self):
        """Test show_tool_call_stat with no statistics."""
        from topsailai.workspace.plugin_instruction.stat import show_tool_call_stat

        # Should not raise exception
        show_tool_call_stat()

    def test_show_tool_call_stat_with_tool_name(self):
        """Test show_tool_call_stat with a specific tool name."""
        from topsailai.workspace.plugin_instruction.stat import show_tool_call_stat

        # Should not raise exception
        show_tool_call_stat(tool_name="nonexistent_tool_12345")

    def test_show_tool_call_errors_no_data(self):
        """Test show_tool_call_errors with no errors."""
        from topsailai.workspace.plugin_instruction.stat import show_tool_call_errors

        # Should not raise exception
        show_tool_call_errors()

    def test_show_tool_call_errors_with_tool_name(self):
        """Test show_tool_call_errors with a specific tool name."""
        from topsailai.workspace.plugin_instruction.stat import show_tool_call_errors

        # Should not raise exception
        show_tool_call_errors(tool_name="nonexistent_tool_12345")

    def test_log_tool_call(self):
        """Test log_tool_call function."""
        from topsailai.workspace.plugin_instruction.stat import log_tool_call

        # Should not raise exception
        log_tool_call()


class TestPluginInstructionBaseInit(unittest.TestCase):
    """Test cases for workspace/plugin_instruction/base/init.py module."""

    def test_instructions_loaded(self):
        """Test that INSTRUCTIONS dict is loaded from modules."""
        from topsailai.workspace.plugin_instruction.base.init import INSTRUCTIONS

        self.assertIsInstance(INSTRUCTIONS, dict)

    def test_expand_plugin_instructions_no_env(self):
        """Test expand_plugin_instructions with no env variable."""
        from topsailai.workspace.plugin_instruction.base.init import (
            expand_plugin_instructions,
        )

        # Should not raise exception
        expand_plugin_instructions()

    @patch.dict(os.environ, {"TOPSAILAI_PLUGIN_INSTRUCTIONS": ""})
    def test_expand_plugin_instructions_empty_env(self):
        """Test expand_plugin_instructions with empty env variable."""
        from topsailai.workspace.plugin_instruction.base.init import (
            expand_plugin_instructions,
        )

        # Should not raise exception
        expand_plugin_instructions()

    @patch.dict(os.environ, {"TOPSAILAI_PLUGIN_INSTRUCTIONS": "nonexistent.path"})
    def test_expand_plugin_instructions_invalid_path(self):
        """Test expand_plugin_instructions with invalid plugin path.
        
        The function raises TypeError when path is invalid.
        """
        from topsailai.workspace.plugin_instruction.base.init import (
            expand_plugin_instructions,
        )

        # Should raise TypeError due to invalid path
        with self.assertRaises(TypeError):
            expand_plugin_instructions()


if __name__ == "__main__":
    unittest.main()
