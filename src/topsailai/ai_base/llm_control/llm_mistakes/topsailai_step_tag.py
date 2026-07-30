'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-07-30
Purpose: Fix LLM responses that wrap ``topsailai.{step_name}`` tags in angle brackets.

The LLM sometimes emits XML-style tags such as ``<topsailai.thought>`` and
``</topsailai.thought>`` instead of the canonical plain-text markers.  This
fixer normalizes the opening tag to ``topsailai.{step_name}`` and removes the
closing tag so the response parser can process the content correctly.
'''

import re


_PREFIX = r"topsailai\."
_STEP_NAME = r"[a-zA-Z0-9_\-]+"

# Opening tag: <topsailai.step_name> (with optional whitespace inside brackets).
_OPENING_TAG_RE = re.compile(
    r"<\s*" + _PREFIX + _STEP_NAME + r"\s*>",
    re.MULTILINE,
)

# Closing tag: </topsailai.step_name>.  Prefer removing the whole line when
# the tag stands alone, otherwise strip the tag and any immediately adjacent
# whitespace.  The four alternatives cover: newline-both, newline-before,
# newline-after, and inline.
_CLOSING_TAG_RE = re.compile(
    r"(?:\n\s*</\s*" + _PREFIX + _STEP_NAME + r"\s*>\s*\n"
    r"|\n\s*</\s*" + _PREFIX + _STEP_NAME + r"\s*>\s*"
    r"|</\s*" + _PREFIX + _STEP_NAME + r"\s*>\s*\n"
    r"|</\s*" + _PREFIX + _STEP_NAME + r"\s*>\s*)",
    re.MULTILINE,
)


def _replace_opening_tag(match):
    """Replace an opening bracketed tag with the canonical ``topsailai.step_name``."""
    inner = match.group(0).lstrip("<").rstrip(">").strip()
    return inner


def _replace_closing_tag(match):
    """Remove a closing bracketed tag, preserving a single newline for line-only tags."""
    text = match.group(0)
    if text.startswith("\n") and text.endswith("\n"):
        return "\n"
    return ""


def fix_topsailai_step_tag(message, **kwargs):
    """Normalize bracketed ``topsailai.{step_name}`` tags in string responses.

    Args:
        message: The LLM response, expected to be a string for this fixer.

    Returns:
        The normalized string if any change was made, otherwise ``None``.
    """
    if not isinstance(message, str):
        return None

    changed = False

    new_message, count = _OPENING_TAG_RE.subn(_replace_opening_tag, message)
    if count:
        changed = True

    new_message, count = _CLOSING_TAG_RE.subn(_replace_closing_tag, new_message)
    if count:
        changed = True

    return new_message if changed else None


MISTAKES = dict(
    fix_topsailai_step_tag=fix_topsailai_step_tag,
)
