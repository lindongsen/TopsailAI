"""Per-model cumulative statistics storage. Author: DawsonLin.

One document per model and no process segment: every writer of the same model
merges into the same cumulative totals under an advisory lock, so readers never
aggregate per-attempt lines. Values are monotonic totals, not records.

Call only from the owning process's serialized storage worker; the execution
thread must never perform this I/O.
"""

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time

from topsailai.utils.file_tool import ctxm_file_lock
from topsailai.workspace.folder_constants import FOLDER_WORKSPACE_STATS
from topsailai.workspace.session_stats_writer import (
    Diagnostic,
    LINE_CAP,
    WriteResult,
    emit,
    framed,
)

# Default retention requested for model statistics: one month.
RETENTION_DAYS = 30
SLUG_MAX = 48
SUFFIX_LEN = 8
UNKNOWN_MODEL = "unknown"
DOCUMENT_SUFFIX = ".model.stats.json"
READ_CAP = LINE_CAP * 16

# Every accumulated field is a non-negative integer total.
SUM_FIELDS = (
    "turn_count",
    "tool_call_count",
    "tool_error_count",
    "llm_request_count",
    "llm_request_failure_count",
    "tool_duration_ms_sum",
    "llm_request_duration_ms_sum",
    "prompt_tokens",
    "completion_tokens",
    "cached_tokens",
    "first_byte_sum_ms",
    "first_byte_count",
)

_swept = False


def model_slug(model_name) -> str:
    """Build a filesystem-safe slug that stays readable and collision resistant."""
    if type(model_name) is not str or not model_name.strip():
        return UNKNOWN_MODEL
    digest = hashlib.sha256(model_name.encode("utf-8")).hexdigest()[:SUFFIX_LEN]
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", model_name.strip())[:SLUG_MAX]
    cleaned = cleaned.strip("._-") or UNKNOWN_MODEL
    return f"{cleaned}.{digest}"


def model_stats_path(model_name, *, directory=None) -> Path:
    """Resolve the single cumulative document owned by one model name."""
    root = Path(FOLDER_WORKSPACE_STATS if directory is None else directory)
    if not root.is_absolute():
        raise ValueError("model stats directory must be absolute")
    return root / f"{model_slug(model_name)}{DOCUMENT_SUFFIX}"


def _total(value) -> int:
    """Accept only a non-negative integer total; anything else contributes zero."""
    if type(value) is not int or value < 0:
        return 0
    return value


def _now() -> str:
    """Return the host-local timezone-aware timestamp used by the document."""
    return datetime.now().astimezone().isoformat(timespec="microseconds")


def _decode_delta(line: bytes) -> dict:
    """Decode one framed delta payload into validated non-negative totals."""
    value = json.loads(line.decode("utf-8"))
    if type(value) is not dict:
        raise ValueError("invalid delta document")
    return {name: _total(value.get(name)) for name in SUM_FIELDS}


def _merge(current: dict, delta: dict, model_name: str) -> dict:
    """Add one delta to the existing totals without losing document identity."""
    merged = dict(current)
    merged["schema_version"] = 1
    merged["model_name"] = model_name
    merged["model_slug"] = model_slug(model_name)
    stamp = _now()
    merged.setdefault("first_seen", stamp)
    merged["last_updated"] = stamp
    for name in SUM_FIELDS:
        merged[name] = _total(merged.get(name)) + delta[name]
    return merged


def _write_atomic(path: Path, document: dict) -> None:
    """Publish the merged document through a temporary file and os.replace."""
    payload = (
        json.dumps(document, ensure_ascii=False, allow_nan=False, sort_keys=True) + "\n"
    ).encode("utf-8")
    tmp = path.with_name(path.name + ".tmp")
    try:
        with tmp.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def sweep(directory, retention_days, diagnostic: Diagnostic, keep=None) -> int:
    """Delete expired model documents; never touch the document being written."""
    if not retention_days:
        return 0
    cutoff = time.time() - retention_days * 86400
    try:
        entries = list(Path(directory).iterdir())
    except OSError:
        emit(diagnostic, "scan_failure", Path(directory))
        return 0
    deleted = 0
    for path in entries:
        if path == keep or not path.name.endswith(DOCUMENT_SUFFIX):
            continue
        try:
            info = path.lstat()
        except OSError:
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_mtime >= cutoff:
            continue
        emit(diagnostic, "delete_attempt", path)
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        except OSError:
            emit(diagnostic, "delete_failed", path)
            continue
        emit(diagnostic, "deleted", path)
        deleted += 1
    return deleted


def _sweep_once(directory, retention_days, diagnostic: Diagnostic, keep) -> None:
    """Run retention at most once per process, after a successful write."""
    global _swept
    if _swept:
        return
    _swept = True
    try:
        sweep(directory, retention_days, diagnostic, keep)
    except Exception:
        emit(diagnostic, "sweep_failure", Path(directory))


class ModelStatsWriter:
    """Merge framed deltas into one cumulative document per model."""

    def __init__(self, model_name, *, diagnostic: Diagnostic, directory=None,
                 retention_days: float = RETENTION_DAYS):
        """Bind the destination and capabilities; perform no I/O here."""
        self.pid = os.getpid()
        self.model_name = model_name if type(model_name) is str else ""
        self.path = model_stats_path(model_name, directory=directory)
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self.diagnostic = diagnostic
        self.retention_days = retention_days

    def _read(self) -> dict:
        """Read the current document, treating absence and damage as empty totals."""
        try:
            with self.path.open("rb") as stream:
                raw = stream.read(READ_CAP)
        except FileNotFoundError:
            return {}
        except OSError:
            emit(self.diagnostic, "read_failure", self.path)
            return {}
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeError, ValueError):
            emit(self.diagnostic, "invalid_document", self.path)
            return {}
        return value if type(value) is dict else {}

    def append(self, line: bytes) -> WriteResult:
        """Merge one delta under an advisory lock; failures are never requeued."""
        if not framed(line):
            return WriteResult(False, "invalid_record")
        if self.pid != os.getpid():
            return WriteResult(False, "foreign_process")
        try:
            delta = _decode_delta(line)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with ctxm_file_lock(str(self.lock_path), mode="a"):
                _write_atomic(self.path, _merge(self._read(), delta, self.model_name))
        except (OSError, ValueError):
            emit(self.diagnostic, "storage_failure", self.path)
            return WriteResult(False, "storage_failure")
        _sweep_once(self.path.parent, self.retention_days, self.diagnostic, self.path)
        return WriteResult(True, "written")
