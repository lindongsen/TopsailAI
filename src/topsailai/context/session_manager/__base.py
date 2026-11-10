"""
Base module for session management in AI engineering context.

This module defines the foundational classes and interfaces for managing
session data and storage operations within the AI engineering framework.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2025-10-29
"""

from datetime import datetime

from topsailai.context.chat_history_manager.__base import (
    ChatHistoryMessageData,
)

class SessionData(object):
    """
    Data container for a single session in the AI engineering framework.

    This class holds the essential information about a session, including
    its unique identifier, associated task, runtime environment paths, and
    accumulated token usage. Additional metadata like session name and
    creation time can be stored as attributes.
    """
    def __init__(
        self,
        session_id: str,
        task: str = "",
        session_name: str = None,
        project_workspace: str = None,
        pwd: str = None,
        topsailai_home: str = None,
        total_tokens: int = 0,
        total_cached_tokens: int = 0,
        total_completion_tokens: int = 0,
        category: str = "",
        turn_count: int = 0,
        tool_call_count: int = 0,
        tool_error_count: int = 0,
        llm_request_count: int = 0,
        llm_request_failure_count: int = 0,
        tool_duration_ms_sum: int = 0,
        llm_request_duration_ms_sum: int = 0,
        summary_count: int = 0,
    ):
        """
        Initialize a SessionData instance.

        Args:
            session_id (str): Unique identifier for the session
            task (str, optional): The task or purpose associated with this session.
                Defaults to an empty string.
            session_name (str, optional): Display name for the session
            project_workspace (str, optional): Project workspace path at session creation
            pwd (str, optional): Working directory at session creation
            topsailai_home (str, optional): TopsailAI home directory at session creation
            total_tokens (int, optional): Accumulated prompt tokens for backward
                compatibility. Defaults to 0.
            total_cached_tokens (int, optional): Accumulated cached prompt tokens.
                Defaults to 0.
            total_completion_tokens (int, optional): Accumulated completion tokens.
                Defaults to 0.
            category (str, optional): Session category. Defaults to an empty string.
            summary_count (int, optional): Successfully applied summaries. Defaults to 0.
            turn_count (int, optional): Settled User2Agent turns. Defaults to 0.
            tool_call_count (int, optional): Measured tool calls. Defaults to 0.
            tool_error_count (int, optional): Tool calls that reported an error.
                Defaults to 0.
            llm_request_count (int, optional): LLM requests attempted. Defaults to 0.
            llm_request_failure_count (int, optional): Failed LLM requests.
                Defaults to 0.
            tool_duration_ms_sum (int, optional): Total tool duration in
                milliseconds. Defaults to 0.
            llm_request_duration_ms_sum (int, optional): Total LLM request duration
                in milliseconds. Defaults to 0.

        Note:
            Additional attributes like session_name and create_time are
            initialized to None and can be set later.
        """
        self.session_id = session_id
        self.task = task

        # other attributes that can be set later
        self.session_name = session_name
        self.project_workspace = project_workspace
        self.pwd = pwd
        self.topsailai_home = topsailai_home
        self.create_time = None
        self.update_time = None
        self.total_tokens = total_tokens
        self.total_cached_tokens = total_cached_tokens
        self.total_completion_tokens = total_completion_tokens
        self.category = category
        self.summary_count = summary_count
        self.turn_count = turn_count
        self.tool_call_count = tool_call_count
        self.tool_error_count = tool_error_count
        self.llm_request_count = llm_request_count
        self.llm_request_failure_count = llm_request_failure_count
        self.tool_duration_ms_sum = tool_duration_ms_sum
        self.llm_request_duration_ms_sum = llm_request_duration_ms_sum

    @property
    def total_prompt_tokens(self):
        """Return accumulated prompt tokens under an explicit name."""
        return self.total_tokens or 0

    @property
    def total_usage_tokens(self):
        """Return accumulated prompt plus completion tokens."""
        return self.total_prompt_tokens + (self.total_completion_tokens or 0)

    def __str__(self):
        """Return string representation of SessionData."""
        return f"SessionData(session_id={self.session_id}, task={self.task})"

class SessionStorageBase(object):
    """
    Abstract base class for session storage implementations.

    This class defines the interface that all session storage backends
    must implement. It provides methods for creating new sessions and
    listing existing sessions. Concrete implementations should handle
    persistence, such as database or file-based storage.

    Attributes:
        tb_session (str): Name of the session table/collection in storage.
    """
    tb_session = "session"

    def __init__(self):

        # chat_history_manager
        self.chat_history = None

    def exists_session(self, session_id) -> bool:
        """ True for existing """
        raise NotImplementedError

    def create_session(self, session_data: SessionData):
        """
        Create a new session and maintain historical limit.

        This method persists a new session to the storage backend and ensures
        that only the most recent 100 counted sessions are retained. Sessions
        whose category is excluded from retention (for example `agent_driver`)
        are neither counted nor removed by this limit. Older counted sessions
        beyond this limit should be automatically removed.

        Args:
            session_data (SessionData): The session data to be created and stored

        Raises:
            NotImplementedError: This is an abstract method that must be
                implemented by concrete storage classes.
        """
        raise NotImplementedError

    def list_sessions(
        self,
        sessions: list[str] = None,
        order_by: str = None,
        offset: int = 0,
        limit: int = None,
        category: str = None,
        included_categories: set[str] = None,
        excluded_categories: set[str] = None,
        has_project: bool = False,
        since: datetime = None,
        until: datetime = None,
    ) -> list[SessionData]:
        """
        Retrieve stored sessions, optionally filtered, sorted, and paginated.

        Args:
            sessions (list[str], optional): A list of session IDs to include.
                When provided, only sessions whose ID is in this list are returned.
                When empty or None, all sessions are returned.
            order_by (str, optional): Field name to sort by. Supported fields include
                ``session_id``, ``session_name``, ``task``, and ``create_time``.
                Prefix the field name with ``-`` for descending order
                (e.g., ``-created_at``). When not provided, the default order is
                implementation-defined (typically ``create_time`` descending).
            offset (int, optional): Number of sessions to skip. Defaults to ``0``.
            limit (int, optional): Maximum number of sessions to return.
                If ``None``, all matching sessions are returned.
            category (str, optional): Exact category to include. ``None`` includes
                every category; an empty string selects uncategorized sessions.
            included_categories (set[str], optional): Categories to include. Names
                are matched exactly and are expected to be already validated; an
                empty string includes uncategorized sessions. ``None`` or an empty
                set includes every category. Combined with ``category`` by
                intersection and with ``excluded_categories`` by subtraction.
            excluded_categories (set[str], optional): Categories to exclude. Names
                are matched exactly and are expected to be already validated; an
                empty string excludes uncategorized sessions. ``None`` or an empty
                set excludes nothing.
            has_project (bool, optional): When true, keep only sessions whose
                ``project_workspace`` is non-empty. Defaults to ``False``, which
                keeps every session.
            since (datetime, optional): Inclusive lower bound on ``create_time``.
                ``None`` applies no lower bound.
            until (datetime, optional): Inclusive upper bound on ``create_time``.
                ``None`` applies no upper bound.

        Returns:
            list[SessionData]: A list of SessionData instances matching the query.
                Returns an empty list if no sessions match.

        Raises:
            NotImplementedError: This is an abstract method that must be
                implemented by concrete storage classes.
        """
        raise NotImplementedError

    def count_sessions(self, sessions: list[str] = None, category: str = None,
                       included_categories: set[str] = None,
                       excluded_categories: set[str] = None,
                       has_project: bool = False, since: datetime = None,
                       until: datetime = None) -> int:
        """Return the number of sessions matching the selection filters."""
        raise NotImplementedError

    def delete_session(self, session_id: str):
        """
        Delete a session and its associated chat history.

        Args:
            session_id (str): The session id to delete.

        Raises:
            Exception: If the session does not exist or deletion fails.
        """
        raise NotImplementedError

    def update_session_name(self, session_id: str, session_name: str) -> bool:
        """
        Update the name of an existing session.

        Args:
            session_id (str): The session id to update.
            session_name (str): The new session name.

        Returns:
            bool: True if the session name was updated successfully,
                  False if the session does not exist or the update failed.

        Raises:
            NotImplementedError: This is an abstract method that must be
                implemented by concrete storage classes.
        """
        raise NotImplementedError
    def accumulate_session_tokens(
        self,
        session_id: str,
        current_tokens: int,
        current_cached_tokens: int,
        current_completion_tokens: int = 0,
    ) -> bool:
        """Atomically add one request's prompt, completion, and cache deltas.

        ``current_tokens`` remains prompt-only for backward compatibility.
        Callers must pass current-request deltas rather than agent-level totals so
        multiple agents can safely contribute to the same session.

        Args:
            session_id (str): The session identifier whose totals should be updated.
            current_tokens (int): Prompt tokens to add to legacy ``total_tokens``.
            current_cached_tokens (int): Cached prompt tokens to add.
            current_completion_tokens (int): Completion tokens to add.

        Returns:
            bool: True if the session existed and was updated, False otherwise.

        Raises:
            NotImplementedError: Concrete storage classes must implement this API.
        """
        raise NotImplementedError

    def accumulate_session_metrics(
        self,
        session_id: str,
        turn_count: int = 0,
        tool_call_count: int = 0,
        tool_error_count: int = 0,
        llm_request_count: int = 0,
        llm_request_failure_count: int = 0,
        tool_duration_ms_sum: int = 0,
        llm_request_duration_ms_sum: int = 0,
        summary_count: int = 0,
    ) -> bool:
        """Atomically add one settled attempt's execution metric deltas.

        Callers must pass per-attempt deltas rather than agent-level totals so
        multiple agents can safely contribute to the same session. Negative
        values are normalized to zero so misreported deltas cannot subtract.

        Args:
            session_id (str): The session identifier whose metrics should be updated.
            summary_count (int): Successfully applied summaries to add.
            turn_count (int): Settled turns to add.
            tool_call_count (int): Measured tool calls to add.
            tool_error_count (int): Tool calls that reported an error to add.
            llm_request_count (int): LLM requests attempted to add.
            llm_request_failure_count (int): Failed LLM requests to add.
            tool_duration_ms_sum (int): Tool duration milliseconds to add.
            llm_request_duration_ms_sum (int): LLM request duration milliseconds to add.

        Returns:
            bool: True if the session existed and was updated, False otherwise.

        Raises:
            NotImplementedError: Concrete storage classes must implement this API.
        """
        raise NotImplementedError

    def get_session_token_totals(self, session_id: str) -> tuple[int, int] | None:
        """Retrieve legacy prompt and cached-prompt totals for a session.

        Returns:
            tuple[int, int] | None: ``(prompt_tokens, cached_prompt_tokens)`` when
                the session exists, otherwise ``None``.
        """
        raise NotImplementedError

    def get_session_token_usage(self, session_id: str) -> dict[str, int] | None:
        """Retrieve explicit prompt, completion, combined, and cache totals.

        Returns:
            dict[str, int] | None: Explicit token metrics when the session exists,
                otherwise ``None``.
        """
        raise NotImplementedError



    def retrieve_messages(self, session_id:str) -> list[dict]:
        """ retrieve messages by chat_history_manager """
        raise NotImplementedError

    def clean_sessions(self, before_seconds: int):
        """
        Delete sessions that were created before the specified number of seconds ago.

        Args:
            before_seconds (int): Delete sessions older than this many seconds from current time.

        Returns:
            int: Number of sessions deleted.
        """
        raise NotImplementedError

    def get_messages_by_session(self, session_id:str) -> list[ChatHistoryMessageData]:
        """ get messages by chat_history_manager """
        raise NotImplementedError
