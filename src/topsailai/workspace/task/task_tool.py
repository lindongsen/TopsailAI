'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-11
  Purpose:
'''

import os
from contextlib import contextmanager

from topsailai.utils.file_tool import (
    ctxm_try_file_lock,
    delete_file,
    write_text,
)
from topsailai.utils import (
    time_tool,
    json_tool,
)
from topsailai.workspace.folder_constants import (
    FOLDER_WORKSPACE_TASK,
)


class TaskData(object):
    """
    Data class to store task information.

    Attributes:
        TASK_STATUS_INITING: Status indicating task is being initialized
        TASK_STATUS_WORKING: Status indicating task is currently being processed
        TASK_STATUS_DONE: Status indicating task has been completed
        task_id: Unique identifier for the task
        task_file: Path to the task file on disk
        task_content: The actual content/data of the task
        create_time: Timestamp when the task was created
        session_id: Session identifier associated with the task
        session_messages: List of messages in the session
        status: Current status of the task
        result: Result of the task execution (if available)
    """
    TASK_STATUS_INITING = "initializing"
    TASK_STATUS_WORKING = "working"
    TASK_STATUS_DONE = "done"

    def __init__(self, task_id:str):
        """
        Initialize a TaskData instance.

        Args:
            task_id (str): Unique identifier for the task
        """
        self.task_id = task_id
        self.task_file = FOLDER_WORKSPACE_TASK + f"/{task_id}.task"

        self.task_content = None
        self.create_time = time_tool.get_current_date(with_t=True)
        self.session_id = os.getenv("SESSION_ID") or ""
        self.session_messages = []

        self.status = self.TASK_STATUS_INITING

        # result
        self.result = None

    @property
    def manifest(self) -> str:
        """
        Generate a YAML-formatted manifest containing task metadata.

        Returns:
            str: YAML string containing task_id and status
        """
        return f"""---
task_id: {self.task_id}
status: {self.status}
---
"""

    def to_dict(self) -> dict:
        """
        Convert task data to a dictionary.

        Returns:
            dict: Dictionary containing task_id, task_content, session_id,
                  session_messages, and create_time
        """
        return dict(
            task_id=self.task_id,
            task_content=self.task_content,
            session_id=self.session_id,
            session_messages=self.session_messages,
            create_time=self.create_time,
        )

    def to_json(self) -> str:
        """
        Convert task data to a JSON string.

        Returns:
            str: JSON-formatted string of the task data
        """
        json_data = json_tool.safe_json_dump(self.to_dict(), indent=2)
        return json_data

class TaskUtil(TaskData):
    """
    Utility class for loading, dumping, and managing task data with file locking.
    Inherits from TaskData and adds file operations and locking capabilities.
    """

    def load(self) -> bool:
        """
        Load task data from the task file.

        Reads the task file contents, parses the JSON data, and populates
        the instance attributes with the loaded values.

        Returns:
            bool: True if data was successfully loaded, False otherwise
        """
        json_data = ""
        with open(self.task_file, encoding='utf-8') as fp:
            json_data = fp.read()
        if not json_data:
            return False
        d = json_tool.safe_json_load(json_data)
        if not d:
            return False
        self.task_content = d["task_content"]
        self.session_id = d["session_id"]
        self.session_messages = d["session_messages"]
        self.create_time = d["create_time"]
        return True

    def dump(self, fp) -> bool:
        """
        Dump (write) task data to a file.

        Serializes the task data to JSON and writes it to the provided file
        pointer or creates a new task file if no file pointer is given.

        Args:
            fp: File pointer to write to, or None to create a new file

        Returns:
            bool: True if data was successfully written
        """
        json_data = self.to_json()
        if fp:
            fp.write(json_data)
            fp.flush()
            return True

        assert not os.path.exists(self.task_file), f"The task file exists and cannot be overwritten: {self.task_file}"
        with open(self.task_file, mode='w', encoding='utf-8') as fp:
            fp.write(json_data)
            fp.flush()

        return True

    def pre_lock(self):
        """
        Prepare for locking the task file.

        Creates an empty task file if it doesn't exist yet.
        This is called before attempting to acquire a file lock.
        """
        if not os.path.exists(self.task_file):
            write_text(self.task_file, "")

        return

    def post_lock(self, fp):
        """
        Handle post-lock operations.

        After acquiring the lock, this method sets the task status to working
        and either dumps the current task content to the file or loads existing
        data from the file if no content was provided.

        Args:
            fp: File pointer to the locked task file
        """
        self.status = self.TASK_STATUS_WORKING
        if self.task_content:
            self.dump(fp)
        else:
            self.load()
        return

    def pre_unlock(self, fp):
        """
        Handle pre-unlock operations.

        Before releasing the lock, this method checks if a result exists
        and updates the task status to done if a result is available.

        Args:
            fp: File pointer to the locked task file
        """
        if self.result:
            self.status = self.TASK_STATUS_DONE
        return

    def post_unlock(self):
        """
        Handle post-unlock operations.

        After releasing the lock, this method checks if the task is completed
        and deletes the task file if the status is done.
        """
        if self.status == self.TASK_STATUS_DONE:
            delete_file(self.task_file)
        return


@contextmanager
def ctxm_process_task(task:TaskUtil):
    """
    Context manager for processing a task with file locking.

    This context manager handles the entire lifecycle of task processing:
    1. Acquires an exclusive lock on the task file
    2. Writes task content to the file (or loads existing data)
    3. Yields control to the caller for actual task processing
    4. Updates task status before unlocking
    5. Releases the lock and cleans up (deletes file if task is done)

    Args:
        task (TaskUtil): The task to process

    Yields:
        File pointer to the locked task file for the caller to use

    Example:
        task = TaskUtil("task_123")
        task.task_content = "do something"
        with ctxm_process_task(task) as fp:
            # process task here
            task.result = "success"
    """
    if task is None:
        yield None
        return

    task.pre_lock()
    with ctxm_try_file_lock(task.task_file) as fp:
        assert fp, f"lock task file failed: task is being executed: {task.task_file}"
        task.post_lock(fp)
        yield fp
        task.pre_unlock(fp)
    task.post_unlock()
    return
