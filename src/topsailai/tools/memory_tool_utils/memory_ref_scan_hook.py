"""Record story-memory citations found in raw LLM response text."""

import logging
import os

logger = logging.getLogger(__name__)


def hook_execute(content):
    """Record unique memory citations and return the response unchanged."""
    if os.environ.get("TOPSAILAI_MEMORY_REFERENCE_SCAN_ENABLED", "1") == "0":
        return content

    try:
        from topsailai.tools import story_memory_tool
        from topsailai.tools.memory_tool_utils import memory_ref_parser, memory_stat

        title_index = memory_ref_parser.build_title_index(
            story_memory_tool.list_memories()
        )
        result = memory_ref_parser.collect_canonical_ids(content, title_index)
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
