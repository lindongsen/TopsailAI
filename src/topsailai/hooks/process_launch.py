"""Deterministic launch preparation for framework-owned hook scripts."""

from __future__ import annotations


def build_script_environment(
    argv: tuple[str, ...],
    environment: dict[str, str],
    result_write: int,
    limit: int,
) -> dict[str, str] | None:
    """Insert the real result descriptor before enforcing the final launch budget."""
    if type(result_write) is not int or result_write < 3:
        return None
    child_environment = dict(environment)
    child_environment["TOPSAILAI_HOOK_RESULT_FD"] = str(result_write)
    if not argument_environment_within_limit(argv, child_environment, limit):
        return None
    return child_environment


def argument_environment_within_limit(
    argv: tuple[str, ...], environment: dict[str, str], limit: int
) -> bool:
    """Count actual UTF-8 argv and environment bytes including terminating NULs."""
    if type(limit) is not int or limit <= 0:
        return False
    try:
        size = sum(len(item.encode("utf-8")) + 1 for item in argv)
        size += sum(
            len(f"{name}={value}".encode("utf-8")) + 1
            for name, value in environment.items()
        )
    except (AttributeError, UnicodeEncodeError):
        return False
    return size <= limit
