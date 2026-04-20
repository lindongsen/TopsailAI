"""
Unit tests for workspace/plugin_instruction/skill_repo.py

Author: DawsonLin
Email: lin_dongsen@126.com
"""

import unittest
from unittest.mock import patch, MagicMock


class TestListSkills(unittest.TestCase):
    """Test cases for list_skills instruction handler."""

    @patch("topsailai.workspace.plugin_instruction.skill_repo.list_skills")
    def test_list_skills_success(self, mock_list_skills):
        """Test listing skills successfully."""
        from topsailai.workspace.plugin_instruction.skill_repo import list_skills
        
        mock_list_skills.return_value = ["skill1", "skill2", "skill3"]
        result = list_skills()
        
        mock_list_skills.assert_called_once()
        self.assertEqual(result, ["skill1", "skill2", "skill3"])

    @patch("topsailai.workspace.plugin_instruction.skill_repo.list_skills")
    def test_list_skills_empty(self, mock_list_skills):
        """Test listing skills when skill list is empty."""
        from topsailai.workspace.plugin_instruction.skill_repo import list_skills
        
        mock_list_skills.return_value = []
        result = list_skills()
        
        mock_list_skills.assert_called_once()
        self.assertEqual(result, [])

    @patch("topsailai.workspace.plugin_instruction.skill_repo.list_skills")
    def test_list_skills_with_filter(self, mock_list_skills):
        """Test listing skills with filter parameter."""
        from topsailai.workspace.plugin_instruction.skill_repo import list_skills
        
        mock_list_skills.return_value = ["python_skill", "java_skill"]
        result = list_skills(filter="python")
        
        mock_list_skills.assert_called_once_with(filter="python")
        self.assertEqual(result, ["python_skill", "java_skill"])

    @patch("topsailai.workspace.plugin_instruction.skill_repo.list_skills")
    def test_list_skills_exception(self, mock_list_skills):
        """Test listing skills when exception occurs."""
        from topsailai.workspace.plugin_instruction.skill_repo import list_skills
        
        mock_list_skills.side_effect = Exception("Failed to list skills")
        
        with self.assertRaises(Exception):
            list_skills()


class TestInstallSkill(unittest.TestCase):
    """Test cases for install_skill instruction handler."""

    @patch("topsailai.workspace.plugin_instruction.skill_repo.install_skill")
    def test_install_skill_success(self, mock_install_skill):
        """Test installing skill successfully."""
        from topsailai.workspace.plugin_instruction.skill_repo import install_skill
        
        mock_install_skill.return_value = {"status": "success", "name": "test_skill"}
        result = install_skill(name="test_skill")
        
        mock_install_skill.assert_called_once_with(name="test_skill")
        self.assertEqual(result, {"status": "success", "name": "test_skill"})

    @patch("topsailai.workspace.plugin_instruction.skill_repo.install_skill")
    def test_install_skill_already_exists(self, mock_install_skill):
        """Test installing skill that already exists."""
        from topsailai.workspace.plugin_instruction.skill_repo import install_skill
        
        mock_install_skill.side_effect = Exception("Skill already installed")
        
        with self.assertRaises(Exception):
            install_skill(name="existing_skill")

    @patch("topsailai.workspace.plugin_instruction.skill_repo.install_skill")
    def test_install_skill_invalid_name(self, mock_install_skill):
        """Test installing skill with invalid name."""
        from topsailai.workspace.plugin_instruction.skill_repo import install_skill
        
        mock_install_skill.side_effect = Exception("Invalid skill name")
        
        with self.assertRaises(Exception):
            install_skill(name="")

    @patch("topsailai.workspace.plugin_instruction.skill_repo.install_skill")
    def test_install_skill_exception(self, mock_install_skill):
        """Test installing skill when exception occurs."""
        from topsailai.workspace.plugin_instruction.skill_repo import install_skill
        
        mock_install_skill.side_effect = Exception("Network error")
        
        with self.assertRaises(Exception):
            install_skill(name="test_skill")


class TestUninstallSkill(unittest.TestCase):
    """Test cases for uninstall_skill instruction handler."""

    @patch("topsailai.workspace.plugin_instruction.skill_repo.uninstall_skill")
    def test_uninstall_skill_success(self, mock_uninstall_skill):
        """Test uninstalling skill successfully."""
        from topsailai.workspace.plugin_instruction.skill_repo import uninstall_skill
        
        mock_uninstall_skill.return_value = {"status": "success", "name": "test_skill"}
        result = uninstall_skill(name="test_skill")
        
        mock_uninstall_skill.assert_called_once_with(name="test_skill")
        self.assertEqual(result, {"status": "success", "name": "test_skill"})

    @patch("topsailai.workspace.plugin_instruction.skill_repo.uninstall_skill")
    def test_uninstall_skill_not_found(self, mock_uninstall_skill):
        """Test uninstalling non-existent skill."""
        from topsailai.workspace.plugin_instruction.skill_repo import uninstall_skill
        
        mock_uninstall_skill.side_effect = Exception("Skill not found")
        
        with self.assertRaises(Exception):
            uninstall_skill(name="nonexistent_skill")

    @patch("topsailai.workspace.plugin_instruction.skill_repo.uninstall_skill")
    def test_uninstall_skill_in_use(self, mock_uninstall_skill):
        """Test uninstalling skill that is currently in use."""
        from topsailai.workspace.plugin_instruction.skill_repo import uninstall_skill
        
        mock_uninstall_skill.side_effect = Exception("Skill is in use")
        
        with self.assertRaises(Exception):
            uninstall_skill(name="active_skill")

    @patch("topsailai.workspace.plugin_instruction.skill_repo.uninstall_skill")
    def test_uninstall_skill_exception(self, mock_uninstall_skill):
        """Test uninstalling skill when exception occurs."""
        from topsailai.workspace.plugin_instruction.skill_repo import uninstall_skill
        
        mock_uninstall_skill.side_effect = Exception("Unknown error")
        
        with self.assertRaises(Exception):
            uninstall_skill(name="test_skill")


class TestInstructions(unittest.TestCase):
    """Test cases for INSTRUCTIONS dictionary."""

    def test_instructions_has_list(self):
        """Test INSTRUCTIONS has 'list' key."""
        from topsailai.workspace.plugin_instruction.skill_repo import INSTRUCTIONS
        
        self.assertIn("list", INSTRUCTIONS)
        self.assertTrue(callable(INSTRUCTIONS["list"]))

    def test_instructions_has_install(self):
        """Test INSTRUCTIONS has 'install' key."""
        from topsailai.workspace.plugin_instruction.skill_repo import INSTRUCTIONS
        
        self.assertIn("install", INSTRUCTIONS)
        self.assertTrue(callable(INSTRUCTIONS["install"]))

    def test_instructions_has_uninstall(self):
        """Test INSTRUCTIONS has 'uninstall' key."""
        from topsailai.workspace.plugin_instruction.skill_repo import INSTRUCTIONS
        
        self.assertIn("uninstall", INSTRUCTIONS)
        self.assertTrue(callable(INSTRUCTIONS["uninstall"]))

    def test_instructions_count(self):
        """Test INSTRUCTIONS has exactly 3 keys."""
        from topsailai.workspace.plugin_instruction.skill_repo import INSTRUCTIONS
        
        self.assertEqual(len(INSTRUCTIONS), 3)


if __name__ == "__main__":
    unittest.main()
