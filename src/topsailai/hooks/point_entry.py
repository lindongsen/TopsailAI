"""Small executable-permission-only Hook Point prototype.

Author: DawsonLin
"""
import asyncio
import importlib.machinery
import importlib.util
import inspect
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from threading import RLock

logger = logging.getLogger(__name__)
_NAME = re.compile(r"hook__[a-z][a-z0-9]*__(?:before|after|error)__[a-z][a-z0-9_]*\Z")


@dataclass(frozen=True)
class PointResources:
    """Own detached external resource selections for one point."""

    name: str
    modules: tuple[Path, ...] = ()
    scripts: tuple[Path, ...] = ()


@dataclass(frozen=True)
class EntryResult:
    """Report execution without interpreting plugin return values."""

    kind: str
    name: str
    status: str


@dataclass(eq=False)
class CleanupRecord:
    """Retain exact child ownership, including unretryable group uncertainty."""

    process: subprocess.Popen
    group_settled: bool = False
    group_retry_safe: bool = True
    child_reaped: bool = False


_cleanup_records = {}
_execution_lock = RLock()


def pending_cleanup():
    """Expose exact recovery handles without discarding unresolved ownership."""
    with _execution_lock:
        return tuple(_cleanup_records.values())


def retry_cleanup(record):
    """Retry only a retained exact record; never mint authority from a PID."""
    with _execution_lock:
        if _cleanup_records.get(id(record.process)) is not record:
            return False
        return _cleanup(record.process)


def decode_points(config):
    """Validate configuration before publishing an immutable snapshot."""
    if type(config) is not dict or len(config) > 128:
        raise ValueError("Hook Points configuration must be a bounded object")
    points = []
    for name, value in config.items():
        if type(name) is not str or not _NAME.fullmatch(name):
            raise ValueError("Invalid Hook Point name")
        if type(value) is not dict or value.keys() - {"modules", "scripts"}:
            raise ValueError("Hook Point requires modules/scripts selections")
        points.append(PointResources(name, _paths(value.get("modules", [])),
                                     _paths(value.get("scripts", []))))
    return tuple(points)


def _paths(value):
    """Detach absolute file/folder selections without trust admission."""
    if type(value) is str:
        value = [value]
    if type(value) is not list or len(value) > 128:
        raise ValueError("Hook resource selections must be a bounded list")
    if any(type(item) is not str or not Path(item).is_absolute() for item in value):
        raise ValueError("Hook resource paths must be absolute")
    return tuple(Path(item) for item in value)


def _discover(selections, internal, kind):
    """Merge direct-child internal/external members and reject duplicate names."""
    roots = ((internal,) if internal.is_dir() else ()) + selections
    entries = []
    for root in roots:
        candidates = tuple(root.iterdir()) if root.is_dir() else (root,)
        if len(candidates) + len(entries) > 128:
            raise ValueError("Hook resource count exceeded")
        entries.extend(path for path in candidates if _eligible(path, kind))
    names = [_logical_name(path, kind) for path in entries]
    if len(names) != len(set(names)):
        raise ValueError("Duplicate Hook resource name")
    return tuple(sorted(entries, key=lambda path: path.name))


def _logical_name(path, kind):
    """Derive the import identity by stripping one recognized Module suffix."""
    if kind != "module":
        return path.name
    if path.name.endswith(".py"):
        return path.name[:-3]
    suffixes = tuple(sorted(importlib.machinery.EXTENSION_SUFFIXES, key=len, reverse=True))
    for suffix in suffixes:
        if path.name.endswith(suffix):
            return path.name[: -len(suffix)]
    return path.name


def _eligible(path, kind):
    """Select Module files or directly executable Script files."""
    if not path.exists():
        raise FileNotFoundError(path)
    if not path.is_file():
        return False
    if kind == "module":
        return _is_module_name(path.name)
    return os.access(path, os.X_OK)


def _is_module_name(name):
    """Accept Python source or a platform interpreter extension, excluding __init__."""
    if name == "__init__.py":
        return False
    if name.endswith(".py"):
        return True
    return any(name.endswith(suffix) for suffix in importlib.machinery.EXTENSION_SUFFIXES)


def execute_point(name, points, *, payload, timeout_seconds=5.0, internal_root=None):
    """Execute one name-ordered point, isolating ordinary resource failures."""
    if not _NAME.fullmatch(name):
        raise ValueError("Invalid Hook Point name")
    if os.name != "posix":
        logger.error("Hook Point %s unavailable: prototype requires POSIX cleanup", name)
        return ()
    deadline = time.monotonic() + timeout_seconds
    _, domain, phase, action = name.split("__")
    base = internal_root or Path(__file__).parent / "points"
    folder = base / domain / f"{phase}_{action}"
    selected = next((point for point in points if point.name == name), PointResources(name))
    try:
        modules = _discover(selected.modules, folder / "modules", "module")
        scripts = _discover(selected.scripts, folder / "scripts", "script")
    except Exception:
        logger.exception("Hook Point %s discovery failed", name)
        return ()
    results = []
    for kind, paths in (("module", modules), ("script", scripts)):
        for path in paths:
            status = _execute(kind, path, payload, deadline)
            results.append(EntryResult(kind, path.name, status))
            if status in ("timeout", "cleanup_failed"):
                return tuple(results)
    return tuple(results)


def _execute(kind, path, payload, deadline):
    """Serialize admission with cleanup so unresolved ownership bounds new work."""
    with _execution_lock:
        if _cleanup_records:
            logger.error("Hook execution blocked by %s pending cleanup records", len(_cleanup_records))
            return "cleanup_failed"
        if kind == "module":
            return _execute_module_inprocess(path, payload, deadline)
        return _execute_script_subprocess(path, deadline)


def _execute_module_inprocess(path, payload, deadline):
    """Import and invoke one Module directly in the current process.

    In-process code cannot be preempted, so the aggregate deadline is checked
    only before invocation; an overrunning Module is not killed. Ordinary
    failures become a structured status, while host control flow propagates.
    """
    if time.monotonic() >= deadline:
        return "timeout"
    try:
        module = _import_module(path)
        entry = getattr(module, "main", None)
        if not callable(entry):
            logger.error("Hook module %s has no callable main entry", path)
            return "error"
        result = entry(**payload)
        if inspect.isawaitable(result):
            asyncio.run(_await_result(result))
        return "success"
    except Exception:
        logger.exception("Hook module %s execution failed", path)
        return "error"


def _import_module(path):
    """Import a selected Module file in-process under its logical name."""
    logical = _logical_name(path, "module")
    parent = str(path.parent)
    inserted = parent not in sys.path
    if inserted:
        sys.path.insert(0, parent)
    try:
        spec = importlib.util.spec_from_file_location(logical, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"unsupported Module source: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if inserted and parent in sys.path:
            sys.path.remove(parent)


async def _await_result(result):
    """Adapt arbitrary awaitables to the coroutine expected by asyncio.run."""
    return await result


def _execute_script_subprocess(path, deadline):
    """Run one isolated Script child with bounded waiting and no shell invocation."""
    if time.monotonic() >= deadline:
        return "timeout"
    process = None
    status = "error"
    primary = None
    try:
        process = subprocess.Popen([str(path)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, start_new_session=True)
        _cleanup_records[id(process)] = CleanupRecord(process)
        code = _wait_owned(process, deadline)
        status = "success" if code == 0 else "error"
        if code:
            logger.error("Hook script %s exited with code %s", path, code)
    except subprocess.TimeoutExpired:
        logger.error("Hook script %s exceeded aggregate deadline", path)
        status = "timeout"
    except Exception:
        logger.exception("Hook script %s execution failed", path)
    except BaseException as error:
        primary = error
        raise
    finally:
        if process is not None:
            try:
                if not _cleanup(process):
                    status = "cleanup_failed"
            except BaseException:
                if primary is None:
                    raise
                logger.exception("Hook cleanup interrupted; preserving primary host interruption")
    return status


def _wait_owned(process, deadline):
    """Observe exit without reaping so group cleanup cannot signal a reused PID."""
    while True:
        observed = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        if observed is not None:
            return observed.si_status if observed.si_code == os.CLD_EXITED else -observed.si_status
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(process.args, 0)
        time.sleep(min(0.01, remaining))


def _cleanup(process):
    """Settle independent group/reap obligations while retaining uncertain ownership."""
    with _execution_lock:
        record = _cleanup_records.setdefault(id(process), CleanupRecord(process))
        if not record.group_settled and record.group_retry_safe:
            _stop_group(record)
        if not record.child_reaped:
            _reap_child(record)
        if record.group_settled and record.child_reaped:
            del _cleanup_records[id(process)]
            return True
        return False


def _stop_group(record):
    """Signal only while the unreaped child anchors the owned process-group ID."""
    try:
        os.killpg(record.process.pid, signal.SIGKILL)
        record.group_settled = True
    except ProcessLookupError:
        record.group_settled = True
    except Exception:
        logger.exception("Hook child group cleanup failed pid=%s", record.process.pid)


def _reap_child(record):
    """Attempt reaping even after group failure, then prohibit historical group signals."""
    record.group_retry_safe = False
    try:
        record.process.wait(timeout=1)
        record.child_reaped = True
    except subprocess.TimeoutExpired:
        logger.error("Hook child reap timeout pid=%s", record.process.pid)
    except Exception:
        logger.exception("Hook child reap failed pid=%s", record.process.pid)
