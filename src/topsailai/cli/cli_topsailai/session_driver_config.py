"""Resolve validated CLI driver defaults and optional installation overrides.

Author: DawsonLin
"""

from pathlib import Path
import os
import sys
from typing import Mapping

from cli_topsailai.session_driver_launcher import DriverAuthority

ENTRY_ENV = "TOPSAILAI_SESSION_DRIVER_ENTRY"
PYTHON_ENV = "TOPSAILAI_SESSION_DRIVER_PYTHON"


def resolve_driver_authority(environment: Mapping[str, str], *,
                             package_dir: Path | None = None,
                             executable: str | None = None,
                             base_executable: str | None = None) -> DriverAuthority:
    """Resolve only known layout/runtime candidates; invalid overrides fail closed."""
    package = Path(__file__).resolve().parent if package_dir is None else package_dir
    directory = package.parent.parent / "scripts" / "session_agent_driver"
    compiled = directory / "session_agent_driver"
    entry = (Path(environment[ENTRY_ENV]) if ENTRY_ENV in environment else
             compiled if compiled.exists() else directory / "session_agent_driver.py")
    if not entry.is_absolute() or not entry.is_file():
        raise ValueError(f"{ENTRY_ENV}: entry must be an existing absolute file; "
                         "install scripts/session_agent_driver/session_agent_driver.py "
                         "or set this variable before restarting the CLI")
    if not os.access(entry, os.R_OK):
        raise ValueError(f"{ENTRY_ENV}: entry must be readable; "
                         "correct permissions or set a readable absolute entry and restart the CLI")
    if entry.suffix != ".py":
        authority = DriverAuthority(entry, None)
        try:
            authority.validate()
        except ValueError as error:
            raise ValueError(f"{ENTRY_ENV}: compiled entry must be executable; "
                             "correct permissions or set a valid absolute entry and restart the CLI") from error
        return authority
    if PYTHON_ENV in environment:
        candidates = [environment[PYTHON_ENV]]
    else:
        candidates = [sys.executable if executable is None else executable,
                      getattr(sys, "_base_executable", "") if base_executable is None else base_executable]
    for candidate in candidates:
        authority = DriverAuthority(entry, Path(candidate or ""))
        try:
            authority.validate()
        except ValueError:
            continue
        return authority
    raise ValueError(f"{PYTHON_ENV}: interpreter must be an existing executable absolute file "
                     "whose name starts with python; set a compatible Python interpreter "
                     "before restarting the CLI")
