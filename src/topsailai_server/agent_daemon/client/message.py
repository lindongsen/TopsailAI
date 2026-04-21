"""
Message Client Module

This module provides the MessageClient class for interacting with
the message-related endpoints of the agent_daemon API.

Features:
    - Send messages to sessions
    - List messages with filtering and pagination
    - Display complete message content with task information

Usage:
    from topsailai_server.agent_daemon.client import MessageClient

    client = MessageClient()
    messages = client.list_messages("session-123")
    client.send_message("session-123", "Hello, world!")
"""

from typing import Any, Dict, List, Optional

from topsailai_server.agent_daemon.client.base import BaseClient, SPLIT_LINE


class MessageClient(BaseClient):
    """
    Client for message-related API operations.

    This class provides methods for managing messages including sending
    and retrieving messages from sessions.

    Example:
        >>> client = MessageClient()
        >>> messages = client.list_messages("session-123")
        >>> client.send_message("session-123", "Hello, world!")
    """

    def send_message(
        self,
        session_id: str,
        message: str,
        role: str = "user",
        processed_msg_id: Optional[str] = None,
        verbose: bool = False
    ) -> Dict[str, Any]:
        """
        Send a message to a session.

        This method calls the ReceiveMessage API which will:
        1. Store the message in the database
        2. Check if there are unprocessed messages
        3. Start the processor if needed

        Args:
            session_id: The session ID to send the message to.
            message: The message content.
            role: The message role, "user" or "assistant" (default: "user").
            processed_msg_id: Optional processed message ID for callback.
            verbose: If True, print full JSON response.

        Returns:
            Dictionary with the API response including any processing results.

        Raises:
            APIError: If the API returns an error.
        """
        data = {
            "message": message,
            "session_id": session_id,
            "role": role,
        }

        if processed_msg_id:
            data["processed_msg_id"] = processed_msg_id

        result = self.post("/api/v1/message", json_data=data)

        # Print formatted output
        print(f"Message sent successfully")

        if verbose:
            import json
            print(json.dumps(result, indent=2))

        return result

    def list_messages(
        self,
        session_id: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        offset: int = 0,
        limit: int = 1000,
        sort_key: str = "create_time",
        order_by: str = "desc",
        processed_msg_id: Optional[str] = None,
        verbose: bool = False
    ) -> List[Dict[str, Any]]:
        """
        List messages from a session with optional filtering and pagination.

        Args:
            session_id: The session ID to retrieve messages from.
            start_time: Filter messages created after this time.
            end_time: Filter messages created before this time.
            offset: Pagination offset (default: 0).
            limit: Maximum number of messages to return (default: 1000).
            sort_key: Field to sort by (default: "create_time").
            order_by: Sort order, "asc" or "desc" (default: "desc").
            processed_msg_id: Filter messages by processed_msg_id field.
            verbose: If True, print full JSON response.

        Returns:
            List of message dictionaries.

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

        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time
        if processed_msg_id:
            params["processed_msg_id"] = processed_msg_id

        messages = self.get("/api/v1/message", params=params)

        # Print formatted output
        total_count = len(messages) if messages else 0
        print(f"Retrieved Messages: {total_count}, Session: {session_id}")

        if verbose:
            import json
            print(json.dumps(messages, indent=2))
        elif messages:
            for message in messages:
                self._print_message(message)

        return messages

    def _print_message(self, message: Dict[str, Any]) -> None:
        """
        Print a single message in formatted output.

        Args:
            message: Message dictionary to print.
        """
        create_time = self.format_time(message.get('create_time'))
        msg_id = message.get('msg_id')
        role = message.get('role')
        content = message.get('message', '')
        task_id = message.get('task_id')
        task_result = message.get('task_result')

        print(SPLIT_LINE)
        # Show time, msg_id, and role on first line
        print(f"[{create_time}] [{msg_id}] [{role}]")
        # Show complete message content (do not omit)
        print(content)

        # If task_id exists, show it
        if task_id:
            print(f">>> task_id: {task_id}")

        # If task_result exists, show it
        if task_result:
            print(f">>> task_result:")
            print(task_result)
