#!/usr/bin/env python3
"""
ACSClient - Python client for AI-Agent Community Server (ACS) REST API.

This module provides a reusable client class for all ACS API operations.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any

import requests

logger = logging.getLogger(__name__)

class ACSAPIError(Exception):
    """Raised when the ACS API returns an error response."""

    def __init__(self, message: str, status_code: int | None = None, trace_id: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.trace_id = trace_id


def setup_logging() -> None:
    """Configure Python logging from the ACS_LOG_LEVEL environment variable."""
    log_level = os.environ.get("ACS_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )


class ACSClient:
    """Client for the AI-Agent Community Server REST API."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        session_key: str | None = None,
    ) -> None:
        """
        Initialize the ACS client.

        Args:
            base_url: The base URL of the ACS server. If not provided,
                      reads from ACS_SERVER_API_BASE env var, defaulting to
                      http://localhost:7370.
            api_key: API key token in the format "ak-{id}.{secret}". If not
                     provided, reads from ACS_API_KEY env var.
            session_key: Session key for X-Session-Key authentication. If not
                         provided, reads from ACS_LOGIN_SESSION_KEY env var.
                         Takes priority over api_key if both are provided.
        """
        self.base_url = (base_url or os.environ.get("ACS_SERVER_API_BASE", "http://localhost:7370")).rstrip("/")
        self.api_key = api_key or os.environ.get("ACS_API_KEY") or None
        self.session_key = session_key or os.environ.get("ACS_LOGIN_SESSION_KEY") or None

        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

        # Session key has priority over API key when both are provided.
        if self.session_key:
            self.session.headers.update({"X-Session-Key": self.session_key})
        elif self.api_key:
            self.session.headers.update({"Authorization": f"Bearer {self.api_key}"})

    def _url(self, path: str) -> str:
        """Build a full URL from a path."""
        return f"{self.base_url}{path}"

    def _request(
        self,
        method: str,
        path: str,
        json_data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """
        Make an HTTP request and handle the standard response format.

        Retries up to 3 times with exponential backoff on transient failures
        (connection errors, timeouts, and HTTP 5xx status codes).

        Standard response: {"data": {...}, "error": "...", "trace_id": "..."}

        Returns:
            The "data" field from the response, or None for 204 No Content.

        Raises:
            ACSAPIError: If the HTTP request fails or the API returns an error.
        """
        url = self._url(path)
        max_retries = 3
        timeout = int(os.environ.get("ACS_REQUEST_TIMEOUT", "30"))

        for attempt in range(max_retries + 1):
            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    json=json_data,
                    params=params,
                    timeout=timeout,
                )
            except requests.RequestException as exc:
                if attempt < max_retries:
                    sleep_time = 2 ** attempt
                    logger.warning(
                        "Request failed (attempt %d/%d), retrying in %ds: %s",
                        attempt + 1,
                        max_retries + 1,
                        sleep_time,
                        exc,
                    )
                    time.sleep(sleep_time)
                    continue
                raise ACSAPIError(f"HTTP request failed: {exc}") from exc

            # Retry on 5xx server errors
            if response.status_code >= 500 and attempt < max_retries:
                sleep_time = 2 ** attempt
                logger.warning(
                    "Server error %d (attempt %d/%d), retrying in %ds",
                    response.status_code,
                    attempt + 1,
                    max_retries + 1,
                    sleep_time,
                )
                time.sleep(sleep_time)
                continue

            # Handle empty-body success responses without parsing JSON.
            # Fast path for 204 No Content, but also guard any empty 2xx body.
            if response.status_code == 204 or not response.content or not response.content.strip():
                if response.ok:
                    return None
                raise ACSAPIError(
                    f"HTTP {response.status_code} with empty body",
                    status_code=response.status_code,
                )

            # Try to parse JSON response
            try:
                body = response.json()
            except json.JSONDecodeError as exc:
                raise ACSAPIError(
                    f"Invalid JSON response (status {response.status_code}): {response.text}",
                    status_code=response.status_code,
                ) from exc

            trace_id = body.get("trace_id")

            # Check for HTTP error status
            if not response.ok:
                error_msg = body.get("error") or f"HTTP {response.status_code}"
                raise ACSAPIError(error_msg, status_code=response.status_code, trace_id=trace_id)

            # Check for API-level error in 200-range responses
            api_error = body.get("error")
            if api_error:
                raise ACSAPIError(api_error, status_code=response.status_code, trace_id=trace_id)

            # Standard envelope: return the "data" field.
            if "data" in body:
                return body["data"]

            # Non-envelope response with trace_id but no data: treat as no data.
            if trace_id:
                return None

            # Fallback: return the raw body only when it looks like a plain object
            # and contains no error/trace_id markers.
            return body

        # Should never reach here, but satisfy type checker
        raise ACSAPIError("Unexpected end of retry loop")

    # ------------------------------------------------------------------
    # Group endpoints
    # ------------------------------------------------------------------

    def create_group(
        self,
        group_name: str,
        group_context: str = "",
        group_key: str = "",
    ) -> dict[str, Any]:
        """
        Create a new group.

        Args:
            group_name: Name of the group.
            group_context: Context/description of the group.
            group_key: Secret key for private groups (empty string for public).

        Returns:
            The created group object.
        """
        payload = {
            "group_name": group_name,
            "group_context": group_context,
            "group_key": group_key,
        }
        return self._request("POST", "/api/v1/groups", json_data=payload)

    def list_groups(
        self,
        offset: int = 0,
        limit: int = 1000,
        sort_key: str = "create_at_ms",
        order_by: str = "desc",
        create_at_ms: str | None = None,
        update_at_ms: str | None = None,
    ) -> dict[str, Any]:
        """
        List all groups.

        Args:
            offset: Number of records to skip.
            limit: Maximum number of records to return.
            sort_key: Field to sort by.
            order_by: Sort direction ("asc" or "desc").
            create_at_ms: Time range filter "start-end" (epoch ms).
            update_at_ms: Time range filter "start-end" (epoch ms).

        Returns:
            Paginated list of groups: {"items": [...], "total": N, ...}
        """
        params: dict[str, Any] = {
            "offset": offset,
            "limit": limit,
            "sort_key": sort_key,
            "order_by": order_by,
        }
        if create_at_ms is not None:
            params["create_at_ms"] = create_at_ms
        if update_at_ms is not None:
            params["update_at_ms"] = update_at_ms
        return self._request("GET", "/api/v1/groups", params=params)

    def get_group(self, group_id: str) -> dict[str, Any]:
        """
        Get a single group by ID.

        Args:
            group_id: The group ID.

        Returns:
            The group object.
        """
        return self._request("GET", f"/api/v1/groups/{group_id}")

    def update_group(self, group_id: str, **kwargs: Any) -> dict[str, Any]:
        """
        Update a group.

        Args:
            group_id: The group ID.
            **kwargs: Fields to update (group_name, group_context, group_key).

        Returns:
            The updated group object.
        """
        return self._request("PUT", f"/api/v1/groups/{group_id}", json_data=kwargs)

    def delete_group(self, group_id: str) -> None:
        """
        Delete a group.

        Args:
            group_id: The group ID.

        Returns:
            None (the API returns 204 No Content).
        """
        self._request("DELETE", f"/api/v1/groups/{group_id}")

    # ------------------------------------------------------------------
    # Member endpoints
    # ------------------------------------------------------------------

    def join_member(
        self,
        group_id: str,
        member_id: str | None = None,
        member_name: str = "",
        member_type: str | None = None,
        member_description: str = "",
        member_interface: dict[str, Any] | str | None = None,
        group_key: str | None = None,
    ) -> dict[str, Any]:
        """
        Add a member to a group, or self-join a public/private group.

        Args:
            group_id: The group ID.
            member_id: Unique member ID. Omit for self-join.
            member_name: Display name of the member.
            member_type: One of "user", "worker-agent", "manager-agent". Omit for self-join.
            member_description: Optional description.
            member_interface: Agent interface configuration (dict or JSON string).
            group_key: Secret key for self-joining a private group.

        Returns:
            The created member object.
        """
        payload: dict[str, Any] = {}
        if member_id is not None:
            payload["member_id"] = member_id
        if member_name:
            payload["member_name"] = member_name
        if member_type is not None:
            payload["member_type"] = member_type
        if member_description:
            payload["member_description"] = member_description
        if member_interface is not None:
            if isinstance(member_interface, dict):
                payload["member_interface"] = json.dumps(member_interface)
            else:
                payload["member_interface"] = member_interface
        if group_key is not None:
            payload["group_key"] = group_key
        return self._request("POST", f"/api/v1/groups/{group_id}/members", json_data=payload)

    def list_members(
        self,
        group_id: str,
        offset: int = 0,
        limit: int = 1000,
        sort_key: str = "create_at_ms",
        order_by: str = "desc",
    ) -> dict[str, Any]:
        """
        List members of a group.

        Args:
            group_id: The group ID.
            offset: Number of records to skip.
            limit: Maximum number of records to return.
            sort_key: Field to sort by.
            order_by: Sort direction ("asc" or "desc").

        Returns:
            Paginated list of members.
        """
        params = {
            "offset": offset,
            "limit": limit,
            "sort_key": sort_key,
            "order_by": order_by,
        }
        return self._request("GET", f"/api/v1/groups/{group_id}/members", params=params)

    def update_member(self, group_id: str, member_id: str, **kwargs: Any) -> dict[str, Any]:
        """
        Update a group member.

        Args:
            group_id: The group ID.
            member_id: The member ID.
            **kwargs: Fields to update.

        Returns:
            The updated member object.
        """
        return self._request("PUT", f"/api/v1/groups/{group_id}/members/{member_id}", json_data=kwargs)

    def leave_member(self, group_id: str, member_id: str) -> dict[str, Any]:
        """
        Remove a member from a group.

        Args:
            group_id: The group ID.
            member_id: The member ID.

        Returns:
            Confirmation message.
        """
        return self._request("DELETE", f"/api/v1/groups/{group_id}/members/{member_id}")

    # ------------------------------------------------------------------
    # Message endpoints
    # ------------------------------------------------------------------

    def send_message(
        self,
        group_id: str,
        message_text: str,
        sender_id: str | None = None,
        sender_type: str | None = None,
        message_attachments: list[dict[str, Any]] | None = None,
        processed_msg_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Send a message to a group.

        Args:
            group_id: The group ID.
            message_text: Message content (may include @mentions).
            sender_id: Optional ID of the sender member. The ACS API derives this
                       from authentication when omitted.
            sender_type: Optional type of the sender ("user", "worker-agent",
                         "manager-agent"). The ACS API derives this from
                         authentication when omitted.
            message_attachments: Optional list of attachment dicts.
            processed_msg_id: Optional ID of the message being processed.

        Returns:
            The created message object.
        """
        payload: dict[str, Any] = {
            "message_text": message_text,
        }
        if sender_id is not None:
            payload["sender_id"] = sender_id
        if sender_type is not None:
            payload["sender_type"] = sender_type
        if message_attachments is not None:
            payload["message_attachments"] = message_attachments
        if processed_msg_id is not None:
            payload["processed_msg_id"] = processed_msg_id
        return self._request("POST", f"/api/v1/groups/{group_id}/messages", json_data=payload)

    def list_messages(
        self,
        group_id: str,
        offset: int = 0,
        limit: int = 1000,
        sort_key: str = "create_at_ms",
        order_by: str = "desc",
        processed_msg_id: str | None = None,
        create_at_ms: str | None = None,
        update_at_ms: str | None = None,
    ) -> dict[str, Any]:
        """
        List messages in a group.

        Args:
            group_id: The group ID.
            offset: Number of records to skip.
            limit: Maximum number of records to return.
            sort_key: Field to sort by.
            order_by: Sort direction ("asc" or "desc").
            processed_msg_id: Filter by processed message ID.
            create_at_ms: Time range filter "start-end" (epoch ms).
            update_at_ms: Time range filter "start-end" (epoch ms).

        Returns:
            Paginated list of messages.
        """
        params: dict[str, Any] = {
            "offset": offset,
            "limit": limit,
            "sort_key": sort_key,
            "order_by": order_by,
        }
        if processed_msg_id is not None:
            params["processed_msg_id"] = processed_msg_id
        if create_at_ms is not None:
            params["create_at_ms"] = create_at_ms
        if update_at_ms is not None:
            params["update_at_ms"] = update_at_ms
        return self._request("GET", f"/api/v1/groups/{group_id}/messages", params=params)

    def get_message(self, group_id: str, message_id: str) -> dict[str, Any]:
        """
        Get a single message.

        Args:
            group_id: The group ID.
            message_id: The message ID.

        Returns:
            The message object.
        """
        return self._request("GET", f"/api/v1/groups/{group_id}/messages/{message_id}")

    def update_message(self, group_id: str, message_id: str, **kwargs: Any) -> dict[str, Any]:
        """
        Update a message.

        Args:
            group_id: The group ID.
            message_id: The message ID.
            **kwargs: Fields to update.

        Returns:
            The updated message object.
        """
        return self._request("PUT", f"/api/v1/groups/{group_id}/messages/{message_id}", json_data=kwargs)

    def delete_message(self, group_id: str, message_id: str) -> dict[str, Any]:
        """
        Soft-delete a message.

        Args:
            group_id: The group ID.
            message_id: The message ID.

        Returns:
            Confirmation message.
        """
        return self._request("DELETE", f"/api/v1/groups/{group_id}/messages/{message_id}")

    # ------------------------------------------------------------------
    # Trigger endpoint
    # ------------------------------------------------------------------

    def trigger_message(
        self,
        group_id: str,
        message_id: str,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Manually trigger agent processing for a message.

        This bypasses NO_TRIGGER_CASES.

        Args:
            group_id: The group ID.
            message_id: The message ID to trigger.
            agent_id: Optional specific agent ID to trigger.

        Returns:
            Trigger status object with {"status": "pending", ...}
        """
        payload: dict[str, Any] = {}
        if agent_id is not None:
            payload["agent_id"] = agent_id
        return self._request(
            "POST",
            f"/api/v1/groups/{group_id}/messages/{message_id}/trigger",
            json_data=payload,
        )

    # ------------------------------------------------------------------
    # Polling helper
    # ------------------------------------------------------------------

    def wait_for_response(
        self,
        group_id: str,
        processed_msg_id: str,
        timeout: int = 600,
        poll_interval: int = 2,
    ) -> dict[str, Any]:
        """
        Poll for a response message with the given processed_msg_id.

        Args:
            group_id: The group ID.
            processed_msg_id: The processed message ID to look for.
            timeout: Maximum time to wait in seconds.
            poll_interval: Seconds between polls.

        Returns:
            The first response message found.

        Raises:
            ACSAPIError: If timeout is reached without finding a response.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            result = self.list_messages(
                group_id=group_id,
                processed_msg_id=processed_msg_id,
                limit=10,
                order_by="desc",
            )
            items = result.get("items", [])
            for msg in items:
                if msg.get("processed_msg_id") == processed_msg_id:
                    return msg
            time.sleep(poll_interval)

        raise ACSAPIError(
            f"Timeout waiting for response to message {processed_msg_id} "
            f"after {timeout} seconds",
        )
