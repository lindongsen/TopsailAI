'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-07-30
  Purpose: Read-only git command execution tool.
'''

import os
import shlex
import subprocess

from topsailai.context import ctx_safe
from topsailai.utils import text_tool
from topsailai.utils.env_tool import EnvReaderInstance
from topsailai.tools.tool_utils.parameter import resolve_finite_int


# Disabled by default. Enable explicitly when read-only git tooling is needed.
FLAG_TOOL_ENABLED = False

# Git subcommands that are read-only and safe to execute.
ALLOWED_SUBCOMMANDS = frozenset({
    "log", "status", "diff", "show", "branch", "tag", "remote",
    "config", "rev-parse", "ls-files", "blame", "stash", "describe",
    "for-each-ref", "reflog", "ls-tree", "cat-file", "symbolic-ref",
    "name-rev", "merge-base", "rev-list", "show-ref", "verify-tag",
    "verify-commit", "archive", "shortlog", "count-objects",
})

# Subcommands that mutate repository state and must be rejected.
MUTATIVE_SUBCOMMANDS = frozenset({
    "add", "commit", "push", "pull", "fetch", "merge", "rebase",
    "reset", "checkout", "cherry-pick", "revert", "apply", "am",
    "init", "clone", "rm", "mv", "bisect", "gc", "clean", "prune",
    "submodule", "worktree", "notes", "update-index", "update-ref",
})

# Mutative options/flags that must be rejected.
MUTATIVE_OPTIONS = frozenset({
    "-d", "-D", "--delete", "--force", "-f", "--move", "-m",
    "--rename", "--set-upstream", "-u", "--unset", "--unset-all",
    "--replace-all", "--add", "--remove-section", "--rename-section",
    "--edit", "-e", "--patch", "-p", "--interactive", "--hard",
    "--soft", "--mixed", "--keep", "--merge", "--abort", "--continue",
    "--skip", "--quit", "--pop", "--drop", "--clear", "--create-reflog",
})


def _get_project_workspace() -> str | None:
    """Return the configured project workspace, or None if not set."""
    return EnvReaderInstance.project_folder


def _split_command(cmd: str | list) -> list[str]:
    """Normalize a git command into a list of tokens.

    Args:
        cmd: A command string or a pre-split list of arguments.

    Returns:
        list[str]: Token list ready for subprocess execution.
    """
    if isinstance(cmd, list):
        return [str(token) for token in cmd]

    cmd = cmd.strip()
    if cmd.startswith("[") and cmd.endswith("]"):
        from topsailai.utils.json_tool import safe_json_load
        parsed = safe_json_load(cmd)
        if isinstance(parsed, list):
            return [str(token) for token in parsed]

    return shlex.split(cmd)


def _validate_git_command(tokens: list[str]) -> tuple[bool, str]:
    """Validate that the token list represents a read-only git command.

    Args:
        tokens: Tokenized command list.

    Returns:
        tuple[bool, str]: (is_valid, error_message)
    """
    if not tokens:
        return False, "empty git command"

    executable = tokens[0].lower()
    if executable != "git":
        return False, f"only 'git' commands are allowed, got: {tokens[0]}"

    if len(tokens) < 2:
        return False, "missing git subcommand"

    subcommand = tokens[1].lower()

    if subcommand in MUTATIVE_SUBCOMMANDS:
        return False, (
            f"git subcommand '{subcommand}' is not allowed: "
            "only read-only git commands are permitted"
        )

    if subcommand not in ALLOWED_SUBCOMMANDS:
        return False, (
            f"git subcommand '{subcommand}' is not recognized as read-only: "
            "only read-only git commands are permitted"
        )

    for token in tokens[2:]:
        if token.startswith("-") and token.lower() in MUTATIVE_OPTIONS:
            return False, (
                f"git option '{token}' is not allowed: "
                "only read-only git commands are permitted"
            )

    # Special-case: "git stash list" is read-only, but other stash
    # subcommands mutate state.
    if subcommand == "stash":
        if len(tokens) < 3 or tokens[2].lower() != "list":
            return False, (
                "only 'git stash list' is allowed: "
                "other stash subcommands mutate repository state"
            )

    # Special-case: "git branch" without deletion flags is read-only,
    # but "git branch -d/-D/-m" etc. mutate state.
    if subcommand == "branch":
        for token in tokens[2:]:
            if token in ("-d", "-D", "-m", "-M", "--delete", "--move"):
                return False, (
                    "branch modification options are not allowed: "
                    "only read-only git commands are permitted"
                )

    # Special-case: "git tag -d" is mutative.
    if subcommand == "tag":
        for token in tokens[2:]:
            if token in ("-d", "--delete"):
                return False, (
                    "tag deletion is not allowed: "
                    "only read-only git commands are permitted"
                )

    return True, ""


def _format_return(code: int, stdout: str, stderr: str) -> tuple | str:
    """Truncate outputs and return a structured result.

    Args:
        code: Process exit code.
        stdout: Standard output text.
        stderr: Standard error text.

    Returns:
        tuple or str: (code, stdout, stderr) or an error string.
    """
    stdout = text_tool.safe_decode(stdout).strip()
    stderr = text_tool.safe_decode(stderr).strip()
    stdout = ctx_safe.truncate_message(stdout).strip()
    stderr = ctx_safe.truncate_message(stderr).strip()
    return (code, stdout, stderr)


def exec_readonly(
        cmd: str | list,
        timeout: int = 30,
        cwd: str | None = None,
    ):
    """Execute a read-only git command safely.

    Args:
        cmd (str|list): Git command to execute. Examples:
            "git log --oneline -5"
            ["git", "status", "--short"]
        timeout (int, optional): Maximum execution time in seconds.
            Defaults to 30.
        cwd (str, optional): Working directory for the command.
            Defaults to TOPSAILAI_PROJECT_WORKSPACE or the current directory.

    Returns:
        tuple: (return_code, stdout, stderr)
        str: Error message if the command is rejected or execution fails.
    """
    try:
        tokens = _split_command(cmd)
    except Exception as e:
        return f"failed to parse git command: {e}"

    valid, error = _validate_git_command(tokens)
    if not valid:
        return error

    if cwd is None:
        cwd = _get_project_workspace() or os.getcwd()

    timeout, error = resolve_finite_int(timeout, "timeout")
    if error:
        return error

    try:
        result = subprocess.run(
            tokens,
            cwd=cwd,
            shell=False,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return (
            f"git command timed out after {timeout} seconds: "
            f"{' '.join(tokens)}"
        )
    except Exception as e:
        return f"failed to execute git command: {e}"

    return _format_return(
        result.returncode,
        text_tool.safe_decode(result.stdout),
        text_tool.safe_decode(result.stderr),
    )


# name: func
TOOLS = dict(
    exec_readonly=exec_readonly,
)

PROMPT = """
# About git_tool

`git_tool-exec_readonly` executes read-only git commands. It rejects any command
that could modify repository state (such as commit, push, pull, merge, rebase,
reset, checkout, cherry-pick, revert, apply, am, init, clone, rm, mv, branch
deletion, tag deletion, stash pop/drop, etc.).

Allowed examples:
- git log --oneline -10
- git status
- git diff HEAD~1
- git show <commit>
- git branch -a
- git tag -l
- git remote -v
- git config --list
- git rev-parse HEAD
- git ls-files
- git blame <file>
- git stash list
"""
