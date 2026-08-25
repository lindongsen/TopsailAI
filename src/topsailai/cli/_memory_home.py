"""Resolve TOPSAILAI_HOMEs to story-memory roots."""

from __future__ import annotations

import os

try:
    from . import _import_topsailai
except ImportError:
    import _import_topsailai

from topsailai.tools import story_memory_tool
from topsailai.workspace.folder_constants import FOLDER_MEMORY


def resolve_memory_home(value: str | None) -> str:
    """Resolve an optional TOPSAILAI_HOME to its memory root."""
    if value is None:
        return story_memory_tool.WORKSPACE or FOLDER_MEMORY

    expanded = os.path.expanduser(value)
    if os.path.isabs(expanded):
        root = os.path.abspath(expanded)
    else:
        original_pwd = os.getenv("TOPSAILAI_PWD") or os.getcwd()
        root = os.path.abspath(os.path.join(original_pwd, expanded))

    if os.path.isdir(os.path.join(root, "story")):
        return root
    return os.path.join(root, "memory")
