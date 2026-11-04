#!/usr/bin/env python3
"""Read-only release gate for one git repository.

Scenario: a release manager is about to publish a tag and asks the agent whether
the tree is safe to tag. The agent must not improvise git commands, because a
wrong `git clean` or `git checkout` destroys uncommitted work. This script is the
only thing the skill allows to run, and it only reads.
"""

import subprocess
import sys
from pathlib import Path

MAX_FILES = 20
GIT_TIMEOUT = 30


def _git(repo: str, *args: str) -> str:
    """Run one read-only git command and return its standard output.

    Args:
        repo: Absolute path of the repository working tree.
        args: The git subcommand and its arguments.

    Returns:
        The command standard output.

    Raises:
        RuntimeError: When git exits non-zero.
    """
    result = subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or f"git {args[0]} failed"
        raise RuntimeError(message)
    return result.stdout


def _lines(text: str) -> list[str]:
    """Split command output into non-empty stripped lines.

    Args:
        text: Raw command output.

    Returns:
        The non-empty lines.
    """
    return [line for line in text.splitlines() if line.strip()]


def _upstream(repo: str) -> str:
    """Return the configured upstream reference of the current branch.

    Args:
        repo: Absolute path of the repository working tree.

    Returns:
        The upstream reference such as `origin/main`, or an empty string when
        the branch has no upstream configured.
    """
    result = subprocess.run(
        ["git", "-C", repo, "rev-parse", "--abbrev-ref", "@{upstream}"],
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _report(repo: str, tag: str) -> tuple[list[str], list[str]]:
    """Collect the blocking and informational facts of one repository.

    Args:
        repo: Absolute path of the repository working tree.
        tag: The tag name the release manager intends to publish.

    Returns:
        A tuple of (blocking lines, informational lines).
    """
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()
    head = _git(repo, "rev-parse", "--short", "HEAD").strip()

    dirty = _lines(_git(repo, "status", "--porcelain", "--untracked-files=normal"))
    tracked_dirty = [line for line in dirty if not line.startswith("??")]
    untracked = [line for line in dirty if line.startswith("??")]

    existing_tag = _lines(_git(repo, "tag", "--list", tag))

    upstream = _upstream(repo)
    ahead = _lines(_git(repo, "log", "--oneline", f"{upstream}..HEAD")) if upstream else []

    blocking = []
    if tracked_dirty:
        blocking.append(f"tracked files modified: {len(tracked_dirty)}")
        blocking.extend(f"  {line}" for line in tracked_dirty[:MAX_FILES])
        if len(tracked_dirty) > MAX_FILES:
            blocking.append(f"  (+{len(tracked_dirty) - MAX_FILES} more)")
    if existing_tag:
        blocking.append(f"tag already exists: {tag}")
    if not upstream:
        blocking.append("branch has no upstream, so pushed state cannot be verified")
    elif ahead:
        blocking.append(f"commits not pushed: {len(ahead)}")
        blocking.extend(f"  {line}" for line in ahead[:MAX_FILES])

    info = [
        f"branch: {branch}",
        f"head: {head}",
        f"upstream: {upstream or '-'}",
        f"untracked files: {len(untracked)}",
    ]
    info.extend(f"  {line}" for line in untracked[:MAX_FILES])
    if len(untracked) > MAX_FILES:
        info.append(f"  (+{len(untracked) - MAX_FILES} more)")

    return blocking, info


def main(argv: list[str]) -> int:
    """Print the release gate report.

    Args:
        argv: Command-line arguments: <repo> <tag>.

    Returns:
        0 when the tree is ready, 1 when it is blocked, 2 on usage error.
    """
    if len(argv) != 2:
        print("usage: check_tree.py <repo> <tag>", file=sys.stderr)
        return 2

    repo, tag = argv
    if not Path(repo).is_dir():
        print(f"error: not a directory: {repo}", file=sys.stderr)
        return 2

    try:
        blocking, info = _report(repo, tag)
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"release gate for tag {tag}")
    for line in info:
        print(line)

    if blocking:
        print("verdict: BLOCKED")
        for line in blocking:
            print(line)
        return 1

    print("verdict: READY")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
