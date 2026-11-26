"""Default environment values shared by the LLM chat entry points.

``llm_chat`` and ``llm_chats`` run a chat directly against a model, so the
framework's display output is not part of their contract. The core reader
``topsailai.utils.env_tool.is_print_enabled`` already treats an absent
``TOPSAILAI_PRINT_ENABLED`` as ``0``, but that default lives in the library and
is invisible to the entry point: a caller shell or a project settings file can
export the variable for another purpose and silently change what these two
commands print.

Pinning the default at the entry point makes the effective value deterministic
for these commands without touching the library contract that other callers
rely on. ``setdefault`` is deliberate: an explicitly configured value, including
an empty one, is preserved, and only an absent variable is filled in.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-26
Purpose: Default TOPSAILAI_PRINT_ENABLED to 0 for the LLM chat entry points
"""

from __future__ import annotations

import os
from typing import Mapping, MutableMapping, Optional

#: Environment variable that allows framework display output in noninteractive mode.
PRINT_ENABLED_ENV_KEY = "TOPSAILAI_PRINT_ENABLED"

#: Value used when the variable is not configured: display output stays off.
PRINT_ENABLED_DEFAULT = "0"


def apply_chat_env_defaults(
    environ: Optional[MutableMapping[str, str]] = None,
) -> None:
    """Fill in the chat entry-point environment defaults.

    Only absent variables are written, so a value the caller configured is
    never overwritten. An empty value counts as configured, because the core
    reader treats it as a present value rather than as an absent one.

    Args:
        environ: Mutable environment mapping to update. Defaults to
            ``os.environ``.
    """
    env: MutableMapping[str, str] = os.environ if environ is None else environ
    env.setdefault(PRINT_ENABLED_ENV_KEY, PRINT_ENABLED_DEFAULT)


def read_print_enabled(
    environ: Optional[Mapping[str, str]] = None,
) -> str:
    """Return the effective ``TOPSAILAI_PRINT_ENABLED`` value for a chat run.

    Args:
        environ: Environment mapping to read. Defaults to ``os.environ``.

    Returns:
        The configured value, or ``PRINT_ENABLED_DEFAULT`` when it is absent.
    """
    env = os.environ if environ is None else environ
    return env.get(PRINT_ENABLED_ENV_KEY, PRINT_ENABLED_DEFAULT)


__all__ = [
    "PRINT_ENABLED_DEFAULT",
    "PRINT_ENABLED_ENV_KEY",
    "apply_chat_env_defaults",
    "read_print_enabled",
]
