"""
Unit tests for SessionSQLAlchemy storage implementation.

Tests CRUD operations, filtering, sorting, and pagination for session storage.

Author: mm-m25
Created: 2026-04-17
"""

import pytest
from datetime import datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from topsailai_server.agent_daemon.storage.session_manager.base import SessionData
from topsailai_server.agent_daemon.storage.session_manager.sql import SessionSQLAlchemy, Session


class TestSessionSQLAlchemyInit:
    """Tests for SessionSQLAlchemy initialization."""

    def test_init_creates_tables(self):
        """Test that initialization creates the session table."""
        engine = create_engine("sqlite:///:memory:")
        storage = SessionSQLAlchemy(engine)

        # Verify table exists
        from sqlalchemy import inspect
        inspector = inspect(engine)
        tables = inspector.get_table_names()

        assert "session" in tables

    def test_get_engine(self):
        """Test that get_engine returns the correct engine."""
        engine = create_engine("sqlite:///:memory:")
        storage = SessionSQLAlchemy(engine)

        assert storage.get_engine() == engine


class TestSessionSQLAlchemyCreate:
    """Tests for SessionSQLAlchemy create operation."""

    def test_create_session_success(self):
        """Test successful session creation."""
        engine = create_engine("sqlite:///:memory:")
        storage = SessionSQLAlchemy(engine)

        session_data = SessionData(
            session_id="test_001",
            task="Test task",
            session_name="Test Session"
        )

        result = storage.create(session_data)

        assert result is True
        # Verify session was created
        created = storage.get("test_001")
        assert created is not None
        assert created.session_id == "test_001"
        assert created.task == "Test task"
        assert created.session_name == "Test Session"

    def test_create_session_with_timestamps(self):
        """Test session creation with custom timestamps."""
        engine = create_engine("sqlite:///:memory:")
        storage = SessionSQLAlchemy(engine)

        now = datetime.now()
        session_data = SessionData(
            session_id="test_002",
            task="Timestamp test",
            create_time=now,
            update_time=now
        )

        storage.create(session_data)
        created = storage.get("test_002")

        assert created.create_time == now
        assert created.update_time == now

    def test_create_duplicate_session_fails(self):
        """Test creating a duplicate session fails due to primary key constraint."""
        engine = create_engine("sqlite:///:memory:")
        storage = SessionSQLAlchemy(engine)

        session1 = SessionData(session_id="dup_001", task="First task")
        session2 = SessionData(session_id="dup_001", task="Second task")

        storage.create(session1)

        # Creating a duplicate should fail due to primary key constraint
        with pytest.raises(Exception):
            storage.create(session2)


class TestSessionSQLAlchemyGet:
    """Tests for SessionSQLAlchemy get operations."""

    def test_get_existing_session(self):
        """Test getting an existing session."""
        engine = create_engine("sqlite:///:memory:")
        storage = SessionSQLAlchemy(engine)

        session_data = SessionData(
            session_id="get_001",
            task="Get test",
            session_name="Get Session"
        )
        storage.create(session_data)

        result = storage.get("get_001")

        assert result is not None
        assert result.session_id == "get_001"
        assert result.task == "Get test"

    def test_get_nonexistent_session(self):
        """Test getting a non-existent session."""
        engine = create_engine("sqlite:///:memory:")
        storage = SessionSQLAlchemy(engine)

        result = storage.get("nonexistent")

        assert result is None

    def test_get_all_sessions(self):
        """Test getting all sessions."""
        engine = create_engine("sqlite:///:memory:")
        storage = SessionSQLAlchemy(engine)

        for i in range(3):
            storage.create(SessionData(session_id=f"all_{i}", task=f"Task {i}"))

        result = storage.get_all()

        assert len(result) == 3


class TestSessionSQLAlchemyUpdate:
    """Tests for SessionSQLAlchemy update operations."""

    def test_update_session_success(self):
        """Test successful session update."""
        engine = create_engine("sqlite:///:memory:")
        storage = SessionSQLAlchemy(engine)

        # Create session
        session_data = SessionData(
            session_id="update_001",
            task="Original task",
            session_name="Original name"
        )
        storage.create(session_data)

        # Update session
        updated_data = SessionData(
            session_id="update_001",
            task="Updated task",
            session_name="Updated name"
        )
        result = storage.update(updated_data)

        assert result is True
        updated = storage.get("update_001")
        assert updated.task == "Updated task"
        assert updated.session_name == "Updated name"

    def test_update_nonexistent_session(self):
        """Test updating a non-existent session."""
        engine = create_engine("sqlite:///:memory:")
        storage = SessionSQLAlchemy(engine)

        session_data = SessionData(session_id="nonexistent", task="Test")
        result = storage.update(session_data)

        assert result is False

    def test_update_processed_msg_id(self):
        """Test updating processed_msg_id."""
        engine = create_engine("sqlite:///:memory:")
        storage = SessionSQLAlchemy(engine)

        storage.create(SessionData(session_id="msg_update", task="Test"))

        result = storage.update_processed_msg_id("msg_update", "msg_123")

        assert result is True
        updated = storage.get("msg_update")
        assert updated.processed_msg_id == "msg_123"


class TestSessionSQLAlchemyDelete:
    """Tests for SessionSQLAlchemy delete operations."""

    def test_delete_existing_session(self):
        """Test deleting an existing session."""
        engine = create_engine("sqlite:///:memory:")
        storage = SessionSQLAlchemy(engine)

        storage.create(SessionData(session_id="delete_001", task="Delete test"))

        result = storage.delete("delete_001")

        assert result is True
        assert storage.get("delete_001") is None

    def test_delete_nonexistent_session(self):
        """Test deleting a non-existent session."""
        engine = create_engine("sqlite:///:memory:")
        storage = SessionSQLAlchemy(engine)

        result = storage.delete("nonexistent")

        assert result is False


class TestSessionSQLAlchemyGetOrCreate:
    """Tests for SessionSQLAlchemy get_or_create operation."""

    def test_get_existing_session(self):
        """Test get_or_create returns existing session."""
        engine = create_engine("sqlite:///:memory:")
        storage = SessionSQLAlchemy(engine)

        # Create session first
        storage.create(SessionData(
            session_id="get_or_create_001",
            task="Original task",
            session_name="Original"
        ))

        # get_or_create should return existing
        result = storage.get_or_create(
            session_id="get_or_create_001",
            session_name="New name",
            task="New task"
        )

        assert result.session_id == "get_or_create_001"
        assert result.task == "Original task"  # Should not be updated

    def test_create_new_session(self):
        """Test get_or_create creates new session."""
        engine = create_engine("sqlite:///:memory:")
        storage = SessionSQLAlchemy(engine)

        result = storage.get_or_create(
            session_id="new_session",
            session_name="New Session",
            task="New task"
        )

        assert result is not None
        assert result.session_id == "new_session"
        assert result.session_name == "New Session"
        assert result.task == "New task"


class TestSessionSQLAlchemyList:
    """Tests for SessionSQLAlchemy list operation with filtering and pagination."""

    def test_list_sessions_basic(self):
        """Test basic list sessions."""
        engine = create_engine("sqlite:///:memory:")
        storage = SessionSQLAlchemy(engine)

        for i in range(5):
            storage.create(SessionData(session_id=f"list_{i}", task=f"Task {i}"))

        result = storage.list_sessions()

        assert len(result) == 5

    def test_list_sessions_with_session_ids_filter(self):
        """Test list sessions with session_ids filter."""
        engine = create_engine("sqlite:///:memory:")
        storage = SessionSQLAlchemy(engine)

        for i in range(5):
            storage.create(SessionData(session_id=f"filter_{i}", task=f"Task {i}"))

        result = storage.list_sessions(session_ids=["filter_0", "filter_2"])

        assert len(result) == 2
        session_ids = [s.session_id for s in result]
        assert "filter_0" in session_ids
        assert "filter_2" in session_ids

    def test_list_sessions_with_time_filter(self):
        """Test list sessions with time range filter."""
        engine = create_engine("sqlite:///:memory:")
        storage = SessionSQLAlchemy(engine)

        now = datetime.now()
        # Create sessions with different times
        for i in range(3):
            storage.create(SessionData(
                session_id=f"time_{i}",
                task=f"Task {i}",
                create_time=now - timedelta(days=i)
            ))

        # Filter for last 2 days
        result = storage.list_sessions(
            start_time=now - timedelta(days=2)
        )

        assert len(result) >= 2

    def test_list_sessions_pagination(self):
        """Test list sessions with pagination."""
        engine = create_engine("sqlite:///:memory:")
        storage = SessionSQLAlchemy(engine)

        for i in range(10):
            storage.create(SessionData(session_id=f"page_{i}", task=f"Task {i}"))

        # Get first page
        page1 = storage.list_sessions(offset=0, limit=3)
        assert len(page1) == 3

        # Get second page
        page2 = storage.list_sessions(offset=3, limit=3)
        assert len(page2) == 3

        # Verify no overlap
        page1_ids = set(s.session_id for s in page1)
        page2_ids = set(s.session_id for s in page2)
        assert page1_ids.isdisjoint(page2_ids)

    def test_list_sessions_sort_order(self):
        """Test list sessions with different sort orders."""
        engine = create_engine("sqlite:///:memory:")
        storage = SessionSQLAlchemy(engine)

        now = datetime.now()
        for i in range(3):
            storage.create(SessionData(
                session_id=f"sort_{i}",
                task=f"Task {i}",
                create_time=now - timedelta(hours=i)
            ))

        # Sort ascending
        asc_result = storage.list_sessions(order_by="asc")
        assert len(asc_result) == 3

        # Sort descending
        desc_result = storage.list_sessions(order_by="desc")
        assert len(desc_result) == 3


class TestSessionSQLAlchemyCleanup:
    """Tests for SessionSQLAlchemy cleanup operations."""

    def test_get_sessions_before(self):
        """Test getting sessions updated before a time."""
        engine = create_engine("sqlite:///:memory:")
        storage = SessionSQLAlchemy(engine)

        now = datetime.now()
        # Create old session
        storage.create(SessionData(
            session_id="old_session",
            task="Old task",
            create_time=now - timedelta(days=30),
            update_time=now - timedelta(days=30)
        ))

        # Create recent session
        storage.create(SessionData(
            session_id="recent_session",
            task="Recent task",
            create_time=now,
            update_time=now
        ))

        # Get sessions before now
        result = storage.get_sessions_before(now - timedelta(days=7))

        assert len(result) >= 1
        assert any(s.session_id == "old_session" for s in result)

    def test_get_sessions_older_than(self):
        """Test getting sessions older than a cutoff date."""
        engine = create_engine("sqlite:///:memory:")
        storage = SessionSQLAlchemy(engine)

        now = datetime.now()
        # Create old session (1 year ago)
        storage.create(SessionData(
            session_id="old_year",
            task="Old task",
            create_time=now - timedelta(days=400),
            update_time=now - timedelta(days=400)
        ))

        # Create recent session
        storage.create(SessionData(
            session_id="recent_year",
            task="Recent task",
            create_time=now,
            update_time=now
        ))

        # Get sessions older than 1 year
        cutoff = now - timedelta(days=365)
        result = storage.get_sessions_older_than(cutoff)

        assert len(result) >= 1
        assert any(s.session_id == "old_year" for s in result)


class TestSessionSQLAlchemyIndexes:
    """Tests for SessionSQLAlchemy index verification."""

    def test_verify_indexes(self):
        """Test index verification."""
        engine = create_engine("sqlite:///:memory:")
        storage = SessionSQLAlchemy(engine)

        result = storage.verify_indexes()

        assert isinstance(result, dict)
        assert "idx_session_update_create_time" in result
        assert "ix_session_processed_msg_id" in result
