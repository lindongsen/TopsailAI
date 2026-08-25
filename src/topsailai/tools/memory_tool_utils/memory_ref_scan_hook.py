"""Record story-memory citations found in raw LLM response text."""

import logging
import os
import threading

logger = logging.getLogger(__name__)

_TITLE_INDEX_LOCK = threading.Lock()
_TITLE_INDEX_CACHE = None
_TITLE_INDEX_SIGNATURE = None
_TITLE_INDEX_WORKSPACE = None


def _is_memory_tool_available(story_memory_tool):
    """Return whether memory is enabled and available to the current agent."""
    if not story_memory_tool.FLAG_TOOL_ENABLED:
        return False

    from topsailai.utils.thread_local_tool import get_agent_object

    agent = get_agent_object()
    available_tools = getattr(agent, "available_tools", {}) if agent else {}
    memory_functions = tuple(story_memory_tool.TOOLS.values())
    return any(
        tool_func is memory_func
        for tool_func in available_tools.values()
        for memory_func in memory_functions
    )


def _reset_title_index_cache():
    """Clear cached title-index state for isolated callers and tests."""
    global _TITLE_INDEX_CACHE, _TITLE_INDEX_SIGNATURE, _TITLE_INDEX_WORKSPACE
    with _TITLE_INDEX_LOCK:
        _TITLE_INDEX_CACHE = None
        _TITLE_INDEX_SIGNATURE = None
        _TITLE_INDEX_WORKSPACE = None


def _get_story_folder_signature(workspace):
    """Return metadata for the story root and visible date directories."""
    story_folder = os.path.join(workspace, "story")
    paths = [story_folder]
    with os.scandir(story_folder) as entries:
        paths.extend(
            entry.path
            for entry in entries
            if not entry.name.startswith(".") and entry.is_dir()
        )
    signature = []
    for path in sorted(paths):
        stat_result = os.stat(path)
        signature.append((
            path,
            stat_result.st_mtime_ns,
            stat_result.st_ctime_ns,
            stat_result.st_size,
        ))
    return tuple(signature)


def _get_title_index(story_memory_tool, memory_ref_parser):
    """Return a title index refreshed when story-directory metadata changes."""
    global _TITLE_INDEX_CACHE, _TITLE_INDEX_SIGNATURE, _TITLE_INDEX_WORKSPACE
    signature = _get_story_folder_signature(story_memory_tool.WORKSPACE)
    with _TITLE_INDEX_LOCK:
        if (
            _TITLE_INDEX_CACHE is None
            or _TITLE_INDEX_WORKSPACE != story_memory_tool.WORKSPACE
            or _TITLE_INDEX_SIGNATURE != signature
        ):
            _TITLE_INDEX_CACHE = memory_ref_parser.build_title_index(
                story_memory_tool.list_memories()
            )
            _TITLE_INDEX_SIGNATURE = signature
            _TITLE_INDEX_WORKSPACE = story_memory_tool.WORKSPACE
        return _TITLE_INDEX_CACHE


def hook_execute(content):
    """Record unique memory citations and return the response unchanged."""
    if os.environ.get("TOPSAILAI_MEMORY_REFERENCE_SCAN_ENABLED", "1") == "0":
        return content

    try:
        from topsailai.tools import story_memory_tool

        if not _is_memory_tool_available(story_memory_tool):
            return content

        from topsailai.tools.memory_tool_utils import memory_ref_parser, memory_stat
        from topsailai.utils import env_tool

        title_index = _get_title_index(story_memory_tool, memory_ref_parser)
        bare_title_enabled = env_tool.get_bool(
            "TOPSAILAI_MEMORY_REF_BARE_TITLE_ENABLED", default=True
        )
        result = memory_ref_parser.collect_canonical_ids(
            content,
            title_index,
            bare_title_enabled=bare_title_enabled,
        )
        for memory_id in result.resolved_ids:
            memory_stat.record_memory_event(
                story_memory_tool.WORKSPACE, memory_id, "cite"
            )
    except Exception:
        logger.warning(
            "Failed to record story-memory references from LLM response",
            exc_info=True,
        )
    return content
