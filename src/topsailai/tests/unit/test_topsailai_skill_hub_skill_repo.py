"""
Unit tests for skill_hub/skill_repo.py module.

This module tests the skill repository functionality, including:
- Skill listing and discovery
- Skill installation from various sources (git, zip, URL, local)
- Skill uninstallation
- Path traversal protection

Author: mm-m25
"""

import os
import unittest
from unittest.mock import MagicMock, patch, mock_open, call
import zipfile
import tempfile
import subprocess


class TestIsGitUrl(unittest.TestCase):
    """Test cases for _is_git_url() function."""

    def test_is_git_url_github_with_git_suffix(self):
        """Test _is_git_url returns True for github.com URL with .git suffix."""
        from topsailai.skill_hub.skill_repo import _is_git_url

        result = _is_git_url("https://github.com/user/repo.git")
        self.assertTrue(result)

    def test_is_git_url_github_without_git_suffix(self):
        """Test _is_git_url returns True for github.com URL without .git suffix."""
        from topsailai.skill_hub.skill_repo import _is_git_url

        result = _is_git_url("https://github.com/user/repo")
        self.assertTrue(result)

    def test_is_git_url_gitlab(self):
        """Test _is_git_url returns True for gitlab.com URL."""
        from topsailai.skill_hub.skill_repo import _is_git_url

        result = _is_git_url("https://gitlab.com/user/repo.git")
        self.assertTrue(result)

    def test_is_git_url_bitbucket(self):
        """Test _is_git_url returns True for bitbucket.org URL."""
        from topsailai.skill_hub.skill_repo import _is_git_url

        result = _is_git_url("https://bitbucket.org/user/repo.git")
        self.assertTrue(result)

    def test_is_git_url_ssh_github(self):
        """Test _is_git_url returns True for SSH git URL."""
        from topsailai.skill_hub.skill_repo import _is_git_url

        result = _is_git_url("git@github.com:user/repo.git")
        self.assertTrue(result)

    def test_is_git_url_ssh_gitlab(self):
        """Test _is_git_url returns True for SSH gitlab URL."""
        from topsailai.skill_hub.skill_repo import _is_git_url

        result = _is_git_url("git@gitlab.com:user/repo.git")
        self.assertTrue(result)

    def test_is_git_url_false_for_http(self):
        """Test _is_git_url returns False for plain HTTP URL."""
        from topsailai.skill_hub.skill_repo import _is_git_url

        result = _is_git_url("http://example.com/repo")
        self.assertFalse(result)

    def test_is_git_url_false_for_local_path(self):
        """Test _is_git_url returns False for local path."""
        from topsailai.skill_hub.skill_repo import _is_git_url

        result = _is_git_url("/path/to/local/repo")
        self.assertFalse(result)

    def test_is_git_url_false_for_zip_file(self):
        """Test _is_git_url returns False for zip file path."""
        from topsailai.skill_hub.skill_repo import _is_git_url

        result = _is_git_url("/path/to/skill.zip")
        self.assertFalse(result)


class TestSafeExtract(unittest.TestCase):
    """Test cases for _safe_extract() function."""

    def test_safe_extract_valid_path(self):
        """Test _safe_extract extracts file to valid path."""
        from topsailai.skill_hub.skill_repo import _safe_extract

        mock_zip = MagicMock()
        target_dir = tempfile.mkdtemp()

        _safe_extract(mock_zip, "file.txt", target_dir)

        mock_zip.extract.assert_called_once_with("file.txt", target_dir)

    def test_safe_extract_prevents_path_traversal(self):
        """Test _safe_extract raises ValueError for path traversal attempt."""
        from topsailai.skill_hub.skill_repo import _safe_extract

        mock_zip = MagicMock()
        target_dir = tempfile.mkdtemp()

        with self.assertRaises(ValueError) as context:
            _safe_extract(mock_zip, "../../../etc/passwd", target_dir)

        self.assertIn("Path traversal attempt detected", str(context.exception))


class TestValidateSkillInstallation(unittest.TestCase):
    """Test cases for _validate_skill_installation() function."""

    @patch("topsailai.skill_hub.skill_repo.get_file_skill_md")
    def test_validate_skill_returns_true_when_skill_md_exists(self, mock_get_file):
        """Test _validate_skill_installation returns True when SKILL.md exists."""
        from topsailai.skill_hub.skill_repo import _validate_skill_installation

        mock_get_file.return_value = "/path/to/skill/SKILL.md"

        result = _validate_skill_installation("/path/to/skill")

        self.assertTrue(result)

    @patch("topsailai.skill_hub.skill_repo.get_file_skill_md")
    @patch("topsailai.skill_hub.skill_repo.logger")
    def test_validate_skill_returns_false_when_skill_md_missing(self, mock_logger, mock_get_file):
        """Test _validate_skill_installation returns False when SKILL.md missing."""
        from topsailai.skill_hub.skill_repo import _validate_skill_installation

        mock_get_file.return_value = None

        result = _validate_skill_installation("/path/to/skill")

        self.assertFalse(result)
        mock_logger.warning.assert_called_once()


class TestInstallSkill(unittest.TestCase):
    """Test cases for install_skill() function."""

    @patch("topsailai.skill_hub.skill_repo.install_from_local")
    @patch("os.path.exists")
    def test_install_skill_from_local_path(self, mock_exists, mock_install_local):
        """Test install_skill calls install_from_local for existing local path."""
        from topsailai.skill_hub.skill_repo import install_skill

        mock_exists.return_value = True
        mock_install_local.return_value = "/skills/local/myskill"

        result = install_skill("/path/to/myskill")

        self.assertEqual(result, "/skills/local/myskill")
        mock_install_local.assert_called_once_with("/path/to/myskill")

    @patch("topsailai.skill_hub.skill_repo.install_from_git")
    @patch("topsailai.skill_hub.skill_repo._is_git_url")
    def test_install_skill_from_git_url(self, mock_is_git, mock_install_git):
        """Test install_skill calls install_from_git for git URL."""
        from topsailai.skill_hub.skill_repo import install_skill

        mock_is_git.return_value = True
        mock_install_git.return_value = "/skills/github.com/repo"

        result = install_skill("https://github.com/user/repo.git")

        self.assertEqual(result, "/skills/github.com/repo")
        mock_install_git.assert_called_once_with("https://github.com/user/repo.git")

    @patch("topsailai.skill_hub.skill_repo.install_from_zip")
    @patch("os.path.exists")
    def test_install_skill_from_zip(self, mock_exists, mock_install_zip):
        """Test install_skill calls install_from_zip for .zip file."""
        from topsailai.skill_hub.skill_repo import install_skill

        mock_exists.return_value = False
        mock_install_zip.return_value = "/skills/local/myskill"

        result = install_skill("/path/to/myskill.zip")

        self.assertEqual(result, "/skills/local/myskill")
        mock_install_zip.assert_called_once_with("/path/to/myskill.zip")

    @patch("topsailai.skill_hub.skill_repo.install_from_url")
    def test_install_skill_from_http_url(self, mock_install_url):
        """Test install_skill calls install_from_url for HTTP URL."""
        from topsailai.skill_hub.skill_repo import install_skill

        mock_install_url.return_value = "/skills/example.com/skill"

        result = install_skill("https://example.com/skill.zip")

        self.assertEqual(result, "/skills/example.com/skill")
        mock_install_url.assert_called_once_with("https://example.com/skill.zip")

    def test_install_skill_raises_error_for_empty_address(self):
        """Test install_skill raises ValueError for empty address."""
        from topsailai.skill_hub.skill_repo import install_skill

        with self.assertRaises(ValueError) as context:
            install_skill("")

        self.assertIn("Address cannot be empty", str(context.exception))

    def test_install_skill_raises_error_for_invalid_address(self):
        """Test install_skill raises ValueError for invalid address."""
        from topsailai.skill_hub.skill_repo import install_skill

        with self.assertRaises(ValueError) as context:
            install_skill("invalid://not-a-valid-address")

        self.assertIn("Illegal address", str(context.exception))


class TestInstallFromGit(unittest.TestCase):
    """Test cases for install_from_git() function."""

    def test_install_from_git_raises_error_for_empty_url(self):
        """Test install_from_git raises ValueError for empty URL."""
        from topsailai.skill_hub.skill_repo import install_from_git

        with self.assertRaises(ValueError) as context:
            install_from_git("")

        self.assertIn("Git URL cannot be empty", str(context.exception))

    @patch("topsailai.skill_hub.skill_repo.subprocess.run")
    def test_install_from_git_raises_error_when_git_not_installed(self, mock_run):
        """Test install_from_git raises ValueError when git is not installed."""
        from topsailai.skill_hub.skill_repo import install_from_git

        mock_run.side_effect = FileNotFoundError("git not found")

        with self.assertRaises(ValueError) as context:
            install_from_git("https://github.com/user/repo.git")

        self.assertIn("git is not installed", str(context.exception))

    @patch("topsailai.skill_hub.skill_repo.os.path.exists")
    def test_install_from_git_returns_existing_path(self, mock_exists):
        """Test install_from_git returns existing path without cloning."""
        from topsailai.skill_hub.skill_repo import install_from_git

        mock_exists.return_value = True

        result = install_from_git("https://github.com/user/repo.git")

        self.assertIn("github.com", result)
        self.assertIn("repo", result)


class TestInstallFromZip(unittest.TestCase):
    """Test cases for install_from_zip() function."""

    def test_install_from_zip_raises_error_for_nonexistent_file(self):
        """Test install_from_zip raises ValueError for non-existent file."""
        from topsailai.skill_hub.skill_repo import install_from_zip

        with patch("os.path.exists", return_value=False):
            with self.assertRaises(ValueError) as context:
                install_from_zip("/path/to/nonexistent.zip")

        self.assertIn("does not exist", str(context.exception))

    def test_install_from_zip_raises_error_for_non_zip_file(self):
        """Test install_from_zip raises ValueError for non-zip file."""
        from topsailai.skill_hub.skill_repo import install_from_zip

        with patch("os.path.exists", return_value=True):
            with self.assertRaises(ValueError) as context:
                install_from_zip("/path/to/file.txt")

        self.assertIn("not a zip file", str(context.exception))

    @patch("topsailai.skill_hub.skill_repo.os.path.exists")
    def test_install_from_zip_returns_existing_path(self, mock_exists):
        """Test install_from_zip returns existing path without extracting."""
        from topsailai.skill_hub.skill_repo import install_from_zip

        mock_exists.return_value = True

        result = install_from_zip("/path/to/skill.zip")

        self.assertIn("local", result)
        self.assertIn("skill", result)


class TestInstallFromUrl(unittest.TestCase):
    """Test cases for install_from_url() function."""

    def test_install_from_url_raises_error_for_invalid_url(self):
        """Test install_from_url raises ValueError for URL without path."""
        from topsailai.skill_hub.skill_repo import install_from_url

        with self.assertRaises(ValueError) as context:
            install_from_url("https://example.com/")

        self.assertIn("Invalid URL", str(context.exception))

    @patch("topsailai.skill_hub.skill_repo.os.path.exists")
    def test_install_from_url_returns_existing_path(self, mock_exists):
        """Test install_from_url returns existing path without downloading."""
        from topsailai.skill_hub.skill_repo import install_from_url

        mock_exists.return_value = True

        result = install_from_url("https://example.com/skill.zip")

        self.assertIn("example.com", result)
        self.assertIn("skill", result)


class TestInstallFromLocal(unittest.TestCase):
    """Test cases for install_from_local() function."""

    def test_install_from_local_raises_error_for_nonexistent_path(self):
        """Test install_from_local raises ValueError for non-existent path."""
        from topsailai.skill_hub.skill_repo import install_from_local

        with patch("os.path.exists", return_value=False):
            with self.assertRaises(ValueError) as context:
                install_from_local("/path/to/nonexistent")

        self.assertIn("does not exist", str(context.exception))

    def test_install_from_local_raises_error_for_file_instead_of_dir(self):
        """Test install_from_local raises ValueError when path is a file."""
        from topsailai.skill_hub.skill_repo import install_from_local

        with patch("os.path.exists", return_value=True):
            with patch("os.path.isdir", return_value=False):
                with self.assertRaises(ValueError) as context:
                    install_from_local("/path/to/file.txt")

        self.assertIn("not a directory", str(context.exception))

    @patch("topsailai.skill_hub.skill_repo.os.path.exists")
    def test_install_from_local_returns_existing_path(self, mock_exists):
        """Test install_from_local returns existing path without copying."""
        from topsailai.skill_hub.skill_repo import install_from_local

        mock_exists.return_value = True

        result = install_from_local("/path/to/myskill")

        self.assertIn("local", result)
        self.assertIn("myskill", result)


class TestUninstallSkill(unittest.TestCase):
    """Test cases for uninstall_skill() function."""

    @patch("topsailai.skill_hub.skill_repo.shutil.rmtree")
    @patch("topsailai.skill_hub.skill_repo.os.path.exists")
    def test_uninstall_skill_success(self, mock_exists, mock_rmtree):
        """Test uninstall_skill successfully removes skill folder."""
        from topsailai.skill_hub.skill_repo import uninstall_skill

        mock_exists.return_value = True

        result = uninstall_skill("local/myskill")

        self.assertTrue(result)
        mock_rmtree.assert_called_once()

    @patch("topsailai.skill_hub.skill_repo.os.path.exists")
    def test_uninstall_skill_returns_false_when_not_exists(self, mock_exists):
        """Test uninstall_skill returns False when skill doesn't exist."""
        from topsailai.skill_hub.skill_repo import uninstall_skill

        mock_exists.return_value = False

        result = uninstall_skill("local/nonexistent")

        self.assertFalse(result)

    def test_uninstall_skill_raises_error_for_empty_name(self):
        """Test uninstall_skill raises ValueError for empty skill name."""
        from topsailai.skill_hub.skill_repo import uninstall_skill

        with self.assertRaises(ValueError) as context:
            uninstall_skill("")

        self.assertIn("cannot be empty", str(context.exception))

    @patch("topsailai.skill_hub.skill_repo.os.path.exists")
    def test_uninstall_skill_raises_error_on_permission_error(self, mock_exists):
        """Test uninstall_skill raises ValueError on permission error."""
        from topsailai.skill_hub.skill_repo import uninstall_skill

        mock_exists.return_value = True

        with patch("shutil.rmtree", side_effect=PermissionError("Permission denied")):
            with self.assertRaises(ValueError) as context:
                uninstall_skill("local/myskill")

        self.assertIn("Permission denied", str(context.exception))


class TestListSkills(unittest.TestCase):
    """Test cases for list_skills() function."""

    @patch("topsailai.skill_hub.skill_repo.os.path.exists")
    def test_list_skills_returns_empty_when_folder_not_exists(self, mock_exists):
        """Test list_skills returns empty list when FOLDER_SKILL doesn't exist."""
        from topsailai.skill_hub.skill_repo import list_skills

        mock_exists.return_value = False

        result = list_skills()

        self.assertEqual(result, [])

    @patch("topsailai.skill_hub.skill_repo.get_file_skill_md")
    @patch("topsailai.skill_hub.skill_repo.os.path.isdir")
    @patch("topsailai.skill_hub.skill_repo.os.listdir")
    @patch("topsailai.skill_hub.skill_repo.os.path.exists")
    def test_list_skills_finds_skills_in_subfolders(
        self, mock_exists, mock_listdir, mock_isdir, mock_get_file
    ):
        """Test list_skills finds skills in subfolders."""
        from topsailai.skill_hub.skill_repo import list_skills

        mock_exists.return_value = True
        mock_listdir.return_value = ["subskill"]
        mock_isdir.return_value = True
        mock_get_file.return_value = "/path/to/subskill/SKILL.md"

        result = list_skills()

        self.assertIn("subskill", result)

    @patch("topsailai.skill_hub.skill_repo.get_file_skill_md")
    @patch("topsailai.skill_hub.skill_repo.os.path.isdir")
    @patch("topsailai.skill_hub.skill_repo.os.listdir")
    @patch("topsailai.skill_hub.skill_repo.os.path.exists")
    def test_list_skills_skips_non_skill_folders(
        self, mock_exists, mock_listdir, mock_isdir, mock_get_file
    ):
        """Test list_skills skips folders without SKILL.md."""
        from topsailai.skill_hub.skill_repo import list_skills

        mock_exists.return_value = True
        mock_listdir.return_value = ["notaskill"]
        mock_isdir.return_value = True
        mock_get_file.return_value = None

        result = list_skills()

        self.assertEqual(result, [])

    @patch("topsailai.skill_hub.skill_repo.get_file_skill_md")
    @patch("topsailai.skill_hub.skill_repo.os.path.isdir")
    @patch("topsailai.skill_hub.skill_repo.os.listdir")
    @patch("topsailai.skill_hub.skill_repo.os.path.exists")
    def test_list_skills_returns_sorted_list(
        self, mock_exists, mock_listdir, mock_isdir, mock_get_file
    ):
        """Test list_skills returns sorted list of skill names."""
        from topsailai.skill_hub.skill_repo import list_skills

        mock_exists.return_value = True
        mock_listdir.return_value = ["zskill", "askill", "mskill"]
        mock_isdir.return_value = True
        mock_get_file.return_value = "/path/to/skill/SKILL.md"

        result = list_skills()

        self.assertEqual(result, sorted(result))


if __name__ == "__main__":
    unittest.main()
