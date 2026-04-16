"""
Session Client Module

This module provides the SessionClient class for interacting with
the session-related endpoints of the agent_daemon API.

Features:
    - List sessions with filtering and pagination
    - Get single session details
    - Delete sessions
    - Process pending messages in a session

Usage:
    from topsailai_server.agent_daemon.client import SessionClient

    client = SessionClient()
    sessions = client.list_sessions()
"""

from typing import Any, Dict, List, Optional

from topsailai_server.agent_daemon.client.base import BaseClient, SPLIT_LINE


class SessionClient(BaseClient):
    """
    Client for session-related API operations.

    This class provides methods for managing sessions including listing,
    retrieving, deleting, and processing sessions.

    Example:
        >>> client = SessionClient()
        >>> sessions = client.list_sessions()
        >>> session = client.get_session("session-123")
        >>> client.delete_sessions(["session-123"])
    """

    def list_sessions(
        self,
        session_ids: Optional[List[str]] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        offset: int = 0,
        limit: int = 1000,
        sort_key: str = "create_time",
        order_by: str = "desc",
        verbose: bool = False
    ) -> List[Dict[str, Any]]:
        """
        List sessions with optional filtering and pagination.

        Args:
            session_ids: Optional list of session IDs to filter.
            start_time: Filter sessions created after this time.
            end_time: Filter sessions created before this time.
            offset: Pagination offset (default: 0).
            limit: Maximum number of sessions to return (default: 1000).
            sort_key: Field to sort by (default: "create_time").
            order_by: Sort order, "asc" or "desc" (default: "desc").
            verbose: If True, print full JSON response.

        Returns:
            List of session dictionaries.

        Raises:
            APIError: If the API returns an error.
        """
        params = {
            "offset": offset,
            "limit": limit,
            "sort_key": sort_key,
            "order_by": order_by,
        }

        if session_ids:
            params["session_ids"] = session_ids
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time

        sessions = self.get("/api/v1/session", params=params)

        # Print formatted output
        total_count = len(sessions) if sessions else 0
        print(f"Retrieved Sessions: {total_count}")

        if verbose:
            import json
            print(json.dumps(sessions, indent=2))
        elif sessions:
            for session in sessions:
                self._print_session(session)

        return sessions

    def get_session(self, session_id: str, verbose: bool = False) -> Dict[str, Any]:
        """
        Get a single session by ID.

        Args:
            session_id: The session ID to retrieve.
            verbose: If True, print full JSON response.

        Returns:
            Session dictionary with all fields including status.

        Raises:
            APIError: If the API returns an error or session not found.
        """
        session = self.get(f"/api/v1/session/{session_id}")

        # Print formatted output
        print(SPLIT_LINE)
        print("Session Details")
        print(SPLIT_LINE)

        create_time = self.format_time(session.get('create_time'))
        update_time = self.format_time(session.get('update_time'))
        session_name = session.get('session_name', 'N/A')
        task = session.get('task', 'N/A')
        processed_msg_id = session.get('processed_msg_id', 'N/A')
        status = session.get('status', 'N/A')

        print(f"Session ID: {session_id}")
        print(f"Session Name: {session_name}")
        print(f"Status: {status}")
        print(f"Task: {task}")
        print(f">>> Processed: {processed_msg_id}")
        print(f"Created: {create_time}")
        print(f"Updated: {update_time}")

        if verbose:
            import json
            print("")
            print(f"Full Response: {json.dumps(session, indent=2)}")

        return session

    def delete_sessions(
        self,
        session_ids: List[str],
        verbose: bool = False
    ) -> Dict[str, Any]:
        """
        Delete multiple sessions.

        Args:
            session_ids: List of session IDs to delete.
            verbose: If True, print full JSON response.

        Returns:
            Dictionary with deletion results including deleted_count.

        Raises:
            APIError: If the API returns an error.
            ValueError: If session_ids is empty.
        """
        if not session_ids:
            raise ValueError("At least one session ID is required")

        params = {
            "session_ids": ",".join(session_ids),
        }

        result = self.delete("/api/v1/session", params=params)

        deleted_count = result.get("deleted_count", 0) if result else 0
        print(f"Deleted {deleted_count} session(s)")

        if verbose:
            import json
            print(json.dumps(result, indent=2))

        return result

    def process_session(self, session_id: str, verbose: bool = False) -> Dict[str, Any]:
        """
        Trigger processing of pending messages for a session.

        This method calls the ProcessSession API which checks if there are
        unprocessed messages and starts the processor if needed.

        Args:
            session_id: The session ID to process.
            verbose: If True, print full JSON response.

        Returns:
            Dictionary with processing results including:
            - processed: bool indicating if processing was started
            - message: str with status message
            - processing_msg_id: msg_id being processed (if any)
            - messages: list of messages being processed (if any)
            - processor_pid: process ID of the processor (if started)

        Raises:
            APIError: If the API returns an error.
        """
        data = {
            "session_id": session_id,
        }

        result = self.post("/api/v1/session/process", json_data=data)

        # Print formatted output
        processed = result.get("processed", False)
        message = result.get("message", "")

        print(f"Session processed: {processed}")
        print(f"Message: {message}")

        if verbose:
            import json
            print(json.dumps(result, indent=2))

        return result

    def _print_session(self, session: Dict[str, Any]) -> None:
        """
        Print a single session in formatted output.

        Args:
            session: Session dictionary to print.
        """
        create_time = self.format_time(session.get('create_time'))
        session_id = session.get('session_id')
        session_name = session.get('session_name', 'N/A')
        task = session.get('task', 'N/A')
        processed_msg_id = session.get('processed_msg_id', 'N/A')

        # Only show one when session_id == session_name
        if session_id == session_name:
            session_display = session_id
        else:
            session_display = f"{session_id}: {session_name}"

        print(SPLIT_LINE)
        print(f"[{create_time}] {session_display}")
        print(f"Task: {task}")
        print(f">>> Processed: {processed_msg_id}")
