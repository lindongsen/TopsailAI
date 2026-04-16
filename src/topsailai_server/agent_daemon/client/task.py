"""
Task Client Module

This module provides the TaskClient class for interacting with
the task-related endpoints of the agent_daemon API.

Features:
    - Set task results
    - List tasks with filtering and pagination
    - Display task content and results

Usage:
    from topsailai_server.agent_daemon.client import TaskClient

    client = TaskClient()
    tasks = client.list_tasks("session-123")
    client.set_task_result("session-123", "msg-id", "task-id", "result")
"""

from typing import Any, Dict, List, Optional

from topsailai_server.agent_daemon.client.base import BaseClient, SPLIT_LINE


class TaskClient(BaseClient):
    """
    Client for task-related API operations.

    This class provides methods for managing tasks including setting
    task results and retrieving task information.

    Example:
        >>> client = TaskClient()
        >>> tasks = client.list_tasks("session-123")
        >>> client.set_task_result("session-123", "msg-id", "task-id", "result")
    """

    def set_task_result(
        self,
        session_id: str,
        processed_msg_id: str,
        task_id: str,
        task_result: str,
        verbose: bool = False
    ) -> Dict[str, Any]:
        """
        Set a task result.

        This method calls the SetTaskResult API which will:
        1. Update the task record with the result
        2. Check if there are unprocessed messages
        3. Start the processor if needed

        Args:
            session_id: The session ID associated with the task.
            processed_msg_id: The processed message ID.
            task_id: The task ID to update.
            task_result: The task result content.
            verbose: If True, print full JSON response.

        Returns:
            Dictionary with the API response.

        Raises:
            APIError: If the API returns an error.
        """
        data = {
            "session_id": session_id,
            "processed_msg_id": processed_msg_id,
            "task_id": task_id,
            "task_result": task_result,
        }

        result = self.post("/api/v1/task", json_data=data)

        # Print formatted output
        print(f"Task result set successfully")

        if verbose:
            import json
            print(json.dumps(result, indent=2))

        return result

    def list_tasks(
        self,
        session_id: str,
        task_ids: Optional[List[str]] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        offset: int = 0,
        limit: int = 1000,
        sort_key: str = "create_time",
        order_by: str = "desc",
        verbose: bool = False
    ) -> List[Dict[str, Any]]:
        """
        List tasks from a session with optional filtering and pagination.

        Args:
            session_id: The session ID to retrieve tasks from.
            task_ids: Optional list of specific task IDs to filter.
            start_time: Filter tasks created after this time.
            end_time: Filter tasks created before this time.
            offset: Pagination offset (default: 0).
            limit: Maximum number of tasks to return (default: 1000).
            sort_key: Field to sort by (default: "create_time").
            order_by: Sort order, "asc" or "desc" (default: "desc").
            verbose: If True, print full JSON response.

        Returns:
            List of task dictionaries.

        Raises:
            APIError: If the API returns an error.
        """
        params = {
            "session_id": session_id,
            "offset": offset,
            "limit": limit,
            "sort_key": sort_key,
            "order_by": order_by,
        }

        if task_ids:
            params["task_ids"] = task_ids
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time

        tasks = self.get("/api/v1/task", params=params)

        # Print formatted output
        total_count = len(tasks) if tasks else 0
        print(f"Retrieved Tasks: {total_count}")

        if verbose:
            import json
            print(json.dumps(tasks, indent=2))
        elif tasks:
            for task in tasks:
                self._print_task(task)

        return tasks

    def _print_task(self, task: Dict[str, Any]) -> None:
        """
        Print a single task in formatted output.

        Args:
            task: Task dictionary to print.
        """
        create_time = self.format_time(task.get('create_time'))
        task_id = task.get('task_id')
        session_id = task.get('session_id')
        msg_id = task.get('msg_id', 'N/A')
        message = task.get('message', '')
        task_result = task.get('task_result')

        print(SPLIT_LINE)
        # Format: [{create_time}] task=[{task_id}] session=[{session_id}] msg=[{msg_id}]
        print(f"[{create_time}] task=[{task_id}] session=[{session_id}] msg=[{msg_id}]")
        # Show task content (message field)
        print(f"Task: {message}")
        # Show separator and task result if exists
        if task_result:
            print("---")
            print(task_result)
