'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-03
  Purpose:
'''

import os
from collections import OrderedDict

from topsailai.workspace.folder_constants import FOLDER_MEMORY
from .story_tool import (
    StoryFileInstance,
    build_story_id,
)

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


def write_memory(title:str, content:str, **_) -> str:
    """
    Save/Rewrite context key information for future extraction.

    Args:
        title (str): A title contains core information and keywords.
        content (str):
    """
    title = build_story_id(title)
    memory_file = StoryFileInstance.write_story(
        workspace=WORKSPACE,
        story_id=title,
        story_content=content,
    )
    return f"new_memory_file={memory_file}" + _PROMPT_NEW_MEMORY

def read_memory(title:str) -> str|None:
    """
    Read history context information

    Args:
        title (str): use `list_memories` to get title

    Return:
        str, memory content.
        none, no found memory.
    """
    for _file in [
        title,
        title+".md",
    ]:
        if os.path.exists(_file):
            title = _file
            break

    return StoryFileInstance.read_story(workspace=WORKSPACE, story_id=title)

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
    return StoryFileInstance.delete_story(workspace=WORKSPACE, story_id=title)

def get_all_memories() -> dict:
    mem_map = OrderedDict()
    for _title in sorted(list_memories()):
        try:
            mem_map[_title] = read_memory(_title)
        except:
            pass
    return mem_map

def get_all_memories_markdown(all_memories:dict=None) -> str:
    result = ""
    if not all_memories:
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
    """ refer to context/prompt_env.py """
    all_memories = get_all_memories()
    return \
f"""
# Current Memories

Titles:

{"\n".join([f"- {mem_title}" for mem_title in all_memories.keys()])}

{get_all_memories_markdown(all_memories)}

# Memory Requirements
{_PROMPT_NEW_MEMORY}
"""

PROMPT = """
# About story_memory_tool (MemoryTool)

Memory content MUST be English, concise and NO NEED TITLE.

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
""" + get_prompt_memory()
