"""Read-only git instruction handlers for the workspace plugin system."""

import os

from topsailai.utils.cmd_tool import exec_cmd


# Subcommands that are considered read-only. Anything outside this list is rejected.
_ALLOWED_SUBCOMMANDS = {
    "status",
    "show",
    "log",
    "diff",
    "branch",
    "tag",
    "remote",
    "rev-parse",
    "ls-files",
    "config",
}

# Flags that make `git config` read-only.
_READ_ONLY_CONFIG_FLAGS = {
    "--get",
    "--get-all",
    "--get-regexp",
    "--list",
}

# Flags that turn `git branch` or `git tag` into write/destructive operations.
_WRITE_BRANCH_FLAGS = {
    "-d", "-D", "--delete",
    "-m", "-M", "--move",
    "-c", "-C", "--copy",
}

_WRITE_TAG_FLAGS = {
    "-d", "-D", "--delete",
    "-f", "--force",
    "-a", "-s", "-u",
    "-m", "--message",
    "-F", "--file",
}


def _resolve_working_directory() -> str:
    """Resolve the working directory for git commands.

    Priority:
      1. TOPSAILAI_PROJECT_FOLDER (or alias TOPSAILAI_PROJECT_WORKSPACE)
      2. TOPSAILAI_PWD
      3. Current working directory

    Returns:
        str: Absolute path to the directory where git should run.
    """
    project_folder = os.getenv("TOPSAILAI_PROJECT_FOLDER") or os.getenv("TOPSAILAI_PROJECT_WORKSPACE")
    if project_folder:
        return os.path.abspath(project_folder)

    pwd = os.getenv("TOPSAILAI_PWD")
    if pwd:
        return os.path.abspath(pwd)

    return os.path.abspath(os.getcwd())


def _validate_subcommand(args: list[str]) -> None:
    """Validate that the requested git subcommand and its flags are read-only.

    Args:
        args: Tokenized git command arguments (excluding "git" itself).

    Raises:
        ValueError: If the subcommand is missing, unsupported, or appears to be
                    write/destructive.
    """
    if not args:
        raise ValueError("No git subcommand provided. Usage: /git <subcommand> [args...]")

    subcommand = args[0]
    if subcommand not in _ALLOWED_SUBCOMMANDS:
        raise ValueError(
            f"Unsupported git subcommand: {subcommand!r}. "
            f"Allowed read-only subcommands: {', '.join(sorted(_ALLOWED_SUBCOMMANDS))}."
        )

    flags = set(args[1:])

    if subcommand == "branch" and flags & _WRITE_BRANCH_FLAGS:
        raise ValueError("Write/destructive branch operations are not allowed.")

    if subcommand == "tag" and flags & _WRITE_TAG_FLAGS:
        raise ValueError("Write/destructive tag operations are not allowed.")

    if subcommand == "config":
        if len(args) < 2 or args[1] not in _READ_ONLY_CONFIG_FLAGS:
            raise ValueError(
                "Only read-only git config queries are allowed "
                "(--get, --get-all, --get-regexp, --list)."
            )


def _run_git(args: list[str], cwd: str) -> str:
    """Execute a git command and return its output.

    Args:
        args: Tokenized git command arguments (excluding "git" itself).
        cwd: Working directory for the command.

    Returns:
        str: Combined stdout/stderr output, or an error message if execution fails.
    """
    if not os.path.isdir(cwd):
        return f"Error: working directory does not exist: {cwd}"

    cmd = ["git"] + args
    try:
        return_code, stdout, stderr = exec_cmd(cmd, timeout=60, cwd=cwd)
    except Exception as exc:
        return f"Error: failed to execute git: {exc}"

    output = stdout or ""
    if stderr:
        if output:
            output += "\n"
        output += stderr

    if return_code != 0 and not output:
        output = f"git exited with code {return_code}"

    return output


def git(*args: str) -> str:
    """Run a read-only git command in the resolved working directory.

    Usage:
        /git <subcommand> [args...]

    Examples:
        /git status
        /git log --oneline -n 5
        /git diff HEAD~1..HEAD
        /git show HEAD --stat

    Args:
        *args: Git subcommand and optional arguments.

    Returns:
        str: Command output.
    """
    args = list(args)
    _validate_subcommand(args)
    cwd = _resolve_working_directory()
    return _run_git(args, cwd)


def git_status(*args: str) -> str:
    """Run git status."""
    return git("status", *args)


def git_log(*args: str) -> str:
    """Run git log."""
    return git("log", *args)


def git_diff(*args: str) -> str:
    """Run git diff."""
    return git("diff", *args)


def git_show(*args: str) -> str:
    """Run git show."""
    return git("show", *args)


def git_branch(*args: str) -> str:
    """Run git branch."""
    return git("branch", *args)


def git_tag(*args: str) -> str:
    """Run git tag."""
    return git("tag", *args)


def git_remote(*args: str) -> str:
    """Run git remote."""
    return git("remote", *args)


INSTRUCTIONS = dict(
    git=git,
    git_status=git_status,
    git_log=git_log,
    git_diff=git_diff,
    git_show=git_show,
    git_branch=git_branch,
    git_tag=git_tag,
    git_remote=git_remote,
)
