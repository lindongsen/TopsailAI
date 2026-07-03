"""Global mutable state for the TopsailAI CLI.

This module holds the small amount of runtime state that was originally
kept at module level in ``topsailai.py``.  It is intentionally kept in one
place to make dependencies and lifecycle obvious.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

if TYPE_CHECKING:
    import subprocess

# Runtime control flag used by signal handlers and the main loop.
running = True

# Subprocesses spawned by the CLI that must be cleaned up on exit.
_child_processes: Set["subprocess.Popen"] = set()

# YAML command support
# Current interactive scope: "workspace" or "session".
current_scope = "workspace"

# Active session identifier when current_scope == "session".
current_session_id: Optional[str] = None

# YAML-loaded command instructions from topsailai.yaml.
yaml_commands: List[Dict[str, Any]] = []

# Command history manager instance.
history_manager: Optional["HistoryManager"] = None  # type: ignore[name-defined]
