"""Managed standalone script launching. Author: DawsonLin."""

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
import logging
import math
import os
from pathlib import Path
import subprocess

from topsailai.utils.env_tool import resolve_python_interpreter

__all__ = ["start_script"]
logger = logging.getLogger(__name__)
# Probe only these explicit suffixes; multiple existing candidates are ambiguous.
_SCRIPT_EXTENSIONS = (".py", ".sh")


def _resolve_script(script_path: str | os.PathLike[str]) -> Path:
    """Resolve a regular executable target without relative root escapes."""
    if not os.fspath(script_path):
        raise ValueError("script_path must not be empty")
    path = Path(script_path)
    root = Path(__file__).resolve().parent
    target = (path if path.is_absolute() else root / path).resolve()
    if not path.is_absolute() and not target.is_relative_to(root):
        raise ValueError("Relative script path escapes the scripts folder")
    if not path.suffix and not target.exists():
        original = path if path.is_absolute() else root / path
        candidates = [original.with_suffix(suffix) for suffix in _SCRIPT_EXTENSIONS
                      if original.with_suffix(suffix).exists()]
        if len(candidates) > 1:
            raise ValueError(f"Ambiguous script candidates: {', '.join(map(str, candidates))}")
        if candidates:
            target = candidates[0].resolve()
            if not path.is_absolute() and not target.is_relative_to(root):
                raise ValueError("Relative script path escapes the scripts folder")
    if not target.exists():
        raise FileNotFoundError(f"Script does not exist: {target}")
    if target.is_dir():
        raise IsADirectoryError(f"Script is a directory: {target}")
    if not target.is_file():
        raise ValueError(f"Script must be a regular file: {target}")
    if not os.access(target, os.X_OK):
        raise PermissionError(f"Script is not executable: {target}")
    return target


def _command(target: Path, args: Sequence[str]) -> list[str]:
    """Choose Python dispatch only after the target passes executable checks."""
    if os.name == "nt" and target.suffix.lower() in {".bat", ".cmd"}:
        raise ValueError("Windows shell scripts are not supported")
    if target.suffix.lower() != ".py":
        return [str(target), *args]
    if not os.access(target, os.R_OK):
        raise PermissionError(f"Python script is not readable: {target}")
    interpreter = resolve_python_interpreter()
    if not Path(interpreter).is_file() or not os.access(interpreter, os.X_OK):
        raise PermissionError("Resolved Python interpreter is not executable")
    return [interpreter, str(target), *args]


def _reap(process: subprocess.Popen, timeout: float) -> None:
    """Stop and reap the exact child, preserving host interrupts during recovery."""
    try:
        try:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    except BaseException as primary:
        # Protect escalation as well as graceful shutdown with recovery ownership.
        recovery_error = None
        try:
            if process.poll() is None:
                process.kill()
        except BaseException as error:
            recovery_error = error
            logger.exception("Emergency script kill failed pid=%s", process.pid)
        try:
            # A failed kill must not suppress reaping or cause an unbounded wait.
            if recovery_error is None:
                process.wait()
            else:
                process.wait(timeout=timeout)
        except BaseException as error:
            if not isinstance(recovery_error, (KeyboardInterrupt, SystemExit)):
                recovery_error = error
            logger.exception("Emergency script wait failed pid=%s", process.pid)
        if recovery_error is not None:
            if isinstance(primary, (KeyboardInterrupt, SystemExit)):
                primary.add_note(f"Recovery failed: {type(recovery_error).__name__}")
                primary.script_cleanup_error = recovery_error
            else:
                raise recovery_error from primary
        raise


@contextmanager
def start_script(
    script_path: str | os.PathLike[str],
    args: Sequence[str] = (),
    *,
    cwd: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    shutdown_timeout: float = 5.0,
) -> Iterator[subprocess.Popen]:
    """Launch on context entry and terminate/reap the direct child on exit.

    Relative paths are rooted at this scripts package; absolute external paths
    are allowed. An absent extensionless target probes .py and .sh; multiple
    existing candidates raise ValueError. The original entry always wins.
    Python targets require executable and readable permissions.
    Arguments are literal strings, not shell text. Environment overrides merge
    into a copy of the parent environment; streams and the default cwd inherit.
    Keep the context open for the required child lifetime. This does not supervise
    grandchildren or guarantee cleanup after a parent crash or SIGKILL.
    """
    process = None
    primary = None
    try:
        if isinstance(args, (str, bytes)) or not isinstance(args, Sequence):
            raise TypeError("args must be a sequence of strings")
        arguments = list(args)
        if any(not isinstance(argument, str) for argument in arguments):
            raise TypeError("Every script argument must be a string")
        if isinstance(shutdown_timeout, bool) or not isinstance(shutdown_timeout, (int, float)):
            raise TypeError("shutdown_timeout must be a number")
        if not math.isfinite(shutdown_timeout) or shutdown_timeout <= 0:
            raise ValueError("shutdown_timeout must be positive and finite")
        target = _resolve_script(script_path)
        command = _command(target, arguments)
        child_env = None if env is None else {**os.environ, **env}
        child_cwd = None if cwd is None else str(Path(cwd).resolve())
        process = subprocess.Popen(command, cwd=child_cwd, env=child_env, shell=False)
        yield process
    except BaseException as error:
        primary = error
        if process is None:
            logger.exception("Script validation or spawn failed")
        raise
    finally:
        try:
            if process is not None:
                _reap(process, float(shutdown_timeout))
        except BaseException as cleanup_error:
            logger.exception("Script cleanup failed pid=%s", process.pid)
            if primary is None:
                raise
            if isinstance(cleanup_error, (KeyboardInterrupt, SystemExit)):
                raise cleanup_error from primary
            primary.add_note(f"Script cleanup failed: {type(cleanup_error).__name__}")
            # Retain the diagnostic object without replacing the caller failure.
            primary.script_cleanup_error = cleanup_error
