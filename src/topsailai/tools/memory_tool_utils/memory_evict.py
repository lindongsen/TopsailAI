"""Evict least-recently-active synchronized story memories."""

import logging
import os
import time
from dataclasses import asdict, dataclass

from topsailai.workspace import lock_tool

from . import memory_stat

logger = logging.getLogger(__name__)


@dataclass
class EvictSummary:
    """Describe eviction scanning, protection, actions, and elapsed time."""

    scanned: int = 0
    eligible: int = 0
    evicted: int = 0
    protected_unsynced: int = 0
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
    """List primary stat files without descending into quarantine."""
    try:
        names = os.listdir(stats_root)
    except FileNotFoundError:
        return []
    return sorted(
        os.path.join(stats_root, name)
        for name in names
        if name.endswith(".json") and os.path.isfile(os.path.join(stats_root, name))
    )


def _healthy_pairs(workspace: str, summary: EvictSummary) -> list[tuple]:
    """Return valid one-to-one Markdown/stat pairs eligible for consideration."""
    story_root = os.path.join(workspace, "story")
    stats_root = os.path.join(story_root, memory_stat.STAT_FOLDER)
    markdown_by_id: dict[str, list[str]] = {}
    for memory_file in _list_markdown_files(story_root):
        memory_id = memory_stat.get_memory_id(memory_file)
        markdown_by_id.setdefault(memory_id, []).append(memory_file)

    healthy = []
    for stat_file in _list_stat_files(stats_root):
        try:
            stat = memory_stat.read_memory_stat_file(stat_file)
            memory_id = stat["memory_id"]
            memory_files = markdown_by_id.get(memory_id, [])
            if stat_file != memory_stat.get_stat_file(workspace, memory_id):
                continue
            if len(memory_files) != 1:
                continue
            healthy.append((memory_id, memory_files[0], stat_file, stat))
        except (OSError, ValueError, TypeError):
            continue
    summary.scanned = len(healthy)
    return healthy


def _select_eviction_victims(
    workspace: str, max_count: int, summary: EvictSummary
) -> list[tuple[str, str]]:
    """Select synchronized LRU victims while protecting every unsynced pair."""
    healthy = _healthy_pairs(workspace, summary)
    synced = []
    for memory_id, memory_file, stat_file, stat in healthy:
        if memory_stat.is_memory_synced(stat):
            synced.append((stat["last_activity_at"], memory_id, memory_file, stat_file))
        else:
            summary.protected_unsynced += 1
    summary.eligible = len(synced)
    overflow = max(0, len(healthy) - max_count)
    synced.sort(key=lambda item: (item[0], item[1]))
    return [(item[2], item[3]) for item in synced[:overflow]]


def select_eviction_victims(
    workspace: str, max_count: int
) -> list[tuple[str, str]]:
    """Return healthy synchronized victim paths in deterministic LRU order."""
    if max_count <= 0:
        return []
    return _select_eviction_victims(workspace, max_count, EvictSummary())


def _delete_victim(memory_file: str, stat_file: str, dry_run: bool) -> None:
    """Delete or report one victim stat-first with observable logging."""
    if dry_run:
        logger.info("would delete evicted memory stat: [%s]", stat_file)
        logger.info("would delete evicted memory: [%s]", memory_file)
        return
    os.remove(stat_file)
    logger.info("delete evicted memory stat: [%s]", stat_file)
    os.remove(memory_file)
    logger.info("delete evicted memory: [%s]", memory_file)


def evict_memory_stats(
    workspace: str,
    max_count: int,
    dry_run: bool = True,
) -> EvictSummary:
    """Evict synchronized healthy memories until the configured bound is met."""
    started = time.perf_counter()
    summary = EvictSummary(dry_run=dry_run)
    if max_count <= 0:
        summary.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return summary

    with lock_tool.FileLock("story_tool", delete_on_release=False):
        victims = _select_eviction_victims(workspace, max_count, summary)
        for memory_file, stat_file in victims:
            memory_id = memory_stat.get_memory_id(memory_file)
            try:
                with lock_tool.FileLock(
                    memory_stat._lock_name(memory_id), delete_on_release=False
                ):
                    _delete_victim(memory_file, stat_file, dry_run)
                summary.evicted += 1
            except Exception:
                summary.errors += 1
                logger.exception("failed to evict memory: [%s]", memory_file)

    summary.elapsed_ms = int((time.perf_counter() - started) * 1000)
    return summary


def maybe_evict_memory_stats(
    workspace: str,
    max_count: int,
    dry_run: bool = False,
) -> EvictSummary:
    """Run eviction when enabled, otherwise return an empty summary."""
    return evict_memory_stats(workspace, max_count, dry_run=dry_run)
