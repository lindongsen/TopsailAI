import os
import pytest
import tempfile
import shutil
from unittest.mock import patch

from topsailai.skill_hub.skill_tool import (
    SkillInfo,
    parse_skill_folder,
    get_skill_markdown,
    PROMPT_SKILL,
)


class TestSkillInfo:
    """Test SkillInfo class"""

    def test_init(self):
        """Test SkillInfo initialization"""
        skill_info = SkillInfo()
        assert skill_info.folder == ""
        assert skill_info.name == ""
        assert skill_info.description == ""

    def test_markdown_property(self):
        """Test markdown property"""
        skill_info = SkillInfo()
        skill_info.folder = "/test/folder"
        skill_info.name = "test_skill"
        skill_info.description = "A test skill description"

        expected = """
## test_skill. folder=`/test/folder`
A test skill description
"""
        assert skill_info.markdown == expected


class TestParseSkillFolder:
    """Test parse_skill_folder function"""

    def setup_method(self):
        """Setup method to create temporary directory for each test"""
        self.temp_dir = tempfile.mkdtemp()

    def teardown_method(self):
        """Cleanup after each test"""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_parse_nonexistent_folder(self):
        """Test parsing a nonexistent folder"""
        result = parse_skill_folder("/nonexistent/folder")
        assert result.folder == "/nonexistent/folder"
        assert result.name == ""
        assert result.description == ""

    def test_parse_folder_without_skill_file(self):
        """Test parsing a folder without SKILL.md"""
        # Create a folder with no skill file
        subdir = os.path.join(self.temp_dir, "empty_folder")
        os.makedirs(subdir)

        result = parse_skill_folder(subdir)
        assert result.name == ""
        assert result.description == ""

    def test_parse_folder_with_skill_md(self):
        """Test parsing a folder with skill.md"""
        # Create SKILL.md
        skill_file = os.path.join(self.temp_dir, "skill.md")
        content = """---
name: my_skill
description: A test skill
---
Some additional content
"""
        with open(skill_file, "w") as f:
            f.write(content)

        result = parse_skill_folder(self.temp_dir)
        assert result.name == "my_skill"
        assert result.description == "A test skill"

    def test_parse_folder_with_CAPITAL_SKILL_md(self):
        """Test parsing a folder with SKILL.md (capitalized)"""
        # Create SKILL.md
        skill_file = os.path.join(self.temp_dir, "SKILL.md")
        content = """---
name: capital_skill
description: Skill with capital SKILL.md
---
"""
        with open(skill_file, "w") as f:
            f.write(content)

        result = parse_skill_folder(self.temp_dir)
        assert result.name == "capital_skill"
        assert result.description == "Skill with capital SKILL.md"

    def test_parse_folder_skill_md_priority(self):
        """Test that skill.md takes priority over SKILL.md"""
        # Create both files
        skill_lower = os.path.join(self.temp_dir, "skill.md")
        skill_upper = os.path.join(self.temp_dir, "SKILL.md")

        with open(skill_lower, "w") as f:
            f.write("---\nname: lower\ndescription: lower priority\n---\n")

        with open(skill_upper, "w") as f:
            f.write("---\nname: upper\ndescription: upper priority\n---\n")

        result = parse_skill_folder(self.temp_dir)
        # SKILL.md (uppercase) should be found first
        assert result.name == "upper"

    def test_parse_folder_invalid_yaml(self):
        """Test parsing with invalid YAML"""
        skill_file = os.path.join(self.temp_dir, "skill.md")
        content = """---
name: invalid
description: [broken yaml
---
"""
        with open(skill_file, "w") as f:
            f.write(content)

        result = parse_skill_folder(self.temp_dir)
        # Should gracefully handle YAML errors
        assert result.name == ""
        assert result.description == ""

    def test_parse_folder_no_frontmatter(self):
        """Test parsing a file without YAML frontmatter"""
        skill_file = os.path.join(self.temp_dir, "skill.md")
        content = """# My Skill

This is just markdown content without frontmatter.
"""
        with open(skill_file, "w") as f:
            f.write(content)

        result = parse_skill_folder(self.temp_dir)
        assert result.name == ""
        assert result.description == ""

    def test_parse_folder_missing_name(self):
        """Test parsing with missing name in frontmatter"""
        skill_file = os.path.join(self.temp_dir, "skill.md")
        content = """---
description: Only description, no name
---
"""
        with open(skill_file, "w") as f:
            f.write(content)

        result = parse_skill_folder(self.temp_dir)
        assert result.name == ""
        assert result.description == "Only description, no name"

    def test_parse_folder_missing_description(self):
        """Test parsing with missing description in frontmatter"""
        skill_file = os.path.join(self.temp_dir, "skill.md")
        content = """---
name: only_name
---
"""
        with open(skill_file, "w") as f:
            f.write(content)

        result = parse_skill_folder(self.temp_dir)
        assert result.name == "only_name"
        assert result.description == ""


class TestGetSkillMarkdown:
    """Test get_skill_markdown function"""

    def setup_method(self):
        """Setup method to create temporary directory for each test"""
        self.temp_dir = tempfile.mkdtemp()
        self.original_env = os.environ.copy()

    def teardown_method(self):
        """Cleanup after each test"""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
        os.environ.clear()
        os.environ.update(self.original_env)

    def test_no_skills_returns_empty(self):
        """Test that empty result returns empty string"""
        with patch("topsailai.skill_hub.skill_tool.FOLDER_SKILL", "/nonexistent"):
            result = get_skill_markdown()
            assert result == ""

    def test_single_skill_folder(self):
        """Test parsing a single skill folder"""
        # Create a skill folder
        skill_dir = os.path.join(self.temp_dir, "test_skill")
        os.makedirs(skill_dir)

        skill_file = os.path.join(skill_dir, "SKILL.md")
        content = """---
name: test_skill
description: A test skill for unit testing
---
"""
        with open(skill_file, "w") as f:
            f.write(content)

        with patch("topsailai.skill_hub.skill_tool.FOLDER_SKILL", self.temp_dir):
            result = get_skill_markdown()

        assert PROMPT_SKILL in result
        assert "## test_skill. folder=" in result
        assert "A test skill for unit testing" in result

    def test_subfolders_parsed(self):
        """Test that subfolders are parsed"""
        # Create subfolders with skills
        subdir1 = os.path.join(self.temp_dir, "skill1")
        subdir2 = os.path.join(self.temp_dir, "skill2")
        os.makedirs(subdir1)
        os.makedirs(subdir2)

        with open(os.path.join(subdir1, "skill.md"), "w") as f:
            f.write("---\nname: skill_one\ndescription: First skill\n---\n")

        with open(os.path.join(subdir2, "skill.md"), "w") as f:
            f.write("---\nname: skill_two\ndescription: Second skill\n---\n")

        with patch("topsailai.skill_hub.skill_tool.FOLDER_SKILL", self.temp_dir):
            result = get_skill_markdown()

        assert "## skill_one. folder=" in result
        assert "## skill_two. folder=" in result

    def test_plugin_skills_from_env(self):
        """Test that plugin skills from environment variable are parsed"""
        # Create a plugin skill folder
        plugin_dir = os.path.join(self.temp_dir, "plugin_skill")
        os.makedirs(plugin_dir)

        skill_file = os.path.join(plugin_dir, "skill.md")
        content = """---
name: plugin_skill
description: A plugin skill
---
"""
        with open(skill_file, "w") as f:
            f.write(content)

        with patch.dict(os.environ, {"TOPSAILAI_PLUGIN_SKILLS": plugin_dir}):
            # Patch FOLDER_SKILL to nonexistent to only test plugin skills
            with patch("topsailai.skill_hub.skill_tool.FOLDER_SKILL", "/nonexistent"):
                result = get_skill_markdown()

        assert "## plugin_skill. folder=" in result
        assert "A plugin skill" in result

    def test_multiple_plugin_skills(self):
        """Test multiple plugin skills from environment variable"""
        plugin_dir1 = os.path.join(self.temp_dir, "plugin1")
        plugin_dir2 = os.path.join(self.temp_dir, "plugin2")
        os.makedirs(plugin_dir1)
        os.makedirs(plugin_dir2)

        with open(os.path.join(plugin_dir1, "skill.md"), "w") as f:
            f.write("---\nname: p1\ndescription: Plugin 1\n---\n")

        with open(os.path.join(plugin_dir2, "skill.md"), "w") as f:
            f.write("---\nname: p2\ndescription: Plugin 2\n---\n")

        # Multiple plugins separated by semicolon
        plugin_path = f"{plugin_dir1};{plugin_dir2}"
        with patch.dict(os.environ, {"TOPSAILAI_PLUGIN_SKILLS": plugin_path}):
            with patch("topsailai.skill_hub.skill_tool.FOLDER_SKILL", "/nonexistent"):
                result = get_skill_markdown()

        assert "## p1. folder=" in result
        assert "## p2. folder=" in result

    def test_empty_folder_skipped(self):
        """Test that folders without SKILL.md are skipped"""
        # Create an empty folder
        empty_dir = os.path.join(self.temp_dir, "empty")
        os.makedirs(empty_dir)

        with patch("topsailai.skill_hub.skill_tool.FOLDER_SKILL", self.temp_dir):
            result = get_skill_markdown()

        # Empty folder should not appear in result
        assert "empty" not in result or result == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
