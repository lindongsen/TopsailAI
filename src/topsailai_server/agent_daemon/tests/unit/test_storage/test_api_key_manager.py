"""
Unit tests for ApiKeySQLAlchemy storage implementation.

Tests CRUD operations, session binding, rate limiting,
and permission checks for API key storage.

Author: km2
Created: 2026-05-04
"""

import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine

from topsailai_server.agent_daemon.storage.api_key_manager.base import (
    ApiKeyData,
    ApiKeySessionData,
    RateLimitLogData,
)
from topsailai_server.agent_daemon.storage.api_key_manager.sql import (
    ApiKeySQLAlchemy,
    ApiKey,
    ApiKeySession,
    RateLimitLog,
)


class TestApiKeySQLAlchemyInit:
    """Tests for ApiKeySQLAlchemy initialization."""

    def test_init_creates_tables(self):
        """Test that initialization creates all three tables."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        from sqlalchemy import inspect
        inspector = inspect(engine)
        tables = inspector.get_table_names()

        assert "api_key" in tables
        assert "api_key_session" in tables
        assert "rate_limit_log" in tables


class TestApiKeySQLAlchemyCreate:
    """Tests for ApiKeySQLAlchemy create operation."""

    def test_create_api_key_success(self):
        """Test successful API key creation."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        key_data = ApiKeyData(
            api_key_id="key_001",
            api_key="secret_key_001",
            name="Test Key",
            role="user",
            rate_limit=60,
        )

        result = storage.create_api_key(key_data)

        assert result is True
        created = storage.get_api_key_by_id("key_001")
        assert created is not None
        assert created.api_key_id == "key_001"
        assert created.api_key == "secret_key_001"
        assert created.name == "Test Key"
        assert created.role == "user"
        assert created.rate_limit == 60
        assert created.is_active is True

    def test_create_api_key_with_timestamps(self):
        """Test API key creation with custom timestamps."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        now = datetime.now()
        key_data = ApiKeyData(
            api_key_id="key_002",
            api_key="secret_key_002",
            name="Timestamp Key",
            create_time=now,
            update_time=now,
        )

        storage.create_api_key(key_data)
        created = storage.get_api_key_by_id("key_002")

        assert created.create_time == now
        assert created.update_time == now

    def test_create_duplicate_api_key_returns_false(self):
        """Test creating a duplicate API key returns False."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        key1 = ApiKeyData(api_key_id="dup_001", api_key="secret1", name="First")
        key2 = ApiKeyData(api_key_id="dup_001", api_key="secret2", name="Second")

        storage.create_api_key(key1)
        result = storage.create_api_key(key2)

        assert result is False


class TestApiKeySQLAlchemyGet:
    """Tests for ApiKeySQLAlchemy get operations."""

    def test_get_api_key_by_id_existing(self):
        """Test getting an existing API key by ID."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        key_data = ApiKeyData(
            api_key_id="get_id_001",
            api_key="secret_get_001",
            name="Get By ID Test",
        )
        storage.create_api_key(key_data)

        result = storage.get_api_key_by_id("get_id_001")

        assert result is not None
        assert result.api_key_id == "get_id_001"
        assert result.name == "Get By ID Test"

    def test_get_api_key_by_id_nonexistent(self):
        """Test getting a non-existent API key by ID."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        result = storage.get_api_key_by_id("nonexistent")

        assert result is None

    def test_get_api_key_by_value_existing(self):
        """Test getting an existing API key by value."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        key_data = ApiKeyData(
            api_key_id="get_val_001",
            api_key="secret_val_001",
            name="Get By Value Test",
        )
        storage.create_api_key(key_data)

        result = storage.get_api_key_by_value("secret_val_001")

        assert result is not None
        assert result.api_key_id == "get_val_001"
        assert result.api_key == "secret_val_001"

    def test_get_api_key_by_value_nonexistent(self):
        """Test getting a non-existent API key by value."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        result = storage.get_api_key_by_value("nonexistent_secret")

        assert result is None

    def test_get_api_key_by_value_inactive(self):
        """Test that inactive API keys are not returned by value lookup."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        key_data = ApiKeyData(
            api_key_id="inactive_001",
            api_key="secret_inactive",
            name="Inactive Key",
            is_active=False,
        )
        storage.create_api_key(key_data)

        result = storage.get_api_key_by_value("secret_inactive")

        assert result is None

    def test_get_api_key_by_id_returns_inactive(self):
        """Test that get by ID returns inactive keys."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        key_data = ApiKeyData(
            api_key_id="inactive_id_001",
            api_key="secret_inactive_id",
            name="Inactive Key",
            is_active=False,
        )
        storage.create_api_key(key_data)

        result = storage.get_api_key_by_id("inactive_id_001")

        assert result is not None
        assert result.is_active is False


class TestApiKeySQLAlchemyList:
    """Tests for ApiKeySQLAlchemy list operation."""

    def test_list_api_keys_basic(self):
        """Test basic list API keys."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        for i in range(3):
            storage.create_api_key(ApiKeyData(
                api_key_id=f"list_{i}",
                api_key=f"secret_list_{i}",
                name=f"Key {i}",
            ))

        result = storage.list_api_keys()

        assert len(result) == 3

    def test_list_api_keys_empty(self):
        """Test listing API keys when none exist."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        result = storage.list_api_keys()

        assert len(result) == 0

    def test_list_api_keys_sorted_by_create_time_desc(self):
        """Test that list returns keys sorted by create_time desc."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        now = datetime.now()
        for i in range(3):
            storage.create_api_key(ApiKeyData(
                api_key_id=f"sort_{i}",
                api_key=f"secret_sort_{i}",
                name=f"Key {i}",
                create_time=now - timedelta(hours=i),
            ))

        result = storage.list_api_keys()

        assert len(result) == 3
        # First result should be the most recent (sort_0)
        assert result[0].api_key_id == "sort_0"


class TestApiKeySQLAlchemyUpdate:
    """Tests for ApiKeySQLAlchemy update operation."""

    def test_update_api_key_success(self):
        """Test successful API key update."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        storage.create_api_key(ApiKeyData(
            api_key_id="update_001",
            api_key="secret_update_001",
            name="Original Name",
            role="user",
            rate_limit=60,
        ))

        updated_data = ApiKeyData(
            api_key_id="update_001",
            api_key="secret_update_001",
            name="Updated Name",
            role="admin",
            rate_limit=0,
        )
        result = storage.update_api_key(updated_data)

        assert result is True
        updated = storage.get_api_key_by_id("update_001")
        assert updated.name == "Updated Name"
        assert updated.role == "admin"
        assert updated.rate_limit == 0

    def test_update_nonexistent_api_key(self):
        """Test updating a non-existent API key."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        key_data = ApiKeyData(
            api_key_id="nonexistent",
            api_key="secret",
            name="Test",
        )
        result = storage.update_api_key(key_data)

        assert result is False


class TestApiKeySQLAlchemyDelete:
    """Tests for ApiKeySQLAlchemy delete operation."""

    def test_delete_existing_api_key(self):
        """Test deleting an existing API key."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        storage.create_api_key(ApiKeyData(
            api_key_id="delete_001",
            api_key="secret_delete_001",
            name="Delete Test",
        ))

        result = storage.delete_api_key("delete_001")

        assert result is True
        assert storage.get_api_key_by_id("delete_001") is None

    def test_delete_nonexistent_api_key(self):
        """Test deleting a non-existent API key."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        result = storage.delete_api_key("nonexistent")

        assert result is False

    def test_delete_api_key_cleans_bindings(self):
        """Test that deleting an API key also removes session bindings."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        storage.create_api_key(ApiKeyData(
            api_key_id="del_bind_001",
            api_key="secret_del_bind",
            name="Delete Bind Test",
        ))
        storage.bind_sessions("del_bind_001", ["session_001", "session_002"])

        storage.delete_api_key("del_bind_001")

        bound = storage.get_bound_sessions("del_bind_001")
        assert len(bound) == 0

    def test_delete_api_key_cleans_rate_limit_logs(self):
        """Test that deleting an API key also removes rate limit logs."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        storage.create_api_key(ApiKeyData(
            api_key_id="del_log_001",
            api_key="secret_del_log",
            name="Delete Log Test",
        ))
        storage.log_rate_limit("del_log_001", "session_001", "receive_message")

        storage.delete_api_key("del_log_001")

        count = storage.count_rate_limit(
            "del_log_001", "receive_message", datetime.now() - timedelta(hours=1)
        )
        assert count == 0


class TestApiKeySQLAlchemyCount:
    """Tests for ApiKeySQLAlchemy count operation."""

    def test_count_api_keys(self):
        """Test counting API keys."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        assert storage.count_api_keys() == 0

        for i in range(3):
            storage.create_api_key(ApiKeyData(
                api_key_id=f"count_{i}",
                api_key=f"secret_count_{i}",
                name=f"Key {i}",
            ))

        assert storage.count_api_keys() == 3


class TestApiKeySQLAlchemyBindSessions:
    """Tests for ApiKeySQLAlchemy session binding operations."""

    def test_bind_sessions_success(self):
        """Test successful session binding."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        storage.create_api_key(ApiKeyData(
            api_key_id="bind_001",
            api_key="secret_bind_001",
            name="Bind Test",
        ))

        result = storage.bind_sessions("bind_001", ["session_001", "session_002"])

        assert result is True
        bound = storage.get_bound_sessions("bind_001")
        assert len(bound) == 2
        assert "session_001" in bound
        assert "session_002" in bound

    def test_bind_duplicate_sessions(self):
        """Test binding duplicate sessions does not create duplicates."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        storage.create_api_key(ApiKeyData(
            api_key_id="bind_dup_001",
            api_key="secret_bind_dup",
            name="Bind Dup Test",
        ))

        storage.bind_sessions("bind_dup_001", ["session_001"])
        storage.bind_sessions("bind_dup_001", ["session_001", "session_002"])

        bound = storage.get_bound_sessions("bind_dup_001")
        assert len(bound) == 2

    def test_unbind_sessions_success(self):
        """Test successful session unbinding."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        storage.create_api_key(ApiKeyData(
            api_key_id="unbind_001",
            api_key="secret_unbind_001",
            name="Unbind Test",
        ))
        storage.bind_sessions("unbind_001", ["session_001", "session_002", "session_003"])

        result = storage.unbind_sessions("unbind_001", ["session_001", "session_002"])

        assert result is True
        bound = storage.get_bound_sessions("unbind_001")
        assert len(bound) == 1
        assert "session_003" in bound

    def test_unbind_nonexistent_sessions(self):
        """Test unbinding sessions that are not bound."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        storage.create_api_key(ApiKeyData(
            api_key_id="unbind_none_001",
            api_key="secret_unbind_none",
            name="Unbind None Test",
        ))

        result = storage.unbind_sessions("unbind_none_001", ["session_001"])

        assert result is True

    def test_get_bound_sessions_empty(self):
        """Test getting bound sessions for key with no bindings."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        storage.create_api_key(ApiKeyData(
            api_key_id="empty_bind_001",
            api_key="secret_empty_bind",
            name="Empty Bind Test",
        ))

        result = storage.get_bound_sessions("empty_bind_001")

        assert len(result) == 0

    def test_is_session_bound_true(self):
        """Test checking if a bound session is bound."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        storage.create_api_key(ApiKeyData(
            api_key_id="is_bound_001",
            api_key="secret_is_bound",
            name="Is Bound Test",
        ))
        storage.bind_sessions("is_bound_001", ["session_001"])

        result = storage.is_session_bound("is_bound_001", "session_001")

        assert result is True

    def test_is_session_bound_false(self):
        """Test checking if an unbound session is bound."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        storage.create_api_key(ApiKeyData(
            api_key_id="is_not_bound_001",
            api_key="secret_is_not_bound",
            name="Is Not Bound Test",
        ))
        storage.bind_sessions("is_not_bound_001", ["session_001"])

        result = storage.is_session_bound("is_not_bound_001", "session_002")

        assert result is False


class TestApiKeySQLAlchemyRateLimit:
    """Tests for ApiKeySQLAlchemy rate limit operations."""

    def test_log_rate_limit_success(self):
        """Test successful rate limit logging."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        storage.create_api_key(ApiKeyData(
            api_key_id="rate_001",
            api_key="secret_rate_001",
            name="Rate Limit Test",
        ))

        result = storage.log_rate_limit("rate_001", "session_001", "receive_message")

        assert result is True

    def test_count_rate_limit(self):
        """Test counting rate limit entries."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        storage.create_api_key(ApiKeyData(
            api_key_id="count_rate_001",
            api_key="secret_count_rate",
            name="Count Rate Test",
        ))

        now = datetime.now()
        # Log 3 entries
        for i in range(3):
            storage.log_rate_limit("count_rate_001", "session_001", "receive_message")

        count = storage.count_rate_limit(
            "count_rate_001",
            "receive_message",
            now - timedelta(minutes=1),
        )

        assert count == 3

    def test_count_rate_limit_with_time_filter(self):
        """Test counting rate limit entries with time filter."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        storage.create_api_key(ApiKeyData(
            api_key_id="count_time_001",
            api_key="secret_count_time",
            name="Count Time Test",
        ))

        now = datetime.now()
        # Log an entry
        storage.log_rate_limit("count_time_001", "session_001", "receive_message")

        # Count with recent cutoff should include the entry
        count_recent = storage.count_rate_limit(
            "count_time_001",
            "receive_message",
            now - timedelta(minutes=1),
        )
        assert count_recent == 1

        # Count with future cutoff should exclude the entry
        count_future = storage.count_rate_limit(
            "count_time_001",
            "receive_message",
            now + timedelta(minutes=1),
        )
        assert count_future == 0

    def test_count_rate_limit_different_actions(self):
        """Test that rate limit counts are separated by action."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        storage.create_api_key(ApiKeyData(
            api_key_id="count_action_001",
            api_key="secret_count_action",
            name="Count Action Test",
        ))

        now = datetime.now()
        storage.log_rate_limit("count_action_001", "session_001", "receive_message")
        storage.log_rate_limit("count_action_001", "session_001", "other_action")

        count_msg = storage.count_rate_limit(
            "count_action_001",
            "receive_message",
            now - timedelta(minutes=1),
        )
        count_other = storage.count_rate_limit(
            "count_action_001",
            "other_action",
            now - timedelta(minutes=1),
        )

        assert count_msg == 1
        assert count_other == 1


class TestApiKeySQLAlchemyCleanRateLimitLogs:
    """Tests for ApiKeySQLAlchemy clean_rate_limit_logs operation."""

    def test_clean_rate_limit_logs(self):
        """Test cleaning old rate limit logs."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        storage.create_api_key(ApiKeyData(
            api_key_id="clean_001",
            api_key="secret_clean_001",
            name="Clean Test",
        ))

        # Log some entries
        for i in range(3):
            storage.log_rate_limit("clean_001", "session_001", "receive_message")

        now = datetime.now()
        # Clean logs older than 1 hour (should not delete recent logs)
        deleted = storage.clean_rate_limit_logs(now - timedelta(hours=1))

        assert deleted == 0

        # Clean logs newer than 1 hour in the future (should delete all)
        deleted = storage.clean_rate_limit_logs(now + timedelta(hours=1))

        assert deleted == 3

        # Verify all logs are gone
        count = storage.count_rate_limit(
            "clean_001", "receive_message", now - timedelta(hours=1)
        )
        assert count == 0

    def test_clean_rate_limit_logs_empty(self):
        """Test cleaning when no logs exist."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        deleted = storage.clean_rate_limit_logs(datetime.now())

        assert deleted == 0


class TestApiKeySQLAlchemyEdgeCases:
    """Tests for edge cases and error handling."""

    def test_create_api_key_with_admin_role(self):
        """Test creating an API key with admin role."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        key_data = ApiKeyData(
            api_key_id="admin_001",
            api_key="secret_admin_001",
            name="Admin Key",
            role="admin",
            rate_limit=0,
        )

        storage.create_api_key(key_data)
        created = storage.get_api_key_by_id("admin_001")

        assert created.role == "admin"
        assert created.rate_limit == 0

    def test_multiple_keys_same_session(self):
        """Test that multiple API keys can bind to the same session."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        storage.create_api_key(ApiKeyData(
            api_key_id="multi_001",
            api_key="secret_multi_001",
            name="Key 1",
        ))
        storage.create_api_key(ApiKeyData(
            api_key_id="multi_002",
            api_key="secret_multi_002",
            name="Key 2",
        ))

        storage.bind_sessions("multi_001", ["shared_session"])
        storage.bind_sessions("multi_002", ["shared_session"])

        assert storage.is_session_bound("multi_001", "shared_session") is True
        assert storage.is_session_bound("multi_002", "shared_session") is True

    def test_unbind_all_sessions(self):
        """Test unbinding all sessions from an API key."""
        engine = create_engine("sqlite:///:memory:")
        storage = ApiKeySQLAlchemy(engine)

        storage.create_api_key(ApiKeyData(
            api_key_id="unbind_all_001",
            api_key="secret_unbind_all",
            name="Unbind All Test",
        ))
        storage.bind_sessions("unbind_all_001", ["session_001", "session_002"])

        storage.unbind_sessions("unbind_all_001", ["session_001", "session_002"])

        bound = storage.get_bound_sessions("unbind_all_001")
        assert len(bound) == 0
