"""
Tests for topsailai.skill_hub.skill_repo module

Author: DawsonLin
Created: 2026-03-26
"""

import os
import pytest
import tempfile
import shutil
import zipfile
from unittest.mock import patch, MagicMock
from pathlib import Path

from topsailai.skill_hub import skill_repo
from topsailai.workspace.folder_constants import FOLDER_SKILL


# Sample skill path for testing
SAMPLE_SKILL_PATH = "/root/ai/TopsailAI/tests/unit/sample/skill_repo/hello_world"


class TestListSkills:
    """Test list_skills function"""

    def setup_method(self):
        """Setup temp directory for tests"""
        self.temp_dir = tempfile.mkdtemp()
        self.mock_skill_folder = os.path.join(self.temp_dir, "skills")
        os.makedirs(self.mock_skill_folder)

    def teardown_method(self):
        """Cleanup temp directory"""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_list_skills_empty_folder(self):
        """Test list_skills returns empty list when folder doesn't exist"""
        with patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', self.mock_skill_folder):
            result = skill_repo.list_skills()
            assert result == []

    def test_list_skills_with_skill_folders(self):
        """Test list_skills returns skill folders with SKILL.md"""
        with patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', self.mock_skill_folder):
            skill_folder = os.path.join(self.mock_skill_folder, "test_skill")
            os.makedirs(skill_folder)
            with open(os.path.join(skill_folder, "SKILL.md"), "w") as f:
                f.write("# Test Skill")
            result = skill_repo.list_skills()
            assert "test_skill" in result

    def test_list_skills_nested_folders(self):
        """Test list_skills handles nested skill folders"""
        with patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', self.mock_skill_folder):
            nested_folder = os.path.join(self.mock_skill_folder, "team", "test_skill")
            os.makedirs(nested_folder)
            with open(os.path.join(nested_folder, "skill.md"), "w") as f:
                f.write("# Test Skill")
            result = skill_repo.list_skills()
            assert "team/test_skill" in result

    def test_list_skills_with_sample_skill(self):
        """Test list_skills with sample skill folder"""
        with patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', self.mock_skill_folder):
            # Copy sample skill to mock folder
            sample_dest = os.path.join(self.mock_skill_folder, "hello_world")
            shutil.copytree(SAMPLE_SKILL_PATH, sample_dest)
            result = skill_repo.list_skills()
            assert "hello_world" in result


class TestIsGitUrl:
    """Test _is_git_url function"""

    def test_github_https(self):
        assert skill_repo._is_git_url("https://github.com/user/repo.git") is True
        assert skill_repo._is_git_url("https://github.com/user/repo") is True

    def test_gitlab_https(self):
        assert skill_repo._is_git_url("https://gitlab.com/user/repo.git") is True
        assert skill_repo._is_git_url("https://gitlab.com/user/repo") is True

    def test_bitbucket_https(self):
        assert skill_repo._is_git_url("https://bitbucket.org/user/repo.git") is True

    def test_git_ssh(self):
        assert skill_repo._is_git_url("git@github.com:user/repo.git") is True
        assert skill_repo._is_git_url("git@gitlab.com:user/repo.git") is True

    def test_git_suffix(self):
        assert skill_repo._is_git_url("https://example.com/repo.git") is True

    def test_non_git_url(self):
        assert skill_repo._is_git_url("https://example.com/file.zip") is False
        assert skill_repo._is_git_url("https://example.com/repo") is False
        assert skill_repo._is_git_url("http://localhost:8080/api") is False


class TestValidateSkillInstallation:
    """Test _validate_skill_installation function"""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()

    def teardown_method(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_valid_skill_with_skill_md(self):
        skill_folder = os.path.join(self.temp_dir, "valid_skill")
        os.makedirs(skill_folder)
        with open(os.path.join(skill_folder, "SKILL.md"), "w") as f:
            f.write("# Test Skill")
        result = skill_repo._validate_skill_installation(skill_folder)
        assert result is True

    def test_valid_skill_with_skill_lowercase(self):
        skill_folder = os.path.join(self.temp_dir, "valid_skill")
        os.makedirs(skill_folder)
        with open(os.path.join(skill_folder, "skill.md"), "w") as f:
            f.write("# Test Skill")
        result = skill_repo._validate_skill_installation(skill_folder)
        assert result is True

    def test_invalid_skill_no_md(self):
        skill_folder = os.path.join(self.temp_dir, "invalid_skill")
        os.makedirs(skill_folder)
        result = skill_repo._validate_skill_installation(skill_folder)
        assert result is False

    def test_validate_sample_skill(self):
        """Test validation with sample skill folder"""
        result = skill_repo._validate_skill_installation(SAMPLE_SKILL_PATH)
        assert result is True


class TestSafeExtract:
    """Test _safe_extract function"""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()

    def teardown_method(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_safe_extract_valid_path(self):
        zip_path = os.path.join(self.temp_dir, "test.zip")
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr("test.txt", "test content")
        with zipfile.ZipFile(zip_path, 'r') as zf:
            skill_repo._safe_extract(zf, "test.txt", self.temp_dir)
        assert os.path.exists(os.path.join(self.temp_dir, "test.txt"))

    def test_safe_extract_path_traversal_blocked(self):
        zip_path = os.path.join(self.temp_dir, "test.zip")
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr("../outside.txt", "malicious content")
        with zipfile.ZipFile(zip_path, 'r') as zf:
            with pytest.raises(ValueError):
                skill_repo._safe_extract(zf, "../outside.txt", self.temp_dir)


class TestInstallSkill:
    """Test install_skill function"""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.skill_folder = os.path.join(self.temp_dir, "skills")
        os.makedirs(self.skill_folder)

    def teardown_method(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_install_skill_empty_address(self):
        with patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', self.skill_folder):
            with pytest.raises(ValueError, match="Address cannot be empty"):
                skill_repo.install_skill("")

    def test_install_skill_invalid_address(self):
        with patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', self.skill_folder):
            with pytest.raises(ValueError, match="Illegal address"):
                skill_repo.install_skill("invalid://address")

    def test_install_skill_local_path(self):
        """Test install_skill with local path"""
        # Create a real temp directory that exists
        real_local_path = os.path.join(self.temp_dir, "real_local")
        os.makedirs(real_local_path)
        with open(os.path.join(real_local_path, "SKILL.md"), "w") as f:
            f.write("# Test Skill")
        with patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', self.skill_folder):
            result = skill_repo.install_skill(real_local_path)
        expected = os.path.join(self.skill_folder, "local", "real_local")
        assert result == expected
        assert os.path.exists(expected)

    def test_install_skill_git_url(self):
        with patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', self.skill_folder):
            with patch('topsailai.skill_hub.skill_repo._is_git_url', return_value=True):
                with patch('topsailai.skill_hub.skill_repo.install_from_git') as mock_install:
                    mock_install.return_value = os.path.join(self.skill_folder, "github.com", "test")
                    result = skill_repo.install_skill("https://github.com/user/repo.git")
                    mock_install.assert_called_once_with("https://github.com/user/repo.git")
                    assert result == mock_install.return_value

    def test_install_skill_zip_url(self):
        with patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', self.skill_folder):
            with patch('topsailai.skill_hub.skill_repo._is_git_url', return_value=False):
                with patch('os.path.exists', return_value=False):
                    with patch('topsailai.skill_hub.skill_repo.install_from_url') as mock_install:
                        mock_install.return_value = os.path.join(self.skill_folder, "example.com", "test")
                        result = skill_repo.install_skill("https://example.com/skill.zip")
                        mock_install.assert_called_once_with("https://example.com/skill.zip")
                        assert result == mock_install.return_value


class TestInstallFromLocal:
    """Test install_from_local function"""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.skill_folder = os.path.join(self.temp_dir, "skills")
        os.makedirs(self.skill_folder)

    def teardown_method(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_install_from_local_nonexistent(self):
        with patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', self.skill_folder):
            with pytest.raises(ValueError, match="Local path does not exist"):
                skill_repo.install_from_local("/nonexistent/path")

    def test_install_from_local_file_not_directory(self):
        file_path = os.path.join(self.temp_dir, "file.txt")
        with open(file_path, "w") as f:
            f.write("test")
        with patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', self.skill_folder):
            with pytest.raises(ValueError, match="Local path is not a directory"):
                skill_repo.install_from_local(file_path)

    def test_install_from_local_without_skill_md(self):
        source_folder = os.path.join(self.temp_dir, "source_skill")
        os.makedirs(source_folder)
        with patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', self.skill_folder):
            with pytest.raises(ValueError, match="does not contain valid SKILL.md"):
                skill_repo.install_from_local(source_folder)

    def test_install_from_local_with_skill_md(self):
        source_folder = os.path.join(self.temp_dir, "source_skill")
        os.makedirs(source_folder)
        with open(os.path.join(source_folder, "SKILL.md"), "w") as f:
            f.write("# Test Skill")
        with patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', self.skill_folder):
            result = skill_repo.install_from_local(source_folder)
        expected = os.path.join(self.skill_folder, "local", "source_skill")
        assert result == expected
        assert os.path.exists(expected)
        assert os.path.exists(os.path.join(expected, "SKILL.md"))

    def test_install_from_local_already_exists(self):
        source_folder = os.path.join(self.temp_dir, "source_skill")
        os.makedirs(source_folder)
        with open(os.path.join(source_folder, "SKILL.md"), "w") as f:
            f.write("# Test Skill")
        dest_folder = os.path.join(self.skill_folder, "local", "source_skill")
        os.makedirs(dest_folder)
        with open(os.path.join(dest_folder, "SKILL.md"), "w") as f:
            f.write("# Existing Skill")
        with patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', self.skill_folder):
            result = skill_repo.install_from_local(source_folder)
        assert result == dest_folder

    def test_install_from_local_with_sample_skill(self):
        """Test install_from_local with sample skill"""
        with patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', self.skill_folder):
            result = skill_repo.install_from_local(SAMPLE_SKILL_PATH)
        expected = os.path.join(self.skill_folder, "local", "hello_world")
        assert result == expected
        assert os.path.exists(expected)
        assert os.path.exists(os.path.join(expected, "SKILL.md"))


class TestUninstallSkill:
    """Test uninstall_skill function"""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.skill_folder = os.path.join(self.temp_dir, "skills")
        os.makedirs(self.skill_folder)

    def teardown_method(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_uninstall_skill_empty_name(self):
        with patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', self.skill_folder):
            with pytest.raises(ValueError, match="Skill name cannot be empty"):
                skill_repo.uninstall_skill("")

    def test_uninstall_nonexistent_skill(self):
        with patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', self.skill_folder):
            result = skill_repo.uninstall_skill("nonexistent")
            assert result is False

    def test_uninstall_existing_skill(self):
        skill_path = os.path.join(self.skill_folder, "test_skill")
        os.makedirs(skill_path)
        with open(os.path.join(skill_path, "SKILL.md"), "w") as f:
            f.write("# Test")
        with patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', self.skill_folder):
            result = skill_repo.uninstall_skill("test_skill")
        assert result is True
        assert not os.path.exists(skill_path)

    def test_uninstall_nested_skill(self):
        skill_path = os.path.join(self.skill_folder, "team", "test_skill")
        os.makedirs(skill_path)
        with open(os.path.join(skill_path, "SKILL.md"), "w") as f:
            f.write("# Test")
        with patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', self.skill_folder):
            result = skill_repo.uninstall_skill("team/test_skill")
        assert result is True
        assert not os.path.exists(skill_path)


class TestInstallFromGit:
    """Test install_from_git function"""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.skill_folder = os.path.join(self.temp_dir, "skills")
        os.makedirs(self.skill_folder)

    def teardown_method(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_install_from_git_empty_url(self):
        with patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', self.skill_folder):
            with pytest.raises(ValueError, match="Git URL cannot be empty"):
                skill_repo.install_from_git("")

    def test_install_from_git_invalid_url(self):
        with patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', self.skill_folder):
            with pytest.raises(ValueError, match="Repository not found|Invalid git URL"):
                skill_repo.install_from_git("not-a-valid-url")

    @patch('subprocess.run')
    def test_install_from_git_git_not_installed(self, mock_run):
        mock_run.side_effect = FileNotFoundError("git not found")
        with patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', self.skill_folder):
            with pytest.raises(ValueError, match="git is not installed"):
                skill_repo.install_from_git("https://github.com/user/repo.git")


class TestInstallFromZip:
    """Test install_from_zip function"""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.skill_folder = os.path.join(self.temp_dir, "skills")
        os.makedirs(self.skill_folder)

    def teardown_method(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_install_from_zip_nonexistent(self):
        with patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', self.skill_folder):
            with pytest.raises(ValueError, match="Zip file does not exist"):
                skill_repo.install_from_zip("/nonexistent.zip")

    def test_install_from_zip_not_zip_file(self):
        not_zip = os.path.join(self.temp_dir, "not_zip.txt")
        with open(not_zip, "w") as f:
            f.write("not a zip")
        with patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', self.skill_folder):
            with pytest.raises(ValueError, match="File is not a zip file"):
                skill_repo.install_from_zip(not_zip)

    def test_install_from_zip_invalid_zip(self):
        invalid_zip = os.path.join(self.temp_dir, "invalid.zip")
        with open(invalid_zip, "w") as f:
            f.write("not a valid zip")
        with patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', self.skill_folder):
            with pytest.raises(ValueError, match="Invalid zip file"):
                skill_repo.install_from_zip(invalid_zip)

    def test_install_from_zip_without_skill_md(self):
        zip_path = os.path.join(self.temp_dir, "test.zip")
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr("file.txt", "content")
        with patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', self.skill_folder):
            with pytest.raises(ValueError, match="does not contain valid SKILL.md"):
                skill_repo.install_from_zip(zip_path)

    def test_install_from_zip_with_skill_md(self):
        zip_path = os.path.join(self.temp_dir, "test.zip")
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr("SKILL.md", "# Test Skill")
            zf.writestr("file.txt", "content")
        with patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', self.skill_folder):
            result = skill_repo.install_from_zip(zip_path)
        expected = os.path.join(self.skill_folder, "local", "test")
        assert result == expected
        assert os.path.exists(expected)
        assert os.path.exists(os.path.join(expected, "SKILL.md"))

    def test_install_from_zip_with_sample_skill(self):
        """Test install_from_zip with sample skill"""
        # Create a zip from the sample skill
        zip_path = os.path.join(self.temp_dir, "hello_world.zip")
        with zipfile.ZipFile(zip_path, 'w') as zf:
            for root, dirs, files in os.walk(SAMPLE_SKILL_PATH):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, SAMPLE_SKILL_PATH)
                    zf.write(file_path, arcname)
        
        with patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', self.skill_folder):
            result = skill_repo.install_from_zip(zip_path)
        expected = os.path.join(self.skill_folder, "local", "hello_world")
        assert result == expected
        assert os.path.exists(expected)
        assert os.path.exists(os.path.join(expected, "SKILL.md"))


class TestInstallFromUrl:
    """Test install_from_url function"""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.skill_folder = os.path.join(self.temp_dir, "skills")
        os.makedirs(self.skill_folder)

    def teardown_method(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_install_from_url_invalid_url(self):
        with patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', self.skill_folder):
            with pytest.raises(ValueError, match="unknown url type|Invalid URL"):
                skill_repo.install_from_url("not-a-url")


class TestEdgeCases:
    """Edge case tests for skill_repo functions"""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.skill_folder = os.path.join(self.temp_dir, "skills")
        os.makedirs(self.skill_folder)

    def teardown_method(self):
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_list_skills_permission_error(self):
        with patch('topsailai.skill_hub.skill_repo.FOLDER_SKILL', self.skill_folder):
            no_access = os.path.join(self.skill_folder, "no_access")
            os.makedirs(no_access)
            try:
                os.chmod(no_access, 0o000)
                result = skill_repo.list_skills()
                assert isinstance(result, list)
            except PermissionError:
                pass
            finally:
                try:
                    os.chmod(no_access, 0o755)
                except:
                    pass

    def test_safe_extract_empty_member(self):
        zip_path = os.path.join(self.temp_dir, "test.zip")
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr("file.txt", "content")
        with zipfile.ZipFile(zip_path, 'r') as zf:
            skill_repo._safe_extract(zf, "file.txt", self.temp_dir)
        assert os.path.exists(os.path.join(self.temp_dir, "file.txt"))
