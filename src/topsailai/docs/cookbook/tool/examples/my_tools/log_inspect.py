"""Bounded log inspection exposed as log_inspect-scan and log_inspect-tail tools."""

# List form: the action name is the function name, so this module registers
# log_inspect-scan and log_inspect-tail.
#
# Scenario: the agent must explain why a run failed. Reading a whole log into the
# context is expensive and usually truncated, so both tools return a bounded
# number of matching lines and report how many lines they skipped.

import json
import os
from pathlib import Path

MAX_LINES = 100


def _resolve(path: str) -> Path:
    """Resolve a log path, defaulting to the agent log folder.

    Args:
        path: Absolute file path, or a bare file name inside the agent log folder.

    Returns:
        The resolved file path.
    """
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate
    home = os.getenv("TOPSAILAI_HOME", "")
    if not home:
        raise FileNotFoundError("relative path needs TOPSAILAI_HOME")
    return Path(home) / "log" / candidate


def _parse_patterns(patterns: str) -> list[str]:
    """Parse the patterns argument, which may arrive as a JSON list or a plain string.

    Args:
        patterns: A JSON array such as ["ERROR","Traceback"], or one plain substring.

    Returns:
        The list of substrings to match.
    """
    text = (patterns or "").strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return [text]
        if isinstance(parsed, list):
            return [str(item) for item in parsed if str(item)]
        return [text]
    return [item.strip() for item in text.split(",") if item.strip()]


def scan(path: str = "", patterns: str = "", limit: str = "40") -> str:
    """Return the last matching lines of one log file.

    Args:
        path: Absolute log path, or a file name inside the agent log folder.
        patterns: JSON array or comma-separated substrings; a line matches any of them.
        limit: Maximum matching lines to return, as a decimal string. Capped at 100.

    Returns:
        A summary line, then the matching lines in file order, or an error message.
    """
    if not path:
        return "error: path is required"

    try:
        max_lines = int(limit)
    except (TypeError, ValueError):
        return "error: limit must be an integer"
    if max_lines <= 0:
        return "error: limit must be positive"
    max_lines = min(max_lines, MAX_LINES)

    needles = _parse_patterns(patterns)
    try:
        target = _resolve(path)
        with target.open(encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError as exc:
        return f"error: {exc}"

    matched = [
        line.rstrip("\n")
        for line in lines
        if not needles or any(needle in line for needle in needles)
    ]
    if not matched:
        return f"no match in {target.name} (lines={len(lines)}, patterns={needles})"

    shown = matched[-max_lines:]
    header = (
        f"{target.name}: matched={len(matched)} shown={len(shown)} "
        f"total_lines={len(lines)} patterns={needles}"
    )
    return "\n".join([header, *shown])


def tail(path: str = "", lines_count: str = "20") -> str:
    """Return the last lines of one log file without any filtering.

    Args:
        path: Absolute log path, or a file name inside the agent log folder.
        lines_count: Number of trailing lines to return, as a decimal string. Capped at 100.

    Returns:
        The trailing lines, or an error message.
    """
    if not path:
        return "error: path is required"

    try:
        count = int(lines_count)
    except (TypeError, ValueError):
        return "error: lines_count must be an integer"
    if count <= 0:
        return "error: lines_count must be positive"
    count = min(count, MAX_LINES)

    try:
        target = _resolve(path)
        with target.open(encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError as exc:
        return f"error: {exc}"

    if not lines:
        return f"{target.name}: empty"
    return "\n".join(line.rstrip("\n") for line in lines[-count:])


TOOLS = [scan, tail]
