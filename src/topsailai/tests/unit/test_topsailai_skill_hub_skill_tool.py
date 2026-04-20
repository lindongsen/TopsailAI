"""
Unit tests for the skill_hub.skill_tool module.

This module tests skill parsing, loading, and management functions.

Author: AI (Unit Test Enhancement)
Purpose: Comprehensive test coverage for skill hub module
"""

import os
import unittest
from unittest.mock import patch, MagicMock, mock_open
import tempfile
import yaml

from topsailai.skill_hub.skill_tool import (
    is_matched_skill,
    is_need_load_overview,
    SkillInfo,
    get_file_skill_md,
    is_disabled_skill,
    parse_skill_folder,
    get_skill_markdown_with_subfolders,
    get_skill_markdown,
    get_skills_from_cache,
    get_skill_info_from_cache,
    unload_skill,
    load_skill,
    exists_skill,
    overview_skill_native,
    get_skill_file,
    get_skill_file_content,
    g_skills,
)


class TestIsMatchedSkill(unittest.TestCase):
    def test_with_none_keys(self):
        """Test with None keys - to_list returns [None] so startswith fails."""
        # The to_list function returns [None] for None input, which causes TypeError
        # This test documents the actual behavior
        with self.assertRaises(TypeError):
            is_matched_skill("any_folder", None)

    def test_with_asterisk_wildcard(self):
        """Test that asterisk wildcard matches any skill."""
        result = is_matched_skill("any_folder", ["*"])
        self.assertTrue(result)

    def test_with_exact_prefix_match(self):
        """Test exact prefix matching."""
        result = is_matched_skill("my_skill_folder", ["my_"])
        self.assertTrue(result)

    def test_with_exact_suffix_match(self):
        """Test exact suffix matching."""
        result = is_matched_skill("folder_python", ["python"])
        self.assertTrue(result)

    def test_with_no_match(self):
        """Test when no match is found."""
        result = is_matched_skill("random_folder", ["specific"])
        self.assertFalse(result)

    def test_with_multiple_keys(self):
        """Test matching with multiple keys."""
        result = is_matched_skill("test_folder", ["abc", "test", "xyz"])
        self.assertTrue(result)

    def test_with_empty_keys(self):
        """Test with empty keys list."""
        result = is_matched_skill("any_folder", [])
        self.assertFalse(result)

    def test_with_none_keys(self):
        """Test with None keys."""
        # to_list converts None to []
        result = is_matched_skill("any_folder", None)
        self.assertFalse(result)

    def test_with_string_instead_of_list(self):
        """Test when keys is a string instead of list."""
        result = is_matched_skill("test_folder", "test")
        self.assertTrue(result)


class TestIsNeedLoadOverview(unittest.TestCase):
    """Test cases for is_need_load_overview function."""

    @patch('topsailai.skill_hub.skill_tool.EnvReaderInstance')
    def test_no_skills_configured(self, mock_env):
        """Test when no skills are configured."""
        mock_env.get_list_str.return_value = None
        
        result = is_need_load_overview("/some/folder")
        self.assertFalse(result)

    @patch('topsailai.skill_hub.skill_tool.EnvReaderInstance')
    def test_folder_matches_configured_skill(self, mock_env):
        """Test when folder matches a configured skill."""
        mock_env.get_list_str.return_value = ["/skills/my_skill"]
        
        result = is_need_load_overview("/skills/my_skill")
        self.assertTrue(result)

    @patch('topsailai.skill_hub.skill_tool.EnvReaderInstance')
    def test_folder_starts_with_skill(self, mock_env):
        """Test when folder path starts with configured skill."""
        mock_env.get_list_str.return_value = ["/skills/base"]
        
        result = is_need_load_overview("/skills/base/subfolder")
        self.assertTrue(result)

    @patch('topsailai.skill_hub.skill_tool.EnvReaderInstance')
    def test_folder_ends_with_skill(self, mock_env):
        """Test when folder path ends with configured skill."""
        mock_env.get_list_str.return_value = ["my_skill"]
        
        result = is_need_load_overview("/path/to/my_skill")
        self.assertTrue(result)

    @patch('topsailai.skill_hub.skill_tool.EnvReaderInstance')
    def test_folder_with_trailing_slash(self, mock_env):
        """Test folder path with trailing slash handling."""
        mock_env.get_list_str.return_value = ["/skills/test"]
        
        result = is_need_load_overview("/skills/test/")
        self.assertTrue(result)

    @patch('topsailai.skill_hub.skill_tool.EnvReaderInstance')
    def test_no_match(self, mock_env):
        """Test when folder doesn't match any configured skill."""
        mock_env.get_list_str.return_value = ["/skills/other"]
        
        result = is_need_load_overview("/skills/different")
        self.assertFalse(result)


class TestSkillInfo(unittest.TestCase):
    """Test cases for SkillInfo class."""

    def test_initialization(self):
        """Test SkillInfo initialization with default values."""
        skill_info = SkillInfo()
        
        self.assertEqual(skill_info.folder, "")
        self.assertEqual(skill_info.name, "")
        self.assertEqual(skill_info.description, "")
        self.assertIsNone(skill_info.flag_overview)
        self.assertEqual(skill_info.all, {})

    def test_markdown_property_empty(self):
        """Test markdown property with empty values."""
        skill_info = SkillInfo()
        skill_info.folder = "test_folder"
        
        result = skill_info.markdown
        
        self.assertIn("test_folder", result)
        self.assertIn("## . folder=", result)

    def test_markdown_property_with_name_and_description(self):
        """Test markdown property with name and description."""
        skill_info = SkillInfo()
        skill_info.folder = "test_folder"
        skill_info.name = "TestSkill"
        skill_info.description = "A test skill"
        
        result = skill_info.markdown
        
        self.assertIn("TestSkill", result)
        self.assertIn("A test skill", result)
        self.assertIn("test_folder", result)

    def test_str_method(self):
        """Test __str__ method returns markdown."""
        skill_info = SkillInfo()
        skill_info.name = "TestSkill"
        skill_info.folder = "test_folder"  # Need folder for markdown
        
        # Mock is_need_load_overview to avoid folder path issues
        with patch('topsailai.skill_hub.skill_tool.is_need_load_overview', return_value=False):
            result = str(skill_info)
            self.assertIn("TestSkill", result)


class TestGetFileSkillMd(unittest.TestCase):
    """Test cases for get_file_skill_md function."""

    def test_finds_uppercase_skill_md(self):
        """Test finding SKILL.md file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_file = os.path.join(tmpdir, "SKILL.md")
            with open(skill_file, "w") as f:
                f.write("test")
            
            result = get_file_skill_md(tmpdir)
            self.assertEqual(result, skill_file)

    def test_finds_lowercase_skill_md(self):
        """Test finding skill.md file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_file = os.path.join(tmpdir, "skill.md")
            with open(skill_file, "w") as f:
                f.write("test")
            
            result = get_file_skill_md(tmpdir)
            self.assertEqual(result, skill_file)

    def test_prefers_uppercase_when_both_exist(self):
        """Test that SKILL.md is preferred over skill.md."""
        with tempfile.TemporaryDirectory() as tmpdir:
            upper_file = os.path.join(tmpdir, "SKILL.md")
            lower_file = os.path.join(tmpdir, "skill.md")
            with open(upper_file, "w") as f:
                f.write("upper")
            with open(lower_file, "w") as f:
                f.write("lower")
            
            result = get_file_skill_md(tmpdir)
            self.assertEqual(result, upper_file)

    def test_returns_empty_when_no_file(self):
        """Test returns empty string when no skill.md found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = get_file_skill_md(tmpdir)
            self.assertEqual(result, "")


class TestIsDisabledSkill(unittest.TestCase):
    """Test cases for is_disabled_skill function."""

    @patch('topsailai.skill_hub.skill_tool.EnvReaderInstance')
    def test_empty_folder_path(self, mock_env):
        """Test that empty folder path is disabled."""
        result = is_disabled_skill("")
        self.assertTrue(result)

    @patch('topsailai.skill_hub.skill_tool.EnvReaderInstance')
    def test_no_disabled_list(self, mock_env):
        """Test when no disabled list is configured."""
        mock_env.get_list_str.return_value = None
        
        result = is_disabled_skill("/some/folder")
        self.assertFalse(result)

    @patch('topsailai.skill_hub.skill_tool.EnvReaderInstance')
    def test_exact_match_in_disabled_list(self, mock_env):
        """Test exact match in disabled list."""
        mock_env.get_list_str.return_value = ["/disabled/folder"]
        
        result = is_disabled_skill("/disabled/folder")
        self.assertTrue(result)

    @patch('topsailai.skill_hub.skill_tool.EnvReaderInstance')
    def test_wildcard_disables_all(self, mock_env):
        """Test that wildcard disables all skills."""
        mock_env.get_list_str.return_value = "*"
        
        result = is_disabled_skill("/any/folder")
        self.assertTrue(result)

    @patch('topsailai.skill_hub.skill_tool.EnvReaderInstance')
    def test_prefix_match_in_disabled_list(self, mock_env):
        """Test prefix match in disabled list."""
        mock_env.get_list_str.return_value = ["/disabled"]
        
        result = is_disabled_skill("/disabled/subfolder")
        self.assertTrue(result)


class TestParseSkillFolder(unittest.TestCase):
    """Test cases for parse_skill_folder function."""

    def setUp(self):
        """Clear global skills cache before each test."""
        g_skills.clear()

    def test_returns_empty_for_nonexistent_folder(self):
        """Test parsing a nonexistent folder returns empty SkillInfo."""
        result = parse_skill_folder("/nonexistent/folder")
        
        self.assertEqual(result.name, "")
        self.assertEqual(result.description, "")

    def test_parses_yaml_frontmatter(self):
        """Test parsing YAML frontmatter from SKILL.md."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_file = os.path.join(tmpdir, "SKILL.md")
            yaml_content = """---
name: TestSkill
description: A test skill description
---
# Additional content
"""
            with open(skill_file, "w") as f:
                f.write(yaml_content)
            
            result = parse_skill_folder(tmpdir)
            
            self.assertEqual(result.name, "TestSkill")
            self.assertEqual(result.description, "A test skill description")
            self.assertEqual(result.folder, tmpdir)

    def test_adds_to_global_cache(self):
        """Test that parsed skill is added to global cache."""
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_file = os.path.join(tmpdir, "SKILL.md")
            yaml_content = """---
name: CachedSkill
description: A cached skill
---
"""
            with open(skill_file, "w") as f:
                f.write(yaml_content)
            
            result = parse_skill_folder(tmpdir)
            
            self.assertIn(tmpdir, g_skills)
            self.assertEqual(g_skills[tmpdir].name, "CachedSkill")


class TestSkillCache(unittest.TestCase):
    """Test cases for skill cache functions."""

    def setUp(self):
        """Clear global skills cache before each test."""
        g_skills.clear()

    def test_get_skills_from_cache_empty(self):
        """Test getting skills from empty cache."""
        result = list(get_skills_from_cache())
        self.assertEqual(len(result), 0)

    def test_get_skill_info_from_cache(self):
        """Test getting skill info from cache."""
        skill_info = SkillInfo()
        skill_info.name = "TestSkill"
        g_skills["/test/path"] = skill_info
        
        result = get_skill_info_from_cache("/test/path")
        
        self.assertIsNotNone(result)
        self.assertEqual(result.name, "TestSkill")

    def test_get_skill_info_from_cache_not_found(self):
        """Test getting skill info that doesn't exist."""
        result = get_skill_info_from_cache("/nonexistent")
        self.assertIsNone(result)

    def test_exists_skill(self):
        """Test checking if skill exists."""
        skill_info = SkillInfo()
        skill_info.name = "TestSkill"
        g_skills["/test/path"] = skill_info
        
        self.assertTrue(exists_skill("/test/path"))
        self.assertFalse(exists_skill("/nonexistent"))


class TestLoadUnloadSkill(unittest.TestCase):
    """Test cases for load_skill and unload_skill functions."""

    def setUp(self):
        """Clear global skills cache and environment before each test."""
        g_skills.clear()
        if "TOPSAILAI_PLUGIN_SKILLS" in os.environ:
            del os.environ["TOPSAILAI_PLUGIN_SKILLS"]

    def tearDown(self):
        """Clean up environment after tests."""
        if "TOPSAILAI_PLUGIN_SKILLS" in os.environ:
            del os.environ["TOPSAILAI_PLUGIN_SKILLS"]

    @patch('topsailai.skill_hub.skill_tool.EnvReaderInstance')
    def test_load_skill(self, mock_env):
        """Test loading a skill."""
        mock_env.get_list_str.return_value = []
        
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_file = os.path.join(tmpdir, "SKILL.md")
            yaml_content = """---
name: LoadedSkill
description: A loaded skill
---
"""
            with open(skill_file, "w") as f:
                f.write(yaml_content)
            
            result = load_skill(tmpdir)
            
            self.assertEqual(result.name, "LoadedSkill")
            self.assertIn(tmpdir, g_skills)

    @patch('topsailai.skill_hub.skill_tool.EnvReaderInstance')
    def test_unload_skill(self, mock_env):
        """Test unloading a skill."""
        mock_env.get_list_str.return_value = []
        
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_file = os.path.join(tmpdir, "SKILL.md")
            yaml_content = """---
name: UnloadSkill
description: A skill to unload
---
"""
            with open(skill_file, "w") as f:
                f.write(yaml_content)
            
            load_skill(tmpdir)
            self.assertIn(tmpdir, g_skills)
            
            unload_skill(tmpdir)
            self.assertNotIn(tmpdir, g_skills)


class TestGetSkillMarkdown(unittest.TestCase):
    """Test cases for get_skill_markdown function."""

    def setUp(self):
        """Clear global skills cache before each test."""
        g_skills.clear()

    @patch('topsailai.skill_hub.skill_tool.EnvReaderInstance')
    def test_empty_result_when_no_skills(self, mock_env):
        """Test empty result when no skills exist."""
        mock_env.get_list_str.return_value = None
        mock_env.get.return_value = 3
        
        with tempfile.TemporaryDirectory() as tmpdir:
            result = get_skill_markdown([tmpdir])
            
        self.assertEqual(result, "")

    @patch('topsailai.skill_hub.skill_tool.EnvReaderInstance')
    def test_returns_prompt_format(self, mock_env):
        """Test that result includes prompt format header."""
        mock_env.get_list_str.return_value = None
        mock_env.get.return_value = 3
        
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_file = os.path.join(tmpdir, "SKILL.md")
            yaml_content = """---
name: PromptTest
description: Test skill
---
"""
            with open(skill_file, "w") as f:
                f.write(yaml_content)
            
            result = get_skill_markdown([tmpdir])
            
        self.assertIn("# Skill Registry", result)
        self.assertIn("PromptTest", result)


if __name__ == '__main__':
    unittest.main()
