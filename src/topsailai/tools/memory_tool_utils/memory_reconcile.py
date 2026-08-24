"""Reconcile Markdown memories with their observable stat records."""

import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime

from topsailai.workspace import lock_tool

from . import memory_hooks, memory_stat

logger = logging.getLogger(__name__)

QUARANTINE_FOLDER = "_quarantine"
TIMESTAMPED_MEMORY_ID = re.compile(r"^\d{14}\.(.+)\.md$", re.DOTALL)
DEFAULT_SYNC_BATCH_LIMIT = 100


@dataclass
class ReconSummary:
    """Describe reconciliation classifications, actions, and elapsed time."""

    scanned: int = 0
    healthy: int = 0
    rebuilt: int = 0
    purged_orphan: int = 0
    quarantined: int = 0
    sync_candidates: int = 0
    sync_dispatched: int = 0
    sync_failed: int = 0
    sync_skipped_limit: int = 0
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


def _list_quarantine_files(quarantine_root: str) -> list[tuple[str, float]]:
    """List quarantined files with mtimes in deterministic order."""
    try:
        names = os.listdir(quarantine_root)
    except FileNotFoundError:
        return []
    files = []
    for name in names:
        path = os.path.join(quarantine_root, name)
        if os.path.isfile(path):
            files.append((path, os.path.getmtime(path)))
    return sorted(files, key=lambda item: (item[1], item[0]))


def _delete_quarantine_file(path: str, reason: str, dry_run: bool) -> None:
    """Delete or report one quarantined file with an observable log."""
    if dry_run:
        logger.info("would delete %s quarantine memory stat: [%s]", reason, path)
        return
    os.remove(path)
    logger.info("delete %s quarantine memory stat: [%s]", reason, path)


def _cleanup_quarantine(
    quarantine_root: str,
    max_age_days: int,
    max_count: int,
    dry_run: bool,
    now: float | None = None,
) -> None:
    """Apply independent age and count limits to quarantined stat files."""
    files = _list_quarantine_files(quarantine_root)
    current_time = time.time() if now is None else now
    max_age_seconds = max_age_days * 86400 if max_age_days > 0 else 0
    surviving = []
    for path, mtime in files:
        if max_age_seconds and current_time - mtime > max_age_seconds:
            _delete_quarantine_file(path, "expired", dry_run)
            continue
        surviving.append((path, mtime))

    if max_count <= 0 or len(surviving) <= max_count:
        return
    for path, _mtime in surviving[: len(surviving) - max_count]:
        _delete_quarantine_file(path, "excess", dry_run)


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
        stat = memory_stat.read_memory_stat_file(stat_file)
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


def _memory_title(memory_id: str) -> str:
    """Derive the original title from a compact timestamped memory identifier."""
    match = TIMESTAMPED_MEMORY_ID.match(memory_id)
    return match.group(1) if match else os.path.splitext(memory_id)[0]


def _read_memory_content(memory_file: str) -> str:
    """Read one local Markdown memory exactly as the sync payload content."""
    with open(memory_file, encoding="utf-8") as stream:
        return stream.read()


def _local_event_version(stat: dict, content: str) -> int:
    """Return a monotonic event version for the current local snapshot."""
    counted_version = stat["update_count"] + 1
    synced_version = stat.get("last_synced_version") or 0
    synced_digest = stat.get("last_synced_content_digest")
    current_digest = memory_stat.get_content_digest(content)
    if synced_digest and synced_digest != current_digest:
        return max(counted_version, synced_version + 1)
    return max(counted_version, synced_version)


def _needs_sync(stat: dict, content: str, event_version: int) -> bool:
    """Return whether local state is newer than the last successful snapshot."""
    if not memory_stat.is_memory_synced(stat):
        return True
    if stat.get("last_synced_version") != event_version:
        return True
    return stat.get("last_synced_content_digest") != memory_stat.get_content_digest(
        content
    )


def _build_sync_event(
    workspace: str,
    memory_id: str,
    memory_file: str,
    content: str,
    stat: dict,
) -> tuple[str, dict]:
    """Build a standard internal sync event for one current local snapshot."""
    event_version = _local_event_version(stat, content)
    operation = (
        memory_hooks.UPDATE
        if memory_stat.is_memory_synced(stat)
        or stat.get("last_synced_version") is not None
        else memory_hooks.CREATE
    )
    event = {
        "op": operation,
        "memory_id": memory_id,
        "title": _memory_title(memory_id),
        "content": content,
        "memory_file": memory_file,
        "workspace": workspace,
        "timestamp": _mtime_timestamp(memory_file),
        "version": event_version,
    }
    return operation, event


def _dispatch_missing_syncs(
    workspace: str,
    markdown_by_id: dict[str, list[str]],
    summary: ReconSummary,
    dry_run: bool,
    sync_batch_limit: int,
) -> None:
    """Dispatch a bounded set of missing local snapshots through standard hooks."""
    candidates = []
    for memory_id in sorted(markdown_by_id):
        paths = markdown_by_id[memory_id]
        if len(paths) != 1:
            continue
        stat = memory_stat.read_memory_stat(workspace, memory_id)
        if stat is None:
            continue
        content = _read_memory_content(paths[0])
        event_version = _local_event_version(stat, content)
        if _needs_sync(stat, content, event_version):
            candidates.append((memory_id, paths[0], content, stat))

    summary.sync_candidates = len(candidates)
    bounded = candidates[:sync_batch_limit]
    summary.sync_skipped_limit = len(candidates) - len(bounded)
    if dry_run:
        return
    for memory_id, memory_file, content, stat in bounded:
        try:
            operation, event = _build_sync_event(
                workspace, memory_id, memory_file, content, stat
            )
            hook_result = memory_hooks.fire_memory_hooks(operation, event)
            if memory_hooks.sync_dispatch_succeeded(hook_result):
                summary.sync_dispatched += 1
                continue
            summary.sync_failed += 1
            summary.errors += 1
            logger.error("no memory sync consumer succeeded: [%s]", memory_id)
        except Exception:
            summary.sync_failed += 1
            summary.errors += 1
            logger.exception("failed to dispatch memory sync: [%s]", memory_id)


def reconcile_memory_stats(
    workspace: str,
    dry_run: bool = True,
    quarantine_max_age_days: int = 0,
    quarantine_max_count: int = 0,
    sync_batch_limit: int = DEFAULT_SYNC_BATCH_LIMIT,
) -> ReconSummary:
    """Reconcile memory stats, missing syncs, and quarantine retention."""
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

        try:
            _dispatch_missing_syncs(
                workspace,
                markdown_by_id,
                summary,
                dry_run,
                max(0, sync_batch_limit),
            )
        except Exception:
            summary.errors += 1
            logger.exception("failed to reconcile memory syncs: [%s]", story_root)

        quarantine_root = os.path.join(stats_root, QUARANTINE_FOLDER)
        try:
            _cleanup_quarantine(
                quarantine_root,
                max(0, quarantine_max_age_days),
                max(0, quarantine_max_count),
                dry_run,
            )
        except Exception:
            summary.errors += 1
            logger.exception("failed to clean quarantine: [%s]", quarantine_root)

    summary.elapsed_ms = int((time.perf_counter() - started) * 1000)
    return summary
