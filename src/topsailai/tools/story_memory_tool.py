'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-03
  Purpose:
'''
import logging
import os
from collections import OrderedDict

from topsailai.context.token import count_tokens
from topsailai.utils import env_tool, time_tool
from topsailai.workspace.folder_constants import FOLDER_MEMORY
from .memory_tool_utils import memory_evict, memory_hooks, memory_reconcile, memory_stat
from .tool_utils.parameter import resolve_str_param
from .story_tool import (
    StoryFileInstance,
    build_story_id,
)

logger = logging.getLogger(__name__)

# memory workspace folder, save memory data to it
WORKSPACE = os.getenv("TOPSAILAI_STORY_WORKSPACE") or \
    os.getenv("TOPSAILAI_MEMORY_WORKSPACE") or \
    FOLDER_MEMORY

if WORKSPACE:
    # If set it to ' ', disable this memory tool.
    WORKSPACE = WORKSPACE.strip()
if WORKSPACE:
    assert WORKSPACE[0] == "/", f"Require the use of absolute paths: [{WORKSPACE}]"

_PROMPT_NEW_MEMORY = """
> [Note] You should only keep the latest memory, and for 'repeated old memories', either merge them into new memory or delete them
"""


def _maybe_evict_memories() -> None:
    """Run configured live eviction without failing the originating operation."""
    max_count = _memory_retention_limit("TOPSAILAI_MEMORY_STAT_MAX_COUNT", 0)
    if max_count <= 0:
        return
    try:
        memory_evict.maybe_evict_memory_stats(
            WORKSPACE, max_count, dry_run=False
        )
    except Exception:
        logger.exception("automatic memory eviction failed")


def write_memory(title:str, content:str, **_) -> str:
    """
    Save/Rewrite context key information for future extraction.

    Args:
        title (str): A title contains core information and keywords.
        content (str):
    """
    title, error = resolve_str_param(title, "title")
    if error:
        return error
    content, error = resolve_str_param(content, "content")
    if error:
        return error
    original_title = title
    # PROMPT injects memories into the system prompt, so filenames must expose their timeline.
    # Day-level folders are too coarse, while this prefix preserves second-level ordering.
    # It also avoids managing identical filenames across different timestamp folders.
    title = build_story_id(title, compact_prefix=True)
    operation = (
        memory_hooks.UPDATE
        if StoryFileInstance.get_story_file(WORKSPACE, title)
        else memory_hooks.CREATE
    )

    def update_stat(path: str) -> None:
        """Ensure the stat and count a successful rewrite before hook dispatch."""
        memory_id = memory_stat.get_memory_id(path)
        if operation == memory_hooks.UPDATE:
            memory_stat.record_memory_event(WORKSPACE, memory_id, "update")
            return
        memory_stat.ensure_memory_stat(WORKSPACE, memory_id)

    memory_file = StoryFileInstance.write_story(
        workspace=WORKSPACE,
        story_id=title,
        story_content=content,
        after_write=update_stat,
    )
    _maybe_evict_memories()
    memory_id = memory_stat.get_memory_id(memory_file)
    event = {
        "op": operation,
        "memory_id": memory_id,
        "title": original_title,
        "content": content,
        "memory_file": memory_file,
        "workspace": WORKSPACE,
        "timestamp": time_tool.get_current_local_datetime_with_offset(),
        "version": memory_stat.get_memory_version(WORKSPACE, memory_id),
    }
    try:
        memory_hooks.fire_memory_hooks(operation, event)
    except Exception:
        logger.exception("memory hook dispatch failed: operation=%s", operation)
    return f"new_memory_file={memory_file}" + _PROMPT_NEW_MEMORY


def _resolve_memory_title(title: str) -> str:
    """Resolve a memory title with an optional Markdown extension."""
    for candidate in (title, title + ".md"):
        if os.path.exists(candidate):
            return candidate
    return title


def _read_memory(title: str, count_read: bool) -> str | None:
    """Read one memory and optionally record its read event and run eviction."""
    after_read = None
    if count_read:
        after_read = lambda path: memory_stat.record_memory_event(
            WORKSPACE, memory_stat.get_memory_id(path), "read"
        )
    content = StoryFileInstance.read_story(
        workspace=WORKSPACE,
        story_id=_resolve_memory_title(title),
        after_read=after_read,
    )
    if count_read and content is not None:
        _maybe_evict_memories()
    return content


def read_memory(title:str) -> str|None:
    """Read a memory and record one successful read."""
    title, error = resolve_str_param(title, "title")
    if error:
        return error
    return _read_memory(title, count_read=True)


def read_memory_without_count(title: str) -> str | None:
    """Read a memory without changing observability counters."""
    return _read_memory(title, count_read=False)

def list_memories() -> list[str]|None:
    """
    List all of titles from memory.
    You can refer to these knowledge to avoid making mistakes again.

    Returns:
        list[str]: titles
        None: no found
    """
    return StoryFileInstance.list_stories(workspace=WORKSPACE)

def delete_memory(title:str) -> bool:
    """
    Delete history context information.

    Args:
        title (str): one title from `list_memories`
    """
    title, error = resolve_str_param(title, "title")
    if error:
        return error
    return StoryFileInstance.delete_story(
        workspace=WORKSPACE,
        story_id=title,
        before_delete=lambda path: memory_stat.delete_memory_stat(
            WORKSPACE, memory_stat.get_memory_id(path)
        ),
    )


def _memory_retention_limit(name: str, default: int) -> int:
    """Read one non-negative memory retention limit from the environment."""
    return max(0, env_tool.get_int(name, default=default))


def reconcile_memories(
    dry_run: bool = True,
    sync_batch_limit: int = memory_reconcile.DEFAULT_SYNC_BATCH_LIMIT,
) -> dict:
    """Reconcile memory stats and bounded missing syncs."""
    max_age_days = _memory_retention_limit(
        "TOPSAILAI_MEMORY_STAT_QUARANTINE_MAX_AGE_DAYS", 30
    )
    max_count = _memory_retention_limit(
        "TOPSAILAI_MEMORY_STAT_QUARANTINE_MAX_COUNT", 100
    )
    summary = memory_reconcile.reconcile_memory_stats(
        WORKSPACE,
        dry_run=dry_run,
        quarantine_max_age_days=max_age_days,
        quarantine_max_count=max_count,
        sync_batch_limit=max(0, sync_batch_limit),
    )
    return summary.to_dict()

def get_all_memories() -> dict:
    mem_map = OrderedDict()
    for _title in sorted(list_memories() or []):
        try:
            mem_map[_title] = read_memory_without_count(_title)
        except Exception:
            pass
    return mem_map


def _parse_max_tokens(value) -> int:
    """Parse the startup memory token budget; zero means unlimited."""
    try:
        max_tokens = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, max_tokens)


def _load_memories_lru(max_tokens: int) -> OrderedDict:
    """Load memories most-recently-used first without changing their stats."""
    scored = []
    for title in list_memories() or []:
        stat = memory_stat.read_memory_stat(WORKSPACE, title)
        scored.append((title, stat))

    scored.sort(key=lambda item: (item[1] or {}).get("memory_id", item[0]))
    scored.sort(
        key=lambda item: (item[1] or {}).get("created_at", ""), reverse=True
    )
    scored.sort(
        key=lambda item: (item[1] or {}).get("last_activity_at", ""), reverse=True
    )

    memories = OrderedDict()
    used_tokens = 0
    for title, _stat in scored:
        try:
            content = read_memory_without_count(title)
        except Exception:
            continue
        if content is None:
            continue
        memory_tokens = count_tokens(content)
        if max_tokens > 0 and used_tokens + memory_tokens > max_tokens:
            break
        memories[title] = content
        used_tokens += memory_tokens
    return memories


def get_all_memories_markdown(all_memories:dict=None) -> str:
    result = ""
    if all_memories is None:
        all_memories = get_all_memories()
    for _title, _content in all_memories.items():
        result += f"\n## {_title}\n" + _content + "\n"
    return result

TOOLS = dict(
    write_memory=write_memory,
    read_memory=read_memory,
    list_memories=list_memories,
    delete_memory=delete_memory,
)

FLAG_TOOL_ENABLED = True if WORKSPACE else False

if not WORKSPACE:
    TOOLS.clear()


def get_prompt_memory():
    """Build the bounded, non-counting startup memory observation."""
    max_tokens = _parse_max_tokens(os.getenv("TOPSAILAI_CONTEXT_MEMORY_LOAD_MAX_TOKENS"))
    all_memories = (
        _load_memories_lru(max_tokens) if max_tokens > 0 else get_all_memories()
    )
    return \
f"""
# Current Memories

Titles:

{"\n".join([f"- {mem_title}" for mem_title in all_memories.keys()])}

{get_all_memories_markdown(all_memories)}

# Memory Requirements
{_PROMPT_NEW_MEMORY}

## Citing Memories
When your answer relies on a memory shown above, cite it inline with the exact
title, e.g. `@memory[<TITLE>]`. Cite each relied-upon memory at most once per
response. Only cite memories that are actually listed above.
"""

PROMPT = """
# About story_memory_tool (MemoryTool)

Memory content MUST be English, concise and NO NEED TITLE.

When creating a memory, pass only the original title without a time prefix; the tool adds it automatically.
When deleting a memory, pass `"{time_prefix}.{title}"` as the title, using the full prefixed filename stem.

Whenever the user explicitly asks you to remember something (e.g., using phrases like "remember that...", "please save this:", "don't forget...", "make a note of...", "store this information: [information]"),
you must use the `MemoryTool` to store the specified information.
The information to be stored is the key detail(s) the user wants you to retain for future interactions.

Memory Retrieval, You can read historical contextual information as needed.

## Core Objective
Proactively retrieve relevant memory whenever the user's input contains personal context, historical references, or specific preferences.

## Trigger Scenarios
- **Identity & Preferences**: When the user mentions "I", "my", or personal traits (e.g., "I'm allergic to peanuts", "I prefer dark mode").
- **Task Continuity**: When a request implies past context (e.g., "Recommend a movie [like the ones I watched]", "Continue the coding project").
- **Explicit References**: When the user refers to history (e.g., "Remember when...", "Last time we talked about...", "The file I uploaded").
- **Personalized Feedback**: When the user expresses emotion or evaluation (e.g., "I hated that design", "This is exactly what I needed").

## Retrieval Priority
- **Direct Match**: Keywords matching stored memory tags.
- **Recency**: More recent interactions take precedence.
- **Critical Constraints**: Safety or hard constraints (e.g., allergies, budget limits) must always be retrieved.

## Negative Constraints
- **Do not** retrieve memory for general knowledge queries (e.g., "What is the capital of France?").
- **Do not** retrieve memory if the user explicitly asks for a generic answer.

## Action & Output
- **Synthesize**: Seamlessly integrate retrieved memory into the response to provide a personalized answer.
- **Verify**: If the memory is ambiguous, ask for clarification rather than assuming.
"""

OBSERVATION = get_prompt_memory()

