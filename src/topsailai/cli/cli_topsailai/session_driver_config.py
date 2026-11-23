"""Resolve validated CLI driver defaults and optional installation overrides.

Author: DawsonLin
"""

from pathlib import Path
import os
import sys
from typing import Mapping

from cli_topsailai.env_compat import get_env
from cli_topsailai.session_driver_launcher import DriverAuthority

ENTRY_ENV = "TOPSAILAI_CLI_SESSION_DRIVER_ENTRY"
PYTHON_ENV = "TOPSAILAI_CLI_SESSION_DRIVER_PYTHON"


def _resolve_override(environment: Mapping[str, str], name: str) -> str | None:
    """Return a driver override, accepting its legacy name as a fallback.

    The prefixed name wins so a caller can migrate one variable at a time. The
    legacy name is still honoured because an operator may export it from an
    older installation.
    """
    value = get_env(name, environ=environment)
    return value


def _is_python_interpreter(path: str | None) -> bool:
    """Return whether *path* names a Python interpreter candidate."""
    return bool(path) and Path(path).name.lower().startswith("python")


def _runtime_is_compiled(executable: str | None, base_executable: str | None) -> bool:
    """Return whether the runtime is a compiled binary rather than an interpreter.

    A compiled installation runs the CLI as a native executable, so
    ``sys.executable`` names that binary instead of an interpreter. An empty
    runtime is not compiled evidence: it only means no candidate was supplied.
    """
    current = sys.executable if executable is None else executable
    base = getattr(sys, "_base_executable", "") if base_executable is None else base_executable
    supplied = [value for value in (current, base) if value]
    return bool(supplied) and not any(_is_python_interpreter(value) for value in supplied)


def _missing_entry_error(entry_override: str | None, executable: str | None,
                         base_executable: str | None) -> ValueError:
    """Build the entry error that matches the installation kind.

    A compiled installation ships ``session_agent_driver`` without the ``.py``
    suffix, so telling an operator to install the source file sends them after a
    path the package never contains.
    """
    if entry_override is not None:
        return ValueError(f"{ENTRY_ENV}: entry must be an existing absolute file; "
                          "set this variable to an installed driver entry before restarting the CLI")
    if _runtime_is_compiled(executable, base_executable):
        return ValueError(f"{ENTRY_ENV}: compiled installation is missing the driver entry; "
                          "reinstall the package to restore scripts/session_agent_driver/session_agent_driver, "
                          "or set this variable to an installed driver entry")
    return ValueError(f"{ENTRY_ENV}: entry must be an existing absolute file; "
                      "install scripts/session_agent_driver/session_agent_driver.py "
                      "or set this variable before restarting the CLI")


def _interpreter_error(executable: str | None, base_executable: str | None) -> ValueError:
    """Build the interpreter error that matches the installation kind."""
    if _runtime_is_compiled(executable, base_executable):
        return ValueError(f"{PYTHON_ENV}: a compiled installation has no Python interpreter; "
                          "install the compiled driver entry instead of a source entry, "
                          "or set this variable to a compatible Python interpreter")
    return ValueError(f"{PYTHON_ENV}: interpreter must be an existing executable absolute file "
                      "whose name starts with python; set a compatible Python interpreter "
                      "before restarting the CLI")


def resolve_driver_authority(environment: Mapping[str, str], *,
                             package_dir: Path | None = None,
                             executable: str | None = None,
                             base_executable: str | None = None) -> DriverAuthority:
    """Resolve only known layout/runtime candidates; invalid overrides fail closed."""
    package = Path(__file__).resolve().parent if package_dir is None else package_dir
    directory = package.parent.parent / "scripts" / "session_agent_driver"
    compiled = directory / "session_agent_driver"
    entry_override = _resolve_override(environment, ENTRY_ENV)
    entry = (Path(entry_override) if entry_override is not None else
             compiled if compiled.exists() else directory / "session_agent_driver.py")
    if not entry.is_absolute() or not entry.is_file():
        raise _missing_entry_error(entry_override, executable, base_executable)
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
    python_override = _resolve_override(environment, PYTHON_ENV)
    if python_override is not None:
        candidates = [python_override]
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
    raise _interpreter_error(executable, base_executable)
