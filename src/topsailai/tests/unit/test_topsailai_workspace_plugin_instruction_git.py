"""Unit tests for the /git plugin instruction module."""

import os
import subprocess

import pytest

from topsailai.workspace.plugin_instruction import git


@pytest.fixture
def temp_git_repo(tmp_path, monkeypatch):
    """Create a temporary git repository for read-only command tests."""
    repo = tmp_path / "git_repo"
    repo.mkdir()

    def _git(*args):
        subprocess.run(
            ["git", *args],
            cwd=str(repo),
            check=True,
            capture_output=True,
        )

    _git("init")
    _git("config", "user.email", "test@example.com")
    _git("config", "user.name", "Test User")
    (repo / "file.txt").write_text("hello")
    _git("add", "file.txt")
    _git("commit", "-m", "initial")
    (repo / "file.txt").write_text("hello world")

    return str(repo)


class TestResolveWorkingDirectory:
    def test_project_folder_takes_precedence(self, monkeypatch, tmp_path):
        project = tmp_path / "project"
        pwd = tmp_path / "pwd"
        project.mkdir()
        pwd.mkdir()
        monkeypatch.setenv("TOPSAILAI_PROJECT_FOLDER", str(project))
        monkeypatch.setenv("TOPSAILAI_PWD", str(pwd))
        assert git._resolve_working_directory() == str(project)

    def test_pwd_used_when_project_folder_missing(self, monkeypatch, tmp_path):
        pwd = tmp_path / "pwd"
        pwd.mkdir()
        monkeypatch.delenv("TOPSAILAI_PROJECT_FOLDER", raising=False)
        monkeypatch.delenv("TOPSAILAI_PROJECT_WORKSPACE", raising=False)
        monkeypatch.setenv("TOPSAILAI_PWD", str(pwd))
        assert git._resolve_working_directory() == str(pwd)

    def test_project_workspace_alias(self, monkeypatch, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        monkeypatch.delenv("TOPSAILAI_PROJECT_FOLDER", raising=False)
        monkeypatch.setenv("TOPSAILAI_PROJECT_WORKSPACE", str(project))
        assert git._resolve_working_directory() == str(project)

    def test_falls_back_to_cwd(self, monkeypatch, tmp_path):
        monkeypatch.delenv("TOPSAILAI_PROJECT_FOLDER", raising=False)
        monkeypatch.delenv("TOPSAILAI_PROJECT_WORKSPACE", raising=False)
        monkeypatch.delenv("TOPSAILAI_PWD", raising=False)
        expected = os.path.abspath(os.getcwd())
        assert git._resolve_working_directory() == expected


class TestValidateSubcommand:
    def test_allows_read_only_subcommands(self):
        for sub in ["status", "log", "diff", "show", "branch", "tag", "remote"]:
            git._validate_subcommand([sub])  # should not raise

    def test_rejects_missing_subcommand(self):
        with pytest.raises(ValueError, match="No git subcommand"):
            git._validate_subcommand([])

    def test_rejects_unsupported_subcommand(self):
        with pytest.raises(ValueError, match="Unsupported git subcommand"):
            git._validate_subcommand(["push"])

    def test_rejects_write_branch_operations(self):
        with pytest.raises(ValueError, match="Write/destructive branch"):
            git._validate_subcommand(["branch", "-d", "feature"])

    def test_rejects_write_tag_operations(self):
        with pytest.raises(ValueError, match="Write/destructive tag"):
            git._validate_subcommand(["tag", "-a", "v1", "-m", "msg"])

    def test_allows_read_only_config(self):
        git._validate_subcommand(["config", "--list"])

    def test_rejects_write_config(self):
        with pytest.raises(ValueError, match="Only read-only git config"):
            git._validate_subcommand(["config", "user.name", "x"])


class TestRunGit:
    def test_status_in_temp_repo(self, temp_git_repo):
        output = git._run_git(["status"], cwd=temp_git_repo)
        assert "On branch" in output
        assert "file.txt" in output

    def test_log_in_temp_repo(self, temp_git_repo):
        output = git._run_git(["log", "--oneline"], cwd=temp_git_repo)
        assert "initial" in output

    def test_show_in_temp_repo(self, temp_git_repo):
        output = git._run_git(["show", "--stat"], cwd=temp_git_repo)
        assert "file.txt" in output

    def test_diff_in_temp_repo(self, temp_git_repo):
        output = git._run_git(["diff"], cwd=temp_git_repo)
        assert "hello" in output and "world" in output

    def test_missing_directory(self, tmp_path):
        missing = tmp_path / "missing"
        output = git._run_git(["status"], cwd=str(missing))
        assert "working directory does not exist" in output


class TestDispatcher:
    def test_git_status_uses_env_project_folder(self, temp_git_repo, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_PROJECT_FOLDER", temp_git_repo)
        output = git.git_status()
        assert "On branch" in output

    def test_git_log_uses_env_pwd(self, temp_git_repo, monkeypatch):
        monkeypatch.delenv("TOPSAILAI_PROJECT_FOLDER", raising=False)
        monkeypatch.delenv("TOPSAILAI_PROJECT_WORKSPACE", raising=False)
        monkeypatch.setenv("TOPSAILAI_PWD", temp_git_repo)
        output = git.git_log("--oneline")
        assert "initial" in output

    def test_git_rejects_destructive_command(self):
        with pytest.raises(ValueError, match="Unsupported git subcommand"):
            git.git("add", ".")

    def test_git_rejects_push(self):
        with pytest.raises(ValueError, match="Unsupported git subcommand"):
            git.git("push")

    def test_git_branch_lists_branches(self, temp_git_repo, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_PROJECT_FOLDER", temp_git_repo)
        output = git.git_branch()
        assert "main" in output or "master" in output

    def test_git_remote_lists_remotes(self, temp_git_repo, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_PROJECT_FOLDER", temp_git_repo)
        output = git.git_remote("-v")
        # No remotes configured in temp repo
        assert output.strip() == ""


class TestInstructionsRegistry:
    def test_instructions_exported(self):
        assert "git" in git.INSTRUCTIONS
        for name in [
            "git_status",
            "git_log",
            "git_diff",
            "git_show",
            "git_branch",
            "git_tag",
            "git_remote",
        ]:
            assert name in git.INSTRUCTIONS
