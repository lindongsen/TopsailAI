'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-03
  Purpose:
'''

import os

from topsailai.workspace.folder_constants import FOLDER_MEMORY_STORY
from .story_tool import (
    StoryFileInstance,
    build_story_id,
)


WORKSPACE = os.getenv("TOPSAILAI_STORY_WORKSPACE") or os.getenv("TOPSAILAI_MEMORY_WORKSPACE") or FOLDER_MEMORY_STORY
if WORKSPACE:
    # If set it to ' ', disable this memory tool.
    WORKSPACE = WORKSPACE.strip()
if WORKSPACE:
    assert WORKSPACE[0] == "/", f"Require the use of absolute paths: [{WORKSPACE}]"


def write_memory(memory_title:str, memory_content:str) -> str:
    """
    Save/Rewrite context key information for future extraction.

    Args:
        memory_title (str): A title contains core information and keywords.
        memory_content (str):
    """
    memory_title = build_story_id(memory_title)
    return StoryFileInstance.write_story(
        workspace=WORKSPACE,
        story_id=memory_title,
        story_content=memory_content,
    )

def read_memory(memory_title:str) -> str|None:
    """
    Read history context information

    Args:
        memory_title (str): use `list_memories` to get title

    Return:
        str, memory content.
        none, no found memory.
    """
    for _file in [
        memory_title,
        memory_title+".md",
    ]:
        if os.path.exists(_file):
            memory_title = _file
            break

    return StoryFileInstance.read_story(workspace=WORKSPACE, story_id=memory_title)

def list_memories() -> list[str]|None:
    """
    List all of titles from memory.

    Returns:
        list[str]: titles
        None: no found
    """
    return StoryFileInstance.list_stories(workspace=WORKSPACE)

def delete_memory(memory_title:str) -> bool:
    """
    Delete history context information.

    Args:
        memory_title (str):
    """
    return StoryFileInstance.delete_story(workspace=WORKSPACE, story_id=memory_title)


TOOLS = dict(
    write_memory=write_memory,
    read_memory=read_memory,
    list_memories=list_memories,
    delete_memory=delete_memory,
)

FLAG_TOOL_ENABLED = True if WORKSPACE else False

if not WORKSPACE:
    TOOLS.clear()

PROMPT = """
## story_memory_tool
You can read historical contextual information as needed.
You should start reading with the latest memory.
"""
