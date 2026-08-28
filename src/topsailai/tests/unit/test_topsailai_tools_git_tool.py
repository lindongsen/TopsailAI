"""
Test for topsailai/tools/git_tool.py

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-07-30
"""

import os
import subprocess
import pytest
from unittest.mock import patch, MagicMock

from topsailai.tools import git_tool


class TestToolFlag:
    """Test module-level tool flag."""

    def test_flag_tool_enabled_is_false_by_default(self):
        assert git_tool.FLAG_TOOL_ENABLED is False


class TestSplitCommand:
    """Test _split_command helper."""

    def test_split_string_command(self):
        result = git_tool._split_command("git log --oneline -5")
        assert result == ["git", "log", "--oneline", "-5"]

    def test_split_list_command(self):
        result = git_tool._split_command(["git", "status", "--short"])
        assert result == ["git", "status", "--short"]

    def test_split_json_string_command(self):
        result = git_tool._split_command('["git", "branch", "-a"]')
        assert result == ["git", "branch", "-a"]


class TestValidateGitCommand:
    """Test _validate_git_command helper."""

    def test_allowed_log(self):
        valid, error = git_tool._validate_git_command(["git", "log", "--oneline"])
        assert valid is True
        assert error == ""

    def test_allowed_status(self):
        valid, error = git_tool._validate_git_command(["git", "status"])
        assert valid is True
        assert error == ""

    def test_allowed_stash_list(self):
        valid, error = git_tool._validate_git_command(["git", "stash", "list"])
        assert valid is True
        assert error == ""

    def test_rejected_commit(self):
        valid, error = git_tool._validate_git_command(["git", "commit", "-m", "x"])
        assert valid is False
        assert "commit" in error
        assert "read-only" in error

    def test_rejected_push(self):
        valid, error = git_tool._validate_git_command(["git", "push"])
        assert valid is False
        assert "push" in error

    def test_rejected_reset(self):
        valid, error = git_tool._validate_git_command(["git", "reset", "--hard"])
        assert valid is False
        assert "reset" in error

    def test_rejected_checkout(self):
        valid, error = git_tool._validate_git_command(["git", "checkout", "main"])
        assert valid is False
        assert "checkout" in error

    def test_rejected_stash_pop(self):
        valid, error = git_tool._validate_git_command(["git", "stash", "pop"])
        assert valid is False
        assert "stash" in error

    def test_rejected_branch_delete(self):
        valid, error = git_tool._validate_git_command(["git", "branch", "-d", "feature"])
        assert valid is False
        assert "read-only" in error

    def test_rejected_tag_delete(self):
        valid, error = git_tool._validate_git_command(["git", "tag", "-d", "v1"])
        assert valid is False
        assert "read-only" in error

    def test_rejected_non_git_executable(self):
        valid, error = git_tool._validate_git_command(["rm", "-rf", "/"])
        assert valid is False
        assert "only 'git' commands are allowed" in error

    def test_rejected_empty_command(self):
        valid, error = git_tool._validate_git_command([])
        assert valid is False
        assert "empty git command" in error

    def test_rejected_missing_subcommand(self):
        valid, error = git_tool._validate_git_command(["git"])
        assert valid is False
        assert "missing git subcommand" in error


class TestExecReadonly:
    """Test exec_readonly function."""

    def test_allowed_command_mocked(self):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=b"abc123 commit message\n",
                stderr=b"",
            )
            result = git_tool.exec_readonly("git log --oneline -1")
            assert result == (0, "abc123 commit message", "")
            mock_run.assert_called_once()
            call_args = mock_run.call_args
            assert call_args[0][0] == ["git", "log", "--oneline", "-1"]
            assert call_args[1]["cwd"] is not None
            assert call_args[1]["shell"] is False
            assert call_args[1]["timeout"] == 30

    def test_rejected_command_returns_error(self):
        result = git_tool.exec_readonly("git reset --hard HEAD")
        assert isinstance(result, str)
        assert "reset" in result

    def test_non_zero_exit_code(self):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=128,
                stdout=b"",
                stderr=b"fatal: not a git repository\n",
            )
            result = git_tool.exec_readonly("git status")
            assert result == (128, "", "fatal: not a git repository")

    def test_timeout_handling(self):
        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(
                cmd=["git", "log"],
                timeout=5,
            )
            result = git_tool.exec_readonly("git log", timeout=5)
            assert isinstance(result, str)
            assert "timed out" in result
            assert "5 seconds" in result

    @pytest.mark.parametrize(
        ("value", "expected"),
        [(10, 10), (10.9, 10), ("30", 30), (" 15 ", 15), ("1e2", 100), (0, 0), (-1, -1)],
    )
    def test_timeout_accepts_finite_numeric_values(self, value, expected):
        """Finite timeout values preserve integer and boundary semantics."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=b"", stderr=b"")
            result = git_tool.exec_readonly("git status", timeout=value)

        assert result == (0, "", "")
        assert mock_run.call_args.kwargs["timeout"] == expected

    @pytest.mark.parametrize(
        "value",
        ["NaN", "+inf", "-inf", "1e10000", "", None, "abc", object()],
    )
    def test_timeout_rejects_invalid_values(self, value):
        """Invalid timeout values return invalid_request without execution."""
        with patch("subprocess.run") as mock_run:
            result = git_tool.exec_readonly("git status", timeout=value)

        assert result["status"] == "invalid_request"
        assert "timeout" in result["reason"]
        assert result["status"] != "unavailable"
        mock_run.assert_not_called()

    def test_custom_cwd(self):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=b"",
                stderr=b"",
            )
            result = git_tool.exec_readonly("git status", cwd="/tmp")
            assert result == (0, "", "")
            assert mock_run.call_args[1]["cwd"] == "/tmp"

    def test_cwd_defaults_to_project_workspace(self):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=b"",
                stderr=b"",
            )
            with patch.object(
                git_tool,
                '_get_project_workspace',
                return_value="/workspace",
            ):
                result = git_tool.exec_readonly("git status")
                assert result == (0, "", "")
                assert mock_run.call_args[1]["cwd"] == "/workspace"

    def test_cwd_defaults_to_current_directory(self):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=b"",
                stderr=b"",
            )
            with patch.object(
                git_tool,
                '_get_project_workspace',
                return_value=None,
            ):
                result = git_tool.exec_readonly("git status")
                assert result == (0, "", "")
                assert mock_run.call_args[1]["cwd"] == os.getcwd()

    def test_output_truncation(self):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=b"x" * 40000,
                stderr=b"",
            )
            with patch('topsailai.tools.git_tool.ctx_safe.truncate_message') as mock_truncate:
                mock_truncate.side_effect = lambda x: x[:100]
                result = git_tool.exec_readonly("git log")
                assert result[0] == 0
                assert len(result[1]) == 100


class TestToolsConstant:
    """Test TOOLS constant."""

    def test_tools_contains_exec_readonly(self):
        assert "exec_readonly" in git_tool.TOOLS
        assert callable(git_tool.TOOLS["exec_readonly"])


class TestPrompt:
    """Test module-level PROMPT."""

    def test_prompt_declares_read_only(self):
        assert "read-only" in git_tool.PROMPT
        assert "exec_readonly" in git_tool.PROMPT
