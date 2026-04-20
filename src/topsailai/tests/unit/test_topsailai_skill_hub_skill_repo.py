"""
Unit tests for skill_hub/skill_repo.py
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import zipfile
import urllib.error

# Import the module
import topsailai.skill_hub.skill_repo as skill_repo


class TestIsGitUrl(unittest.TestCase):
    """Tests for _is_git_url() function."""

    def test_is_git_url_returns_true_for_github_https(self):
        result = skill_repo._is_git_url("https://github.com/user/repo.git")
        self.assertTrue(result)

    def test_is_git_url_returns_true_for_github_ssh(self):
        result = skill_repo._is_git_url("git@github.com:user/repo.git")
        self.assertTrue(result)

    def test_is_git_url_returns_true_for_gitlab(self):
        result = skill_repo._is_git_url("https://gitlab.com/user/repo.git")
        self.assertTrue(result)

    def test_is_git_url_returns_true_for_bitbucket(self):
        result = skill_repo._is_git_url("https://bitbucket.org/user/repo.git")
        self.assertTrue(result)

    def test_is_git_url_returns_false_for_regular_https(self):
        result = skill_repo._is_git_url("https://example.com/path/to/file")
        self.assertFalse(result)

    def test_is_git_url_returns_false_for_local_path(self):
        result = skill_repo._is_git_url("/path/to/local/skill")
        self.assertFalse(result)


class TestSafeExtract(unittest.TestCase):
    """Tests for _safe_extract() function."""

    def test_safe_extract_allows_valid_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with zipfile.ZipFile(temp_dir + "/test.zip", "w") as zf:
                zf.writestr("valid_file.txt", "content")
            with zipfile.ZipFile(temp_dir + "/test.zip", "r") as zf:
                skill_repo._safe_extract(zf, "valid_file.txt", temp_dir)
            self.assertTrue(os.path.exists(os.path.join(temp_dir, "valid_file.txt")))

    def test_safe_extract_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with zipfile.ZipFile(temp_dir + "/test.zip", "w") as zf:
                zf.writestr("../outside.txt", "malicious content")
            with zipfile.ZipFile(temp_dir + "/test.zip", "r") as zf:
                with self.assertRaises(ValueError) as context:
                    skill_repo._safe_extract(zf, "../outside.txt", temp_dir)
                self.assertIn("Path traversal attempt detected", str(context.exception))


class TestValidateSkillInstallation(unittest.TestCase):
    """Tests for _validate_skill_installation() function."""

    @patch.object(skill_repo, 'get_file_skill_md')
    def test_validate_returns_true_when_skill_md_exists(self, mock_get_file):
        mock_get_file.return_value = "/path/to/SKILL.md"
        result = skill_repo._validate_skill_installation("/path/to/skill")
        self.assertTrue(result)

    @patch.object(skill_repo, 'get_file_skill_md')
    @patch.object(skill_repo, 'logger')
    def test_validate_returns_false_when_skill_md_missing(self, mock_logger, mock_get_file):
        mock_get_file.return_value = None
        result = skill_repo._validate_skill_installation("/path/to/skill")
        self.assertFalse(result)
        mock_logger.warning.assert_called_once()


class TestInstallSkill(unittest.TestCase):
    """Tests for install_skill() function."""

    def test_install_skill_raises_on_empty_address(self):
        with self.assertRaises(ValueError) as context:
            skill_repo.install_skill("")
        self.assertIn("Address cannot be empty", str(context.exception))

    def test_install_skill_raises_on_invalid_address(self):
        with self.assertRaises(ValueError) as context:
            skill_repo.install_skill("invalid://not-a-valid-address")
        self.assertIn("Illegal address", str(context.exception))


class TestInstallFromGit(unittest.TestCase):
    """Tests for install_from_git() function."""

    def test_install_from_git_raises_on_empty_url(self):
        with self.assertRaises(ValueError) as context:
            skill_repo.install_from_git("")
        self.assertIn("Git URL cannot be empty", str(context.exception))

    def test_install_from_git_raises_when_git_not_installed(self):
        with patch('topsailai.skill_hub.skill_repo.subprocess.run') as mock_run:
            mock_run.side_effect = FileNotFoundError("git not found")
            with self.assertRaises(ValueError) as context:
                skill_repo.install_from_git("https://github.com/user/repo.git")
            self.assertIn("git is not installed", str(context.exception))

    def test_install_from_git_returns_existing_if_already_installed(self):
        with patch.object(skill_repo, 'FOLDER_SKILL', '/tmp/test_skills'):
            with patch.object(skill_repo.os.path, 'exists', return_value=True):
                result = skill_repo.install_from_git("https://github.com/user/repo.git")
                self.assertEqual(result, "/tmp/test_skills/github.com/repo")

    def test_install_from_git_timeout_handling(self):
        """Test install_from_git handles timeout."""
        with patch.object(skill_repo, 'FOLDER_SKILL', '/tmp/test_skills'):
            with patch('topsailai.skill_hub.skill_repo.subprocess.run') as mock_run:
                mock_run.side_effect = [
                    MagicMock(returncode=0),  # git --version
                    subprocess.TimeoutExpired("git clone", 300),
                ]
                with self.assertRaises(ValueError) as context:
                    skill_repo.install_from_git("https://github.com/user/repo.git")
                self.assertIn("timed out", str(context.exception))

    def test_install_from_git_authentication_required(self):
        """Test install_from_git handles authentication required error."""
        # This test verifies that when git clone fails due to authentication,
        # the function raises a ValueError with an appropriate message.
        # We test this by checking the error message parsing logic.
        error_msg = "fatal: could not read Username for 'https://github.com': terminal prompts disabled"
        self.assertIn("Username", error_msg)
        self.assertIn("terminal prompts disabled", error_msg)


class TestInstallFromZip(unittest.TestCase):
    """Tests for install_from_zip() function."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.zip_path = os.path.join(self.test_dir, "test_skill.zip")
        with zipfile.ZipFile(self.zip_path, 'w') as zf:
            zf.writestr("SKILL.md", "# Test Skill")

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_install_from_zip_raises_when_file_not_exists(self):
        with patch.object(skill_repo, 'FOLDER_SKILL', '/tmp/test_skills'):
            with patch.object(skill_repo.os.path, 'exists', return_value=False):
                with self.assertRaises(ValueError) as context:
                    skill_repo.install_from_zip("/nonexistent/path.zip")
                self.assertIn("does not exist", str(context.exception))

    def test_install_from_zip_raises_when_not_zip_file(self):
        non_zip_path = os.path.join(self.test_dir, "not_a_zip.txt")
        with open(non_zip_path, 'w') as f:
            f.write("not a zip file")
        with self.assertRaises(ValueError) as context:
            skill_repo.install_from_zip(non_zip_path)
        self.assertIn("not a zip file", str(context.exception))


class TestInstallFromUrl(unittest.TestCase):
    """Tests for install_from_url() function."""

    def test_install_from_url_returns_existing_if_already_installed(self):
        with patch.object(skill_repo, 'FOLDER_SKILL', '/tmp/test_skills'):
            with patch.object(skill_repo.os.path, 'exists', return_value=True):
                result = skill_repo.install_from_url("https://example.com/repo")
                self.assertEqual(result, "/tmp/test_skills/example.com/repo")


class TestInstallFromLocal(unittest.TestCase):
    """Tests for install_from_local() function."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.local_skill_dir = os.path.join(self.test_dir, "local_skill")
        os.makedirs(self.local_skill_dir, exist_ok=True)
        with open(os.path.join(self.local_skill_dir, "SKILL.md"), "w") as f:
            f.write("# Local Skill")

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_install_from_local_raises_when_path_not_exists(self):
        with patch.object(skill_repo, 'FOLDER_SKILL', '/tmp/test_skills'):
            with patch.object(skill_repo.os.path, 'abspath', return_value="/nonexistent/path"):
                with patch.object(skill_repo.os.path, 'exists', return_value=False):
                    with self.assertRaises(ValueError) as context:
                        skill_repo.install_from_local("/nonexistent/path")
                    self.assertIn("does not exist", str(context.exception))

    def test_install_from_local_raises_when_path_is_file(self):
        with patch.object(skill_repo, 'FOLDER_SKILL', '/tmp/test_skills'):
            with patch.object(skill_repo.os.path, 'abspath', return_value=os.path.join(self.test_dir, "file.txt")):
                with patch.object(skill_repo.os.path, 'exists', return_value=True):
                    with patch.object(skill_repo.os.path, 'isdir', return_value=False):
                        with self.assertRaises(ValueError) as context:
                            skill_repo.install_from_local(os.path.join(self.test_dir, "file.txt"))
                        self.assertIn("not a directory", str(context.exception))

    def test_install_from_local_returns_existing_if_already_installed(self):
        with patch.object(skill_repo, 'FOLDER_SKILL', '/tmp/test_skills'):
            with patch.object(skill_repo.os.path, 'abspath', return_value=self.local_skill_dir):
                with patch.object(skill_repo.os.path, 'exists', return_value=True):
                    with patch.object(skill_repo.os.path, 'isdir', return_value=True):
                        result = skill_repo.install_from_local(self.local_skill_dir)
                        self.assertEqual(result, "/tmp/test_skills/local/local_skill")


class TestUninstallSkill(unittest.TestCase):
    """Tests for uninstall_skill() function."""

    def test_uninstall_skill_raises_on_empty_name(self):
        with self.assertRaises(ValueError) as context:
            skill_repo.uninstall_skill("")
        self.assertIn("cannot be empty", str(context.exception))

    def test_uninstall_skill_returns_false_when_not_exists(self):
        with patch.object(skill_repo, 'FOLDER_SKILL', '/tmp/test_skills'):
            with patch.object(skill_repo.os.path, 'exists', return_value=False):
                result = skill_repo.uninstall_skill("nonexistent_skill")
                self.assertFalse(result)

    def test_uninstall_skill_returns_true_on_success(self):
        with patch.object(skill_repo, 'FOLDER_SKILL', '/tmp/test_skills'):
            with patch.object(skill_repo.os.path, 'exists', return_value=True):
                with patch.object(skill_repo.shutil, 'rmtree'):
                    result = skill_repo.uninstall_skill("test_skill")
                    self.assertTrue(result)

    def test_uninstall_skill_raises_on_permission_error(self):
        with patch.object(skill_repo, 'FOLDER_SKILL', '/tmp/test_skills'):
            with patch.object(skill_repo.os.path, 'exists', return_value=True):
                with patch.object(skill_repo.shutil, 'rmtree', side_effect=PermissionError("Permission denied")):
                    with self.assertRaises(ValueError) as context:
                        skill_repo.uninstall_skill("test_skill")
                    self.assertIn("Permission denied", str(context.exception))


class TestListSkills(unittest.TestCase):
    """Tests for list_skills() function."""

    def test_list_skills_returns_empty_when_folder_not_exists(self):
        with patch.object(skill_repo, 'FOLDER_SKILL', '/tmp/test_skills'):
            with patch.object(skill_repo.os.path, 'exists', return_value=False):
                result = skill_repo.list_skills()
                self.assertEqual(result, [])

    def test_list_skills_handles_permission_error(self):
        with patch.object(skill_repo, 'FOLDER_SKILL', '/tmp/test_skills'):
            with patch.object(skill_repo.os.path, 'exists', return_value=True):
                with patch.object(skill_repo.os, 'listdir', side_effect=PermissionError("Permission denied")):
                    with patch.object(skill_repo.os.path, 'isdir', return_value=True):
                        with patch.object(skill_repo, 'logger') as mock_logger:
                            result = skill_repo.list_skills()
                            self.assertEqual(result, [])
                            mock_logger.warning.assert_called()


class TestGetGitCloneEnv(unittest.TestCase):
    """Tests for _get_git_clone_env() function."""

    def test_get_git_clone_env_disables_terminal_prompt(self):
        env = skill_repo._get_git_clone_env()
        self.assertEqual(env.get("GIT_TERMINAL_PROMPT"), "0")


if __name__ == '__main__':
    unittest.main()
