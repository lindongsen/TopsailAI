"""Color helpers for terminal output.

Provides ANSI color constants and reusable print helpers so that
colored output is consistent across the CLI.
"""

from __future__ import annotations

import builtins
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Optional


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


def cprint(
    text: str,
    color: str = Colors.WHITE,
    bold: bool = False,
    dim: bool = False,
    bg: str = "",
    end: str = "\n",
    file: Optional[object] = None,
) -> None:
    """Print *text* with the given color/style.

    Args:
        text: The text to print.
        color: An ANSI foreground color attribute from :class:`Colors`.
        bold: Whether to apply bold style.
        dim: Whether to apply dim style.
        bg: An ANSI background color attribute from :class:`Colors`.
        end: String appended after the last value.
        file: Output stream passed to ``print``.
    """
    kwargs = {}
    if end != "\n":
        kwargs["end"] = end
    if file is not None:
        kwargs["file"] = file
    builtins.print(colored(text, color, bold=bold, dim=dim, bg=bg), **kwargs)


def print_colored(text: str, color: str = Colors.WHITE, end: str = "\n") -> None:
    """Print *text* with the given color.

    This is a convenience alias for callers that only need a color.
    """
    cprint(text, color=color, end=end)


def print_info(text: str, end: str = "\n") -> None:
    """Print an info message in cyan."""
    cprint(text, color=Colors.CYAN, end=end)


def print_success(text: str, end: str = "\n") -> None:
    """Print a success message in green."""
    cprint(text, color=Colors.GREEN, end=end)


def print_warning(text: str, end: str = "\n") -> None:
    """Print a warning message in yellow."""
    cprint(text, color=Colors.YELLOW, end=end)


def print_error(text: str, end: str = "\n") -> None:
    """Print an error message in red."""
    cprint(text, color=Colors.RED, end=end)


def print_dim(text: str, end: str = "\n") -> None:
    """Print dimmed text."""
    cprint(text, color=Colors.WHITE, dim=True, end=end)
