"""ANSI color/style helpers for terminal output.

This is a low-level, dependency-free module that provides ANSI escape
sequence constants and a reusable ``colored()`` function. Both the CLI
(``cli.cli_topsailai.colors``) and general utilities (e.g.
``utils.print_tool``) import from here so that colored output stays
consistent across the project without duplicating logic.
"""

from __future__ import annotations


class Colors:
    """ANSI color/style escape sequences."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    GRAY = "\033[90m"
    BG_BLUE = "\033[44m"
    BG_GREEN = "\033[42m"


def colored(
    text: str,
    color: str = "",
    bold: bool = False,
    dim: bool = False,
    bg: str = "",
) -> str:
    """Wrap *text* with ANSI color/style codes.

    Args:
        text: The text to colorize.
        color: An ANSI foreground color attribute from :class:`Colors`.
        bold: Whether to apply bold style.
        dim: Whether to apply dim style.
        bg: An ANSI background color attribute from :class:`Colors`.

    Returns:
        The colorized string with reset appended.
    """
    style = ""
    if bold:
        style += Colors.BOLD
    if dim:
        style += Colors.DIM
    if bg:
        style += bg
    if color:
        style += color
    return f"{style}{text}{Colors.RESET}"
