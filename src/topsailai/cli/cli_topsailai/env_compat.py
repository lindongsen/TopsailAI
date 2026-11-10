"""Resolve CLI environment variables with their legacy names as a fallback.

Author: DawsonLin

CLI-only variables moved under the ``TOPSAILAI_CLI_`` prefix. An operator who
still exports a previous name must keep working, so every read consults the
prefixed name first and the legacy name second. The prefixed name always wins,
which lets a caller migrate one variable at a time without losing the old
setting.

An empty value is treated as a configured value, not as an absent one, because
at least one variable assigns a meaning to the empty string. Only an absent
variable falls back to its legacy name.
"""

from __future__ import annotations

import os
import sys
from typing import Mapping, Optional

#: Legacy name for every prefixed CLI variable.
LEGACY_NAMES = {
    "TOPSAILAI_CLI_HISTORY_MAX_ENTRIES": "TOPSAILAI_HISTORY_MAX_ENTRIES",
    "TOPSAILAI_CLI_HISTORY_MAX_SIZE_MB": "TOPSAILAI_HISTORY_MAX_SIZE_MB",
    "TOPSAILAI_CLI_HISTORY_MAX_BACKUPS": "TOPSAILAI_HISTORY_MAX_BACKUPS",
    "TOPSAILAI_CLI_DEBUG_INPUT": "TOPSAILAI_DEBUG_INPUT",
    "TOPSAILAI_CLI_TMP_CLEANUP_MAX_AGE_DAYS": "TOPSAILAI_TMP_CLEANUP_MAX_AGE_DAYS",
    "TOPSAILAI_CLI_SESSION_DRIVER_PYTHON": "TOPSAILAI_SESSION_DRIVER_PYTHON",
    "TOPSAILAI_CLI_SESSION_DRIVER_ENTRY": "TOPSAILAI_SESSION_DRIVER_ENTRY",
    "TOPSAILAI_CLI_SCAN_MAX_TOKENS": "TOPSAILAI_SCAN_MAX_TOKENS",
    "TOPSAILAI_CLI_SCAN_EXCLUDE": "TOPSAILAI_SCAN_EXCLUDE",
    "TOPSAILAI_CLI_SCAN_EXCLUDE_DIRS": "TOPSAILAI_SCAN_EXCLUDE_DIRS",
    "TOPSAILAI_CLI_SCAN_EXCLUDE_FILES": "TOPSAILAI_SCAN_EXCLUDE_FILES",
    "TOPSAILAI_CLI_SCAN_INCLUDE_FILES": "TOPSAILAI_SCAN_INCLUDE_FILES",
}

#: Legacy names already reported, so a repeated read warns only once.
_WARNED = set()


def legacy_name(name: str) -> Optional[str]:
    """Return the legacy name for a prefixed CLI variable, if it has one."""
    return LEGACY_NAMES.get(name)


def get_env(
    name: str,
    *,
    environ: Optional[Mapping[str, str]] = None,
    default: Optional[str] = None,
    warn: bool = True,
) -> Optional[str]:
    """Return the value of *name*, falling back to its legacy name.

    Args:
        name: Prefixed CLI variable name.
        environ: Mapping to read from. Defaults to ``os.environ``.
        default: Value returned when neither name is present.
        warn: Emit one deprecation notice per legacy name when it is used.

    Returns:
        The configured value, or *default* when neither name is present.
    """
    source = os.environ if environ is None else environ
    value = source.get(name)
    if value is not None:
        return value
    legacy = LEGACY_NAMES.get(name)
    if legacy is None:
        return default
    value = source.get(legacy)
    if value is None:
        return default
    if warn and legacy not in _WARNED:
        _WARNED.add(legacy)
        print(
            f"[WARN] {legacy} is deprecated; use {name} instead.",
            file=sys.stderr,
        )
    return value


def has_env(name: str, *, environ: Optional[Mapping[str, str]] = None) -> bool:
    """Return True when *name* or its legacy name is present."""
    source = os.environ if environ is None else environ
    if name in source:
        return True
    legacy = LEGACY_NAMES.get(name)
    return legacy is not None and legacy in source
