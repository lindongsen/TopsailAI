'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-11-24
  Purpose:
'''

import os

from topsailai.utils import (
    time_tool,
    file_tool,
    env_tool,
)
from topsailai.prompt_hub import prompt_tool
from topsailai.workspace import (
    lock_tool,
)

KEY_STORY = "story"

PROMPT_SUMMARY = prompt_tool.read_prompt("context/summary/L0.md")

PROMPT_SUMMARY_AS_STORY = PROMPT_SUMMARY + """
Use story_tool to save content.
[Attention] story_id is Heading/Title, also is filename, max length is 250, Cannot contain any special characters other than '_-'
""" + env_tool.EnvReaderInstance.story_prompt_content


class StoryBase(object):
    name = "story_tool"

    def assert_workspace(self, workspace:str):
        if not workspace \
            or workspace == '/' \
            or workspace[0] != '/' \
        :
            raise Exception(f"illegal workspace: {workspace}")
        return

    def write_story(self, workspace:str, story_id: str, story_content:str) -> bool:
        raise NotImplementedError

    def read_story(self, workspace:str, story_id:str) -> str|None:
        raise NotImplementedError

    def delete_story(self, workspace:str, story_id:str) -> bool:
        raise NotImplementedError

    def list_stories(self, workspace:str) -> list[str]|None:
        raise NotImplementedError

    def retrieve_stories(self, workspace:str, keywords:str) -> list[dict]:
        """
        Args:
            workspace (str):
            keywords (str): split by ','
        """
        raise NotImplementedError


class StoryFile(StoryBase):

    def get_story_file(self, workspace:str, story_id:str):
        """get a file path for the story content.

        Args:
            workspace (str): folder path.
            story_id (str): story id.

        Return:
            str, a file path.
            none, failed to get file.
        """
        story_folder = os.path.join(workspace, KEY_STORY)
        files = file_tool.find_files_by_name(story_folder, story_id)
        if files:
            return files[0]
        return None

    def write_story(self, workspace:str, story_id:str, story_content:str):
        """save story content.

        Args:
            workspace (str): folder path.
            story_id (str): story id.
            story_content (str): story content.
        """
        with lock_tool.FileLock(self.name):
            folder_path = os.path.join(workspace, KEY_STORY, time_tool.get_current_day())
            file_path = os.path.join(folder_path, story_id)
            os.makedirs(folder_path, exist_ok=True)
            with open(file_path, "w+", encoding="utf-8") as fd:
                fd.write(story_content)
            return file_path

    def read_story(self, workspace:str, story_id:str):
        """read story content.

        Args:
            workspace (str): folder path.
            story_id (str): story id.

        Return:
        str, story content.
        none, no found story.
        """
        with lock_tool.FileLock(self.name):
            story_file = self.get_story_file(workspace, story_id)
            if not story_file:
                return None
            with open(story_file, encoding='utf-8') as fd:
                return fd.read()
            return None

    def list_stories(self, workspace:str) -> list[str]|None:
        """List all of stories from workspace.

        Args:
            workspace (str): folder path.

        Returns:
            list[str]:
            None: no found
        """
        with lock_tool.FileLock(self.name):
            # find all of them
            results = file_tool.list_files(workspace)

            # only filename
            stories = []
            for _file in results:
                stories.append(os.path.basename(_file))
            return stories

    def retrieve_stories(self, workspace:str, keywords:str) -> list[dict]|None:
        """Retrieve lots of stories.

        Args:
            workspace (str): folder path.
            keywords (str): split by '|', example: 'A|B' is A or B
        """
        with lock_tool.FileLock(self.name):
            file_set = file_tool.list_files(
                workspace,
                included_filename_keywords=keywords.split('|'),
            )
            if not file_set:
                return None

            results = []
            for _filepath in file_set:
                _file_d = {
                    "title": os.path.basename(_filepath),
                    "content": "",
                }
                results.append(_file_d)
                with open(_filepath, encoding="utf-8") as fd:
                    _file_d["content"] = fd.read()

            return results

    def delete_story(self, workspace:str, story_id:str):
        """delete a story.

        Args:
            workspace (str): folder path
            story_id (str):
        """
        with lock_tool.FileLock(self.name):
            _filepath = self.get_story_file(workspace, story_id)
            if _filepath:
                file_tool.delete_file(_filepath)
            return

# init
StoryFileInstance = StoryFile()

# default tools, only read/write
TOOLS = dict(
    write_story=StoryFileInstance.write_story,
    read_story=StoryFileInstance.read_story,
)

# enhance tools, support read/write/list/retrieve
STORY_FILE_RWLR_TOOLS = dict(
    write_story=StoryFileInstance.write_story,
    read_story=StoryFileInstance.read_story,
    list_stories=StoryFileInstance.list_stories,
    retrieve_stories=StoryFileInstance.retrieve_stories,
)

# all tools
STORY_FILE_ALL_TOOLS = dict(
    write_story=StoryFileInstance.write_story,
    read_story=StoryFileInstance.read_story,
    list_stories=StoryFileInstance.list_stories,
    retrieve_stories=StoryFileInstance.retrieve_stories,
    delete_story=StoryFileInstance.delete_story,
)
