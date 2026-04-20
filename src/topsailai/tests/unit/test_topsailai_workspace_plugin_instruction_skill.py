"""
Unit tests for workspace/plugin_instruction/skill.py module.

This module tests the skill instruction handlers for managing skills and hooks.

Author: mm-m25
Created: 2026-04-19
"""

import unittest
from unittest.mock import (
    MagicMock,
    patch,
)


class TestShowSkills(unittest.TestCase):
    """Test cases for show_skills() function."""

    def setUp(self):
        """Set up test fixtures."""
        self.skill_tool_patcher = patch(
            'topsailai.workspace.plugin_instruction.skill.skill_tool'
        )
        self.mock_skill_tool = self.skill_tool_patcher.start()

    def tearDown(self):
        """Clean up test fixtures."""
        self.skill_tool_patcher.stop()

    def test_show_skills_no_skills(self):
        """Test show_skills when no skills available."""
        self.mock_skill_tool.get_skills_from_cache.return_value = []

        from topsailai.workspace.plugin_instruction.skill import show_skills
        
        with patch('builtins.print') as mock_print:
            show_skills()
            mock_print.assert_not_called()

    def test_show_skills_all_skills(self):
        """Test show_skills displays all skills when no filter."""
        mock_skill1 = MagicMock()
        mock_skill1.name = "skill1"
        mock_skill1.__str__ = MagicMock(return_value="Skill1: description")
        
        mock_skill2 = MagicMock()
        mock_skill2.name = "skill2"
        mock_skill2.__str__ = MagicMock(return_value="Skill2: description")
        
        self.mock_skill_tool.get_skills_from_cache.return_value = [mock_skill1, mock_skill2]

        from topsailai.workspace.plugin_instruction.skill import show_skills
        
        with patch('builtins.print') as mock_print:
            show_skills()
            # Should print header and 2 skills
            self.assertGreater(mock_print.call_count, 0)

    def test_show_skills_with_filter_match(self):
        """Test show_skills with matching filter word."""
        mock_skill = MagicMock()
        mock_skill.name = "python_skill"
        mock_skill.__str__ = MagicMock(return_value="PythonSkill: description")
        
        self.mock_skill_tool.get_skills_from_cache.return_value = [mock_skill]

        from topsailai.workspace.plugin_instruction.skill import show_skills
        
        with patch('builtins.print') as mock_print:
            show_skills(word="python")
            mock_skill.__str__.assert_called()

    def test_show_skills_with_filter_no_match(self):
        """Test show_skills with non-matching filter word."""
        mock_skill = MagicMock()
        mock_skill.name = "python_skill"
        mock_skill.__str__ = MagicMock(return_value="PythonSkill: description")
        
        self.mock_skill_tool.get_skills_from_cache.return_value = [mock_skill]

        from topsailai.workspace.plugin_instruction.skill import show_skills
        
        with patch('builtins.print') as mock_print:
            show_skills(word="java")
            # Should not print skill since name doesn't contain "java"
            mock_skill.__str__.assert_not_called()


class TestUnloadSkill(unittest.TestCase):
    """Test cases for unload_skill() function."""

    def setUp(self):
        """Set up test fixtures."""
        self.skill_tool_patcher = patch(
            'topsailai.workspace.plugin_instruction.skill.skill_tool'
        )
        self.mock_skill_tool = self.skill_tool_patcher.start()
        
        self.cache_patcher = patch(
            'topsailai.workspace.plugin_instruction.skill.get_ai_agent'
        )
        self.mock_get_ai_agent = self.cache_patcher.start()

    def tearDown(self):
        """Clean up test fixtures."""
        self.skill_tool_patcher.stop()
        self.cache_patcher.stop()

    def test_unload_skill_success(self):
        """Test successful skill unload."""
        self.mock_skill_tool.get_skills_from_cache.return_value = ["other_skill"]
        mock_agent = MagicMock()
        self.mock_get_ai_agent.return_value = mock_agent

        from topsailai.workspace.plugin_instruction.skill import unload_skill
        
        with patch('builtins.print') as mock_print:
            unload_skill("/path/to/skill")
            
            self.mock_skill_tool.unload_skill.assert_called_once_with("/path/to/skill")
            mock_agent.remove_tools.assert_not_called()
            mock_agent.reload_tool_prompt.assert_called_once()
            mock_print.assert_called_with("OK")

    def test_unload_skill_last_skill_removes_tool(self):
        """Test that removing last skill removes skill_tool from agent."""
        self.mock_skill_tool.get_skills_from_cache.return_value = []
        mock_agent = MagicMock()
        self.mock_get_ai_agent.return_value = mock_agent

        from topsailai.workspace.plugin_instruction.skill import unload_skill
        
        with patch('builtins.print'):
            unload_skill("/path/to/skill")
            
            mock_agent.remove_tools.assert_called_once_with("skill_tool")
            mock_agent.reload_tool_prompt.assert_called_once()

    def test_unload_skill_no_agent(self):
        """Test unload when no agent is available."""
        self.mock_skill_tool.get_skills_from_cache.return_value = []
        self.mock_get_ai_agent.return_value = None

        from topsailai.workspace.plugin_instruction.skill import unload_skill
        
        with patch('builtins.print') as mock_print:
            unload_skill("/path/to/skill")
            
            self.mock_skill_tool.unload_skill.assert_called_once()
            mock_print.assert_called_with("OK")


class TestLoadSkill(unittest.TestCase):
    """Test cases for load_skill() function."""

    def setUp(self):
        """Set up test fixtures."""
        self.skill_tool_patcher = patch(
            'topsailai.workspace.plugin_instruction.skill.skill_tool'
        )
        self.mock_skill_tool = self.skill_tool_patcher.start()
        
        self.cache_patcher = patch(
            'topsailai.workspace.plugin_instruction.skill.get_ai_agent'
        )
        self.mock_get_ai_agent = self.cache_patcher.start()

    def tearDown(self):
        """Clean up test fixtures."""
        self.skill_tool_patcher.stop()
        self.cache_patcher.stop()

    def test_load_skill_success(self):
        """Test successful skill load."""
        self.mock_skill_tool.exists_skill.return_value = True
        mock_agent = MagicMock()
        self.mock_get_ai_agent.return_value = mock_agent

        from topsailai.workspace.plugin_instruction.skill import load_skill
        
        with patch('builtins.print') as mock_print:
            load_skill("/path/to/skill")
            
            self.mock_skill_tool.load_skill.assert_called_once_with("/path/to/skill")
            mock_agent.add_tools_by_module.assert_called_once_with("topsailai.tools.skill_tool")
            mock_agent.reload_tool_prompt.assert_called_once()
            mock_print.assert_called_with("OK")

    def test_load_skill_failure(self):
        """Test skill load failure."""
        self.mock_skill_tool.exists_skill.return_value = False
        mock_agent = MagicMock()
        self.mock_get_ai_agent.return_value = mock_agent

        from topsailai.workspace.plugin_instruction.skill import load_skill
        
        with patch('builtins.print') as mock_print:
            load_skill("/path/to/skill")
            
            mock_print.assert_called_with("Failed")

    def test_load_skill_no_agent(self):
        """Test load when no agent is available."""
        self.mock_skill_tool.exists_skill.return_value = True
        self.mock_get_ai_agent.return_value = None

        from topsailai.workspace.plugin_instruction.skill import load_skill
        
        with patch('builtins.print') as mock_print:
            load_skill("/path/to/skill")
            
            self.mock_skill_tool.load_skill.assert_called_once()
            mock_print.assert_called_with("OK")


class TestShowHooks(unittest.TestCase):
    """Test cases for show_hooks() function."""

    def setUp(self):
        """Set up test fixtures."""
        self.skill_hook_patcher = patch(
            'topsailai.workspace.plugin_instruction.skill.skill_hook'
        )
        self.mock_skill_hook = self.skill_hook_patcher.start()

    def tearDown(self):
        """Clean up test fixtures."""
        self.skill_hook_patcher.stop()

    def test_show_hooks_success(self):
        """Test show_hooks displays sorted hook keys."""
        self.mock_skill_hook.get_hooks.return_value = {
            "hook1": MagicMock(),
            "hook2": MagicMock(),
            "hook3": MagicMock(),
        }

        from topsailai.workspace.plugin_instruction.skill import show_hooks
        
        with patch('builtins.print') as mock_print:
            show_hooks()
            
            self.mock_skill_hook.get_hooks.assert_called_once()
            mock_print.assert_called_once()

    def test_show_hooks_empty(self):
        """Test show_hooks with no hooks available."""
        self.mock_skill_hook.get_hooks.return_value = {}

        from topsailai.workspace.plugin_instruction.skill import show_hooks
        
        with patch('builtins.print') as mock_print:
            show_hooks()
            
            mock_print.assert_called_once_with([])


class TestInstructions(unittest.TestCase):
    """Test cases for INSTRUCTIONS dictionary."""

    def test_instructions_has_show(self):
        """Test INSTRUCTIONS has 'show' key."""
        from topsailai.workspace.plugin_instruction.skill import INSTRUCTIONS
        
        self.assertIn('show', INSTRUCTIONS)
        self.assertTrue(callable(INSTRUCTIONS['show']))

    def test_instructions_has_load(self):
        """Test INSTRUCTIONS has 'load' key."""
        from topsailai.workspace.plugin_instruction.skill import INSTRUCTIONS
        
        self.assertIn('load', INSTRUCTIONS)
        self.assertTrue(callable(INSTRUCTIONS['load']))

    def test_instructions_has_unload(self):
        """Test INSTRUCTIONS has 'unload' key."""
        from topsailai.workspace.plugin_instruction.skill import INSTRUCTIONS
        
        self.assertIn('unload', INSTRUCTIONS)
        self.assertTrue(callable(INSTRUCTIONS['unload']))

    def test_instructions_has_hooks(self):
        """Test INSTRUCTIONS has 'hooks' key."""
        from topsailai.workspace.plugin_instruction.skill import INSTRUCTIONS
        
        self.assertIn('hooks', INSTRUCTIONS)
        self.assertTrue(callable(INSTRUCTIONS['hooks']))


if __name__ == '__main__':
    unittest.main()
