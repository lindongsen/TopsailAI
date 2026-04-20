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

from topsailai.skill_hub import skill_repo


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

    @patch('topsailai.skill_hub.skill_repo.get_file_skill_md')
    def test_validate_returns_true_when_skill_md_exists(self, mock_get_file):
        mock_get_file.return_value = "/path/to/SKILL.md"
        result = skill_repo._validate_skill_installation("/path/to/skill")
        self.assertTrue(result)

    @patch('topsailai.skill_hub.skill_repo.get_file_skill_md')
    @patch('topsailai.skill_hub.skill_repo.logger')
    def test_validate_returns_false_when_skill_md_missing(self, mock_logger, mock_get_file):
        mock_get_file.return_value = None
        result = skill_repo._validate_skill_installation("/path/to/skill")
        self.assertFalse(result)
        mock_logger.warning.assert_called_once()


class TestInstallSkill(unittest.TestCase):
    """Tests for install_skill() function."""

    @patch('topsailai.skill_hub.skill_repo.install_from_git')
    @patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', '/tmp/test_skills')
    def test_install_skill_calls_install_from_git_for_git_url(self, mock_install_git):
        mock_install_git.return_value = "/tmp/test_skills/github.com/repo"
        result = skill_repo.install_skill("https://github.com/user/repo.git")
        mock_install_git.assert_called_once_with("https://github.com/user/repo.git")
        self.assertEqual(result, "/tmp/test_skills/github.com/repo")

    @patch('topsailai.skill_hub.skill_repo.install_from_url')
    @patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', '/tmp/test_skills')
    def test_install_skill_calls_install_from_url_for_http(self, mock_install_url):
        mock_install_url.return_value = "/tmp/test_skills/example.com/repo"
        result = skill_repo.install_skill("https://example.com/repo")
        mock_install_url.assert_called_once_with("https://example.com/repo")
        self.assertEqual(result, "/tmp/test_skills/example.com/repo")

    @patch('topsailai.skill_hub.skill_repo.install_from_zip')
    @patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', '/tmp/test_skills')
    def test_install_skill_calls_install_from_zip_for_zip_file(self, mock_install_zip):
        mock_install_zip.return_value = "/tmp/test_skills/local/skill"
        result = skill_repo.install_skill("/path/to/skill.zip")
        mock_install_zip.assert_called_once_with("/path/to/skill.zip")
        self.assertEqual(result, "/tmp/test_skills/local/skill")

    @patch('topsailai.skill_hub.skill_repo.install_from_local')
    @patch('topsailai.skill_hub.skill_repo.os.path.exists')
    @patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', '/tmp/test_skills')
    def test_install_skill_calls_install_from_local_for_existing_path(self, mock_exists, mock_install_local):
        mock_exists.return_value = True
        mock_install_local.return_value = "/tmp/test_skills/local/skill"
        result = skill_repo.install_skill("/path/to/local/skill")
        mock_install_local.assert_called_once_with("/path/to/local/skill")
        self.assertEqual(result, "/tmp/test_skills/local/skill")

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

    @patch('topsailai.skill_hub.skill_repo.subprocess.run')
    def test_install_from_git_raises_on_empty_url(self, mock_subprocess):
        with self.assertRaises(ValueError) as context:
            skill_repo.install_from_git("")
        self.assertIn("Git URL cannot be empty", str(context.exception))

    @patch('topsailai.skill_hub.skill_repo.subprocess.run')
    def test_install_from_git_raises_when_git_not_installed(self, mock_subprocess):
        mock_subprocess.side_effect = FileNotFoundError("git not found")
        with self.assertRaises(ValueError) as context:
            skill_repo.install_from_git("https://github.com/user/repo.git")
        self.assertIn("git is not installed", str(context.exception))

    @patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', '/tmp/test_skills')
    @patch('topsailai.skill_hub.skill_repo.os.path.exists')
    def test_install_from_git_returns_existing_if_already_installed(self, mock_exists):
        mock_exists.return_value = True
        result = skill_repo.install_from_git("https://github.com/user/repo.git")
        self.assertEqual(result, "/tmp/test_skills/github.com/repo")


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

    @patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', '/tmp/test_skills')
    @patch('topsailai.skill_hub.skill_repo._validate_skill_installation')
    @patch('topsailai.skill_hub.skill_repo.os.path.exists')
    @patch('topsailai.skill_hub.skill_repo.os.makedirs')
    @patch('topsailai.skill_hub.skill_repo.shutil.copytree')
    @patch('topsailai.skill_hub.skill_repo.shutil.move')
    @patch('topsailai.skill_hub.skill_repo.shutil.rmtree')
    def test_install_from_zip_raises_when_file_not_exists(self, mock_rmtree, mock_move, mock_copytree, mock_makedirs, mock_exists, mock_validate):
        mock_exists.return_value = False
        with self.assertRaises(ValueError) as context:
            skill_repo.install_from_zip("/nonexistent/path.zip")
        self.assertIn("does not exist", str(context.exception))

    @patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', '/tmp/test_skills')
    def test_install_from_zip_raises_when_not_zip_file(self):
        non_zip_path = os.path.join(self.test_dir, "not_a_zip.txt")
        with open(non_zip_path, 'w') as f:
            f.write("not a zip file")
        with self.assertRaises(ValueError) as context:
            skill_repo.install_from_zip(non_zip_path)
        self.assertIn("not a zip file", str(context.exception))


class TestInstallFromUrl(unittest.TestCase):
    """Tests for install_from_url() function."""

    @patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', '/tmp/test_skills')
    @patch('topsailai.skill_hub.skill_repo._validate_skill_installation')
    @patch('topsailai.skill_hub.skill_repo.os.path.exists')
    @patch('topsailai.skill_hub.skill_repo.os.makedirs')
    @patch('topsailai.skill_hub.skill_repo.shutil.move')
    @patch('topsailai.skill_hub.skill_repo.shutil.rmtree')
    @patch('topsailai.skill_hub.skill_repo.urllib.request.urlopen')
    def test_install_from_url_returns_existing_if_already_installed(self, mock_urlopen, mock_rmtree, mock_move, mock_makedirs, mock_exists, mock_validate):
        mock_exists.return_value = True
        result = skill_repo.install_from_url("https://example.com/repo")
        self.assertEqual(result, "/tmp/test_skills/example.com/repo")
        mock_urlopen.assert_not_called()


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

    @patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', '/tmp/test_skills')
    @patch('topsailai.skill_hub.skill_repo.os.path.abspath')
    @patch('topsailai.skill_hub.skill_repo.os.path.exists')
    def test_install_from_local_raises_when_path_not_exists(self, mock_exists, mock_abspath):
        mock_abspath.return_value = "/nonexistent/path"
        mock_exists.return_value = False
        with self.assertRaises(ValueError) as context:
            skill_repo.install_from_local("/nonexistent/path")
        self.assertIn("does not exist", str(context.exception))

    @patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', '/tmp/test_skills')
    @patch('topsailai.skill_hub.skill_repo.os.path.abspath')
    @patch('topsailai.skill_hub.skill_repo.os.path.exists')
    @patch('topsailai.skill_hub.skill_repo.os.path.isdir')
    def test_install_from_local_raises_when_path_is_file(self, mock_isdir, mock_exists, mock_abspath):
        mock_abspath.return_value = os.path.join(self.test_dir, "file.txt")
        mock_exists.return_value = True
        mock_isdir.return_value = False
        with self.assertRaises(ValueError) as context:
            skill_repo.install_from_local(os.path.join(self.test_dir, "file.txt"))
        self.assertIn("not a directory", str(context.exception))

    @patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', '/tmp/test_skills')
    @patch('topsailai.skill_hub.skill_repo._validate_skill_installation')
    @patch('topsailai.skill_hub.skill_repo.os.path.abspath')
    @patch('topsailai.skill_hub.skill_repo.os.path.exists')
    @patch('topsailai.skill_hub.skill_repo.os.path.isdir')
    def test_install_from_local_returns_existing_if_already_installed(self, mock_isdir, mock_exists, mock_abspath, mock_validate):
        mock_abspath.return_value = self.local_skill_dir
        mock_exists.return_value = True
        mock_isdir.return_value = True
        result = skill_repo.install_from_local(self.local_skill_dir)
        self.assertEqual(result, "/tmp/test_skills/local/local_skill")


class TestUninstallSkill(unittest.TestCase):
    """Tests for uninstall_skill() function."""

    def test_uninstall_skill_raises_on_empty_name(self):
        with self.assertRaises(ValueError) as context:
            skill_repo.uninstall_skill("")
        self.assertIn("cannot be empty", str(context.exception))

    @patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', '/tmp/test_skills')
    @patch('topsailai.skill_hub.skill_repo.os.path.exists')
    def test_uninstall_skill_returns_false_when_not_exists(self, mock_exists):
        mock_exists.return_value = False
        result = skill_repo.uninstall_skill("nonexistent_skill")
        self.assertFalse(result)

    @patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', '/tmp/test_skills')
    @patch('topsailai.skill_hub.skill_repo.shutil.rmtree')
    @patch('topsailai.skill_hub.skill_repo.os.path.exists')
    def test_uninstall_skill_returns_true_on_success(self, mock_exists, mock_rmtree):
        mock_exists.return_value = True
        result = skill_repo.uninstall_skill("test_skill")
        self.assertTrue(result)
        mock_rmtree.assert_called_once()

    @patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', '/tmp/test_skills')
    @patch('topsailai.skill_hub.skill_repo.shutil.rmtree')
    @patch('topsailai.skill_hub.skill_repo.os.path.exists')
    def test_uninstall_skill_raises_on_permission_error(self, mock_exists, mock_rmtree):
        mock_exists.return_value = True
        mock_rmtree.side_effect = PermissionError("Permission denied")
        with self.assertRaises(ValueError) as context:
            skill_repo.uninstall_skill("test_skill")
        self.assertIn("Permission denied", str(context.exception))


class TestListSkills(unittest.TestCase):
    """Tests for list_skills() function."""

    @patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', '/tmp/test_skills')
    @patch('topsailai.skill_hub.skill_repo.os.path.exists')
    def test_list_skills_returns_empty_when_folder_not_exists(self, mock_exists):
        mock_exists.return_value = False
        result = skill_repo.list_skills()
        self.assertEqual(result, [])


# === STEP 16: ENHANCED TESTS FOR skill_repo.py ===

class TestInstallFromGitEnhanced(unittest.TestCase):
    """Enhanced tests for install_from_git() function."""

    @patch('topsailai.skill_hub.skill_repo.subprocess.run')
    @patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', '/tmp/test_skills')
    def test_install_from_git_handles_branch_fallback(self, mock_run):
        """Test install_from_git falls back to master when main not found."""
        mock_run.side_effect = [
            MagicMock(returncode=0),
            MagicMock(returncode=1, stderr="branch not found"),
            MagicMock(returncode=0, stderr=""),
        ]
        with patch('topsailai.skill_hub.skill_repo.os.path.exists', return_value=False):
            with patch('topsailai.skill_hub.skill_repo.os.makedirs'):
                with patch('topsailai.skill_hub.skill_repo.shutil.copytree'):
                    with patch('topsailai.skill_hub.skill_repo.shutil.move'):
                        with patch('topsailai.skill_hub.skill_repo._validate_skill_installation', return_value=True):
                            with patch('topsailai.skill_hub.skill_repo.os.listdir', return_value=['file.txt']):
                                with patch('topsailai.skill_hub.skill_repo.tempfile.mkdtemp') as mock_temp:
                                    mock_temp.return_value = '/tmp/fake_temp'
                                    with patch('topsailai.skill_hub.skill_repo.shutil.rmtree'):
                                        result = skill_repo.install_from_git("https://github.com/user/repo.git")
                                        self.assertEqual(result, "/tmp/test_skills/github.com/repo")

    @patch('topsailai.skill_hub.skill_repo.subprocess.run')
    @patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', '/tmp/test_skills')
    def test_install_from_git_timeout_handling(self, mock_run):
        """Test install_from_git handles timeout."""
        mock_run.side_effect = [
            MagicMock(returncode=0),
            subprocess.TimeoutExpired("git clone", 300),
        ]
        with self.assertRaises(ValueError) as context:
            skill_repo.install_from_git("https://github.com/user/repo.git")
        self.assertIn("timed out", str(context.exception))

    @patch('topsailai.skill_hub.skill_repo.subprocess.run')
    @patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', '/tmp/test_skills')
    def test_install_from_git_repository_not_found(self, mock_run):
        """Test install_from_git handles repository not found."""
        mock_run.side_effect = [
            MagicMock(returncode=0),
            MagicMock(returncode=128, stderr="Repository not found"),
        ]
        with patch('topsailai.skill_hub.skill_repo.os.path.exists', return_value=False):
            with patch('topsailai.skill_hub.skill_repo.os.makedirs'):
                with patch('topsailai.skill_hub.skill_repo.tempfile.mkdtemp') as mock_temp:
                    mock_temp.return_value = '/tmp/fake_temp'
                    with patch('topsailai.skill_hub.skill_repo.shutil.rmtree'):
                        with self.assertRaises(ValueError) as context:
                            skill_repo.install_from_git("https://github.com/user/nonexistent.git")
                        self.assertIn("Failed to install", str(context.exception))

    @patch('topsailai.skill_hub.skill_repo.subprocess.run')
    @patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', '/tmp/test_skills')
    def test_install_from_git_atomic_installation(self, mock_run):
        """Test install_from_git uses atomic installation pattern."""
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        with patch('topsailai.skill_hub.skill_repo.os.path.exists', side_effect=[False, False, True]):
            with patch('topsailai.skill_hub.skill_repo.os.makedirs'):
                with patch('topsailai.skill_hub.skill_repo.shutil.copytree') as mock_copy:
                    with patch('topsailai.skill_hub.skill_repo.shutil.move') as mock_move:
                        with patch('topsailai.skill_hub.skill_repo._validate_skill_installation', return_value=True):
                            with patch('topsailai.skill_hub.skill_repo.os.listdir', return_value=['file.txt']):
                                with patch('topsailai.skill_hub.skill_repo.tempfile.mkdtemp') as mock_temp:
                                    mock_temp.return_value = '/tmp/fake_temp'
                                    with patch('topsailai.skill_hub.skill_repo.shutil.rmtree'):
                                        skill_repo.install_from_git("https://github.com/user/repo.git")
                                        self.assertTrue(mock_copy.called)
                                        self.assertTrue(mock_move.called)


class TestInstallFromZipEnhanced(unittest.TestCase):
    """Enhanced tests for install_from_zip() function."""

    @patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', '/tmp/test_skills')
    @patch('topsailai.skill_hub.skill_repo.os.path.exists')
    @patch('topsailai.skill_hub.skill_repo.os.path.abspath')
    def test_install_from_zip_bad_zip_file(self, mock_abspath, mock_exists):
        """Test install_from_zip handles bad zip file (not ending with .zip)."""
        mock_abspath.return_value = "/path/to/corrupt.txt"
        mock_exists.return_value = True
        
        with self.assertRaises(ValueError) as context:
            skill_repo.install_from_zip("/path/to/corrupt.txt")
        self.assertIn("not a zip file", str(context.exception))


class TestInstallFromUrlEnhanced(unittest.TestCase):
    """Enhanced tests for install_from_url() function."""

    @patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', '/tmp/test_skills')
    @patch('topsailai.skill_hub.skill_repo._validate_skill_installation')
    @patch('topsailai.skill_hub.skill_repo.os.path.exists')
    @patch('topsailai.skill_hub.skill_repo.os.makedirs')
    @patch('topsailai.skill_hub.skill_repo.shutil.move')
    @patch('topsailai.skill_hub.skill_repo.tempfile.mkdtemp')
    @patch('topsailai.skill_hub.skill_repo.shutil.rmtree')
    @patch('topsailai.skill_hub.skill_repo.urllib.request.urlopen')
    @patch('topsailai.skill_hub.skill_repo.zipfile.is_zipfile')
    def test_install_from_url_handles_url_error(
        self, mock_is_zip, mock_urlopen, mock_rmtree, mock_temp, 
        mock_move, mock_makedirs, mock_exists, mock_validate
    ):
        """Test install_from_url handles URL errors gracefully."""
        mock_exists.return_value = False
        mock_temp.return_value = "/tmp/fake_temp"
        mock_is_zip.return_value = False
        
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")
        
        with self.assertRaises(ValueError) as context:
            skill_repo.install_from_url("https://example.com/skill.zip")
        self.assertIn("Failed to download", str(context.exception))


class TestListSkillsEnhanced(unittest.TestCase):
    """Enhanced tests for list_skills() function."""

    @patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', '/tmp/test_skills')
    @patch('topsailai.skill_hub.skill_repo.get_file_skill_md')
    @patch('topsailai.skill_hub.skill_repo.os.path.exists')
    @patch('topsailai.skill_hub.skill_repo.os.listdir')
    @patch('topsailai.skill_hub.skill_repo.os.path.isdir')
    @patch('topsailai.skill_hub.skill_repo.logger')
    def test_list_skills_handles_permission_error(
        self, mock_logger, mock_isdir, mock_listdir, mock_exists, mock_get_file
    ):
        """Test list_skills handles permission errors gracefully."""
        mock_exists.return_value = True
        mock_listdir.side_effect = PermissionError("Permission denied")
        mock_isdir.return_value = True
        
        result = skill_repo.list_skills()
        self.assertEqual(result, [])
        mock_logger.warning.assert_called()

    @patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', '/tmp/test_skills')
    @patch('topsailai.skill_hub.skill_repo.get_file_skill_md')
    @patch('topsailai.skill_hub.skill_repo.os.path.exists')
    @patch('topsailai.skill_hub.skill_repo.os.listdir')
    @patch('topsailai.skill_hub.skill_repo.os.path.isdir')
    def test_list_skills_respects_max_depth(
        self, mock_isdir, mock_listdir, mock_exists, mock_get_file
    ):
        """Test list_skills respects MAX_DEPTH limit."""
        mock_exists.return_value = True
        mock_listdir.return_value = ['subdir']
        mock_isdir.return_value = True
        mock_get_file.return_value = None
        
        result = skill_repo.list_skills()
        self.assertIsInstance(result, list)


class TestUninstallSkillEnhancedStep16(unittest.TestCase):
    """Enhanced tests for uninstall_skill() function - Step 16."""

    @patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', '/tmp/test_skills')
    @patch('topsailai.skill_hub.skill_repo.shutil.rmtree')
    @patch('topsailai.skill_hub.skill_repo.os.path.exists')
    def test_uninstall_skill_handles_os_error(self, mock_exists, mock_rmtree):
        """Test uninstall_skill handles OSError gracefully."""
        mock_exists.return_value = True
        mock_rmtree.side_effect = OSError("Disk full")
        
        with self.assertRaises(ValueError) as context:
            skill_repo.uninstall_skill("test_skill")
        self.assertIn("Failed to remove skill folder", str(context.exception))

    @patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', '/tmp/test_skills')
    @patch('topsailai.skill_hub.skill_repo.os.path.exists')
    def test_uninstall_skill_not_found(self, mock_exists):
        """Test uninstall_skill returns False for non-existent skill."""
        mock_exists.return_value = False
        
        result = skill_repo.uninstall_skill("nonexistent_skill")
        self.assertFalse(result)


if __name__ == '__main__':
    unittest.main()
