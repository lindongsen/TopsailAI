"""Reconcile Markdown memories with their observable stat records."""

import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime

from topsailai.workspace import lock_tool

from . import memory_stat

logger = logging.getLogger(__name__)

QUARANTINE_FOLDER = "_quarantine"


@dataclass
class ReconSummary:
    """Describe reconciliation classifications, actions, and elapsed time."""

    scanned: int = 0
    healthy: int = 0
    rebuilt: int = 0
    purged_orphan: int = 0
    quarantined: int = 0
    errors: int = 0
    dry_run: bool = True
    elapsed_ms: int = 0

    def to_dict(self) -> dict:
        """Return a JSON-friendly representation of this summary."""
        return asdict(self)


def _list_markdown_files(story_root: str) -> list[str]:
    """List visible Markdown memory files in deterministic path order."""
    files = []
    for root, dirs, names in os.walk(story_root):
        dirs[:] = sorted(name for name in dirs if not name.startswith("."))
        for name in sorted(names):
            if not name.startswith(".") and name.lower().endswith(".md"):
                files.append(os.path.join(root, name))
    return sorted(files)


def _list_stat_files(stats_root: str) -> list[str]:
    """List primary stat JSON files without descending into quarantine."""
    try:
        names = os.listdir(stats_root)
    except FileNotFoundError:
        return []
    return sorted(
        os.path.join(stats_root, name)
        for name in names
        if name.endswith(".json") and os.path.isfile(os.path.join(stats_root, name))
    )


def _read_stat(stat_file: str) -> dict:
    """Read one stat without invoking the normal auto-rebuild behavior."""
    with open(stat_file, encoding="utf-8") as fd:
        stat = json.load(fd)
    memory_id = stat.get("memory_id") if isinstance(stat, dict) else ""
    return memory_stat._validate_stat(stat, memory_id)


def _mtime_timestamp(memory_file: str) -> str:
    """Format a memory file mtime using the persisted local-time contract."""
    local_mtime = datetime.fromtimestamp(os.path.getmtime(memory_file)).astimezone()
    timestamp = local_mtime.strftime("%Y-%m-%d %H:%M:%S %z")
    return timestamp[:-2] + ":" + timestamp[-2:]


def _rebuild_stat(workspace: str, memory_id: str, memory_file: str) -> None:
    """Create a zero-count stat whose creation time comes from Markdown mtime."""
    timestamp = _mtime_timestamp(memory_file)

    def set_creation_time(stat: dict, _timestamp: str) -> None:
        stat["created_at"] = timestamp
        stat["last_activity_at"] = timestamp

    memory_stat.mutate_memory_stat(workspace, memory_id, set_creation_time)


def _quarantine_file(workspace: str, stat_file: str) -> None:
    """Move a suspicious stat into quarantine while logging the movement."""
    stats_root = os.path.dirname(stat_file)
    quarantine_root = os.path.join(stats_root, QUARANTINE_FOLDER)
    os.makedirs(quarantine_root, exist_ok=True)
    suffix = str(time.time_ns())
    destination = os.path.join(quarantine_root, os.path.basename(stat_file) + "." + suffix)
    logger.warning("quarantine memory stat: [%s] -> [%s]", stat_file, destination)
    os.replace(stat_file, destination)


def _expected_stat_name(memory_id: str) -> str:
    """Return the encoded stat basename for a canonical memory identifier."""
    return os.path.basename(memory_stat.get_stat_file("/", memory_id))


def _process_stat(
    workspace: str,
    stat_file: str,
    markdown_by_id: dict[str, list[str]],
    dry_run: bool,
    summary: ReconSummary,
) -> str | None:
    """Classify and optionally repair one existing stat file."""
    stat_name = os.path.basename(stat_file)
    digest_to_ids = {
        _expected_stat_name(memory_id): memory_id for memory_id in markdown_by_id
    }
    path_memory_id = digest_to_ids.get(stat_name)
    try:
        stat = _read_stat(stat_file)
        embedded_id = stat["memory_id"]
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        summary.quarantined += 1
        if not dry_run:
            lock_id = path_memory_id or stat_name
            with lock_tool.FileLock(
                memory_stat._lock_name(lock_id), delete_on_release=False
            ):
                _quarantine_file(workspace, stat_file)
        return path_memory_id

    expected_name = _expected_stat_name(embedded_id)
    paths = markdown_by_id.get(embedded_id, [])
    if expected_name != stat_name or len(paths) > 1:
        summary.quarantined += 1
        if not dry_run:
            with lock_tool.FileLock(
                memory_stat._lock_name(embedded_id), delete_on_release=False
            ):
                _quarantine_file(workspace, stat_file)
        return embedded_id
    if not paths:
        summary.purged_orphan += 1
        if not dry_run:
            memory_stat.delete_memory_stat(workspace, embedded_id)
        return embedded_id

    summary.healthy += 1
    return embedded_id


def reconcile_memory_stats(workspace: str, dry_run: bool = True) -> ReconSummary:
    """Classify and reconcile memory/stat inconsistencies under the story lock."""
    started = time.perf_counter()
    summary = ReconSummary(dry_run=dry_run)
    story_root = os.path.join(workspace, "story")
    stats_root = os.path.join(story_root, memory_stat.STAT_FOLDER)

    with lock_tool.FileLock("story_tool", delete_on_release=False):
        markdown_by_id: dict[str, list[str]] = {}
        for memory_file in _list_markdown_files(story_root):
            memory_id = memory_stat.get_memory_id(memory_file)
            markdown_by_id.setdefault(memory_id, []).append(memory_file)

        stat_files = _list_stat_files(stats_root)
        summary.scanned = sum(len(paths) for paths in markdown_by_id.values()) + len(
            stat_files
        )
        represented_ids = set()
        for stat_file in stat_files:
            try:
                represented_id = _process_stat(
                    workspace, stat_file, markdown_by_id, dry_run, summary
                )
                if represented_id:
                    represented_ids.add(represented_id)
            except Exception:
                summary.errors += 1
                logger.exception("failed to reconcile memory stat: [%s]", stat_file)

        for memory_id in sorted(markdown_by_id):
            paths = markdown_by_id[memory_id]
            if memory_id in represented_ids:
                continue
            if len(paths) != 1:
                summary.errors += 1
                logger.error("ambiguous memory identifier: [%s]", memory_id)
                continue
            summary.rebuilt += 1
            if not dry_run:
                try:
                    _rebuild_stat(workspace, memory_id, paths[0])
                except Exception:
                    summary.rebuilt -= 1
                    summary.errors += 1
                    logger.exception("failed to rebuild memory stat: [%s]", memory_id)

    summary.elapsed_ms = int((time.perf_counter() - started) * 1000)
    return summary
