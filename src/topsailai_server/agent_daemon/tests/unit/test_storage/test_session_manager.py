'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-12
  Purpose: Unit tests for Session Manager
'''

import unittest
import os
from datetime import datetime, timedelta

# Set test environment variables before imports
os.environ['TOPSAILAI_AGENT_DAEMON_PROCESSOR'] = '/bin/echo'
os.environ['TOPSAILAI_AGENT_DAEMON_SUMMARIZER'] = '/bin/echo'
os.environ['TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER'] = '/bin/echo'

from sqlalchemy import create_engine

from topsailai_server.agent_daemon.storage.session_manager.sql import SessionSQLAlchemy
from topsailai_server.agent_daemon.storage.session_manager.base import SessionData


def _create_session_data(session_id, session_name=None, task=None,
                          create_time=None, update_time=None,
                          processed_msg_id=None):
    """Helper function to create SessionData with defaults."""
    now = datetime.now()
    return SessionData(
        session_id=session_id,
        session_name=session_name or f'Session {session_id}',
        task=task or f'Task for {session_id}',
        create_time=create_time or now,
        update_time=update_time or now,
        processed_msg_id=processed_msg_id
    )


def _make_fresh_manager():
    """Create a fresh SessionSQLAlchemy with in-memory DB for isolated tests."""
    engine = create_engine('sqlite:///:memory:')
    return SessionSQLAlchemy(engine)


class TestSessionManager(unittest.TestCase):
    """Test cases for Session Manager"""

    @classmethod
    def setUpClass(cls):
        """Set up shared test fixtures"""
        cls.engine = create_engine('sqlite:///:memory:')
        cls.session_manager = SessionSQLAlchemy(cls.engine)

    # ============================================================
    # Original tests
    # ============================================================

    def test_create_session(self):
        """Test creating a new session"""
        session_data = SessionData(
            session_id='test-session-1',
            session_name='Test Session',
            task='Test task',
            create_time=datetime.now(),
            update_time=datetime.now(),
            processed_msg_id=None
        )
        result = self.session_manager.create(session_data)
        self.assertTrue(result)
        retrieved = self.session_manager.get('test-session-1')
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.session_id, 'test-session-1')
        self.assertEqual(retrieved.session_name, 'Test Session')

    def test_get_session(self):
        """Test retrieving a session"""
        session_data = SessionData(
            session_id='test-session-2',
            session_name='Test Session 2',
            task='Test task 2',
            create_time=datetime.now(),
            update_time=datetime.now(),
            processed_msg_id=None
        )
        self.session_manager.create(session_data)
        retrieved = self.session_manager.get('test-session-2')
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.session_id, 'test-session-2')

    def test_update_session(self):
        """Test updating a session"""
        session_data = SessionData(
            session_id='test-session-3',
            session_name='Original Name',
            task='Original task',
            create_time=datetime.now(),
            update_time=datetime.now(),
            processed_msg_id=None
        )
        self.session_manager.create(session_data)
        session_data.session_name = 'Updated Name'
        session_data.task = 'Updated task'
        result = self.session_manager.update(session_data)
        self.assertTrue(result)
        retrieved = self.session_manager.get('test-session-3')
        self.assertEqual(retrieved.session_name, 'Updated Name')
        self.assertEqual(retrieved.task, 'Updated task')

    def test_update_processed_msg_id(self):
        """Test updating processed_msg_id"""
        session_data = SessionData(
            session_id='test-session-4',
            session_name='Test Session 4',
            task='Test task 4',
            create_time=datetime.now(),
            update_time=datetime.now(),
            processed_msg_id=None
        )
        self.session_manager.create(session_data)
        result = self.session_manager.update_processed_msg_id('test-session-4', 'msg-123')
        self.assertTrue(result)
        retrieved = self.session_manager.get('test-session-4')
        self.assertEqual(retrieved.processed_msg_id, 'msg-123')

    def test_delete_session(self):
        """Test deleting a session"""
        session_data = SessionData(
            session_id='test-session-5',
            session_name='Test Session 5',
            task='Test task 5',
            create_time=datetime.now(),
            update_time=datetime.now(),
            processed_msg_id=None
        )
        self.session_manager.create(session_data)
        result = self.session_manager.delete('test-session-5')
        self.assertTrue(result)
        retrieved = self.session_manager.get('test-session-5')
        self.assertIsNone(retrieved)

    def test_get_or_create(self):
        """Test get_or_create method"""
        session = self.session_manager.get_or_create('test-session-6', 'New Session', 'New task')
        self.assertEqual(session.session_id, 'test-session-6')
        self.assertEqual(session.session_name, 'New Session')
        existing = self.session_manager.get_or_create('test-session-6', 'Different Name', 'Different task')
        self.assertEqual(existing.session_id, 'test-session-6')
        self.assertEqual(existing.session_name, 'New Session')

    def test_get_sessions_older_than(self):
        """Test getting sessions older than a date"""
        old_time = datetime.now() - timedelta(days=400)
        session_data = SessionData(
            session_id='old-session',
            session_name='Old Session',
            task='Old task',
            create_time=old_time,
            update_time=old_time,
            processed_msg_id=None
        )
        self.session_manager.create(session_data)
        recent_session = SessionData(
            session_id='recent-session',
            session_name='Recent Session',
            task='Recent task',
            create_time=datetime.now(),
            update_time=datetime.now(),
            processed_msg_id=None
        )
        self.session_manager.create(recent_session)
        cutoff = datetime.now() - timedelta(days=365)
        old_sessions = self.session_manager.get_sessions_older_than(cutoff)
        session_ids = [s.session_id for s in old_sessions]
        self.assertIn('old-session', session_ids)
        self.assertNotIn('recent-session', session_ids)

    # ============================================================
    # New tests for list_sessions
    # ============================================================

    def test_list_sessions_default_pagination(self):
        """Test list_sessions with default pagination returns all sessions sorted desc."""
        mgr = _make_fresh_manager()
        base = datetime(2026, 1, 1, 0, 0, 0)
        for i in range(5):
            mgr.create(_create_session_data(
                session_id=f'ls-default-{i}',
                create_time=base + timedelta(hours=i),
                update_time=base + timedelta(hours=i)
            ))
        results = mgr.list_sessions()
        self.assertEqual(len(results), 5)
        # Default desc order: newest first
        self.assertEqual(results[0].session_id, 'ls-default-4')

    def test_list_sessions_pagination_offset(self):
        """Test list_sessions with offset skips first N results."""
        mgr = _make_fresh_manager()
        base = datetime(2026, 2, 1, 0, 0, 0)
        for i in range(10):
            mgr.create(_create_session_data(
                session_id=f'ls-offset-{i}',
                create_time=base + timedelta(hours=i),
                update_time=base + timedelta(hours=i)
            ))
        results = mgr.list_sessions(offset=3, limit=1000, sort_key='create_time', order_by='asc')
        self.assertEqual(len(results), 7)
        self.assertEqual(results[0].session_id, 'ls-offset-3')

    def test_list_sessions_pagination_limit(self):
        """Test list_sessions with limit restricts result count."""
        mgr = _make_fresh_manager()
        base = datetime(2026, 3, 1, 0, 0, 0)
        for i in range(10):
            mgr.create(_create_session_data(
                session_id=f'ls-limit-{i}',
                create_time=base + timedelta(hours=i),
                update_time=base + timedelta(hours=i)
            ))
        results = mgr.list_sessions(offset=0, limit=3, sort_key='create_time', order_by='asc')
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0].session_id, 'ls-limit-0')

    def test_list_sessions_pagination_offset_and_limit(self):
        """Test list_sessions with both offset and limit for page-style access."""
        mgr = _make_fresh_manager()
        base = datetime(2026, 4, 1, 0, 0, 0)
        for i in range(10):
            mgr.create(_create_session_data(
                session_id=f'ls-page-{i}',
                create_time=base + timedelta(hours=i),
                update_time=base + timedelta(hours=i)
            ))
        results = mgr.list_sessions(offset=5, limit=3, sort_key='create_time', order_by='asc')
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0].session_id, 'ls-page-5')

    def test_list_sessions_offset_zero(self):
        """Test list_sessions with offset=0 returns from the beginning."""
        mgr = _make_fresh_manager()
        base = datetime(2026, 5, 1, 0, 0, 0)
        for i in range(3):
            mgr.create(_create_session_data(
                session_id=f'ls-zero-{i}',
                create_time=base + timedelta(hours=i),
                update_time=base + timedelta(hours=i)
            ))
        results = mgr.list_sessions(offset=0, limit=1000, sort_key='create_time', order_by='asc')
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0].session_id, 'ls-zero-0')

    def test_list_sessions_offset_exceeds_total(self):
        """Test list_sessions with offset > total returns empty list."""
        mgr = _make_fresh_manager()
        base = datetime(2026, 6, 1, 0, 0, 0)
        for i in range(3):
            mgr.create(_create_session_data(
                session_id=f'ls-exceed-{i}',
                create_time=base + timedelta(hours=i),
                update_time=base + timedelta(hours=i)
            ))
        results = mgr.list_sessions(offset=100, limit=1000, sort_key='create_time', order_by='asc')
        self.assertEqual(len(results), 0)

    def test_list_sessions_limit_zero(self):
        """Test list_sessions with limit=0 returns empty list."""
        mgr = _make_fresh_manager()
        mgr.create(_create_session_data(session_id='ls-limzero', create_time=datetime(2026, 7, 1)))
        results = mgr.list_sessions(offset=0, limit=0)
        self.assertEqual(len(results), 0)

    def test_list_sessions_filter_by_session_ids(self):
        """Test list_sessions filtering by specific session_ids."""
        mgr = _make_fresh_manager()
        base = datetime(2026, 8, 1, 0, 0, 0)
        for i in range(5):
            mgr.create(_create_session_data(
                session_id=f'ls-fid-{i}',
                create_time=base + timedelta(hours=i),
                update_time=base + timedelta(hours=i)
            ))
        results = mgr.list_sessions(session_ids=['ls-fid-1', 'ls-fid-3'])
        self.assertEqual(len(results), 2)
        result_ids = [r.session_id for r in results]
        self.assertIn('ls-fid-1', result_ids)
        self.assertIn('ls-fid-3', result_ids)
        self.assertNotIn('ls-fid-0', result_ids)

    def test_list_sessions_filter_by_start_time(self):
        """Test list_sessions filtering by start_time."""
        mgr = _make_fresh_manager()
        base = datetime(2026, 9, 1, 0, 0, 0)
        for i in range(5):
            mgr.create(_create_session_data(
                session_id=f'ls-start-{i}',
                create_time=base + timedelta(days=i),
                update_time=base + timedelta(days=i)
            ))
        start_time = base + timedelta(days=2)
        results = mgr.list_sessions(start_time=start_time)
        for r in results:
            self.assertGreaterEqual(r.create_time, start_time)

    def test_list_sessions_filter_by_end_time(self):
        """Test list_sessions filtering by end_time."""
        mgr = _make_fresh_manager()
        base = datetime(2026, 10, 1, 0, 0, 0)
        for i in range(5):
            mgr.create(_create_session_data(
                session_id=f'ls-end-{i}',
                create_time=base + timedelta(days=i),
                update_time=base + timedelta(days=i)
            ))
        end_time = base + timedelta(days=3)
        results = mgr.list_sessions(end_time=end_time)
        for r in results:
            self.assertLessEqual(r.create_time, end_time)

    def test_list_sessions_filter_by_time_range(self):
        """Test list_sessions filtering by both start_time and end_time."""
        mgr = _make_fresh_manager()
        base = datetime(2026, 11, 1, 0, 0, 0)
        for i in range(7):
            mgr.create(_create_session_data(
                session_id=f'ls-range-{i}',
                create_time=base + timedelta(days=i),
                update_time=base + timedelta(days=i)
            ))
        start_time = base + timedelta(days=2)
        end_time = base + timedelta(days=4)
        results = mgr.list_sessions(start_time=start_time, end_time=end_time)
        for r in results:
            self.assertGreaterEqual(r.create_time, start_time)
            self.assertLessEqual(r.create_time, end_time)

    def test_list_sessions_sort_desc(self):
        """Test list_sessions sorting by create_time descending."""
        mgr = _make_fresh_manager()
        base = datetime(2026, 12, 1, 0, 0, 0)
        for i in range(5):
            mgr.create(_create_session_data(
                session_id=f'ls-desc-{i}',
                create_time=base + timedelta(hours=i),
                update_time=base + timedelta(hours=i)
            ))
        results = mgr.list_sessions(sort_key='create_time', order_by='desc')
        times = [r.create_time for r in results]
        for j in range(len(times) - 1):
            self.assertGreaterEqual(times[j], times[j + 1])

    def test_list_sessions_sort_asc(self):
        """Test list_sessions sorting by create_time ascending."""
        mgr = _make_fresh_manager()
        base = datetime(2027, 1, 1, 0, 0, 0)
        for i in range(5):
            mgr.create(_create_session_data(
                session_id=f'ls-asc-{i}',
                create_time=base + timedelta(hours=i),
                update_time=base + timedelta(hours=i)
            ))
        results = mgr.list_sessions(sort_key='create_time', order_by='asc')
        times = [r.create_time for r in results]
        for j in range(len(times) - 1):
            self.assertLessEqual(times[j], times[j + 1])

    def test_list_sessions_sort_by_update_time(self):
        """Test list_sessions sorting by update_time."""
        mgr = _make_fresh_manager()
        base = datetime(2027, 2, 1, 0, 0, 0)
        for i in range(3):
            mgr.create(_create_session_data(
                session_id=f'ls-ut-{i}',
                create_time=base,
                update_time=base + timedelta(hours=i)
            ))
        results = mgr.list_sessions(sort_key='update_time', order_by='asc')
        times = [r.update_time for r in results]
        for j in range(len(times) - 1):
            self.assertLessEqual(times[j], times[j + 1])

    def test_list_sessions_sort_by_session_id(self):
        """Test list_sessions sorting by session_id."""
        mgr = _make_fresh_manager()
        base = datetime(2027, 3, 1, 0, 0, 0)
        for i in range(3):
            mgr.create(_create_session_data(
                session_id=f'ls-sid-{i}',
                create_time=base, update_time=base
            ))
        results = mgr.list_sessions(sort_key='session_id', order_by='asc')
        ids = [r.session_id for r in results]
        self.assertEqual(ids, sorted(ids))

    def test_list_sessions_sort_by_session_name(self):
        """Test list_sessions sorting by session_name."""
        mgr = _make_fresh_manager()
        base = datetime(2027, 4, 1, 0, 0, 0)
        names = ['Beta', 'Alpha', 'Gamma']
        for i, name in enumerate(names):
            mgr.create(_create_session_data(
                session_id=f'ls-name-{i}',
                session_name=name,
                create_time=base, update_time=base
            ))
        results = mgr.list_sessions(sort_key='session_name', order_by='asc')
        result_names = [r.session_name for r in results]
        self.assertEqual(result_names, sorted(result_names))

    def test_list_sessions_empty_result_set(self):
        """Test list_sessions returns empty list when no matching sessions."""
        mgr = _make_fresh_manager()
        results = mgr.list_sessions(session_ids=['nonexistent-id-999'])
        self.assertEqual(len(results), 0)

    def test_list_sessions_no_filters(self):
        """Test list_sessions with no filters returns all sessions."""
        mgr = _make_fresh_manager()
        base = datetime(2027, 5, 1, 0, 0, 0)
        for i in range(3):
            mgr.create(_create_session_data(
                session_id=f'ls-nofilter-{i}',
                create_time=base + timedelta(hours=i),
                update_time=base + timedelta(hours=i)
            ))
        results = mgr.list_sessions()
        self.assertEqual(len(results), 3)

    # ============================================================
    # New tests for verify_indexes
    # ============================================================

    def test_verify_indexes_returns_dict(self):
        """Test verify_indexes returns a dictionary."""
        result = self.session_manager.verify_indexes()
        self.assertIsInstance(result, dict)

    def test_verify_indexes_composite_index_exists(self):
        """Test verify_indexes detects the composite index on update_time and create_time."""
        result = self.session_manager.verify_indexes()
        self.assertIn('idx_session_update_create_time', result)
        self.assertTrue(result['idx_session_update_create_time'])

    def test_verify_indexes_processed_msg_id_index_exists(self):
        """Test verify_indexes detects the index on processed_msg_id column."""
        result = self.session_manager.verify_indexes()
        self.assertIn('ix_session_processed_msg_id', result)
        self.assertTrue(result['ix_session_processed_msg_id'])

    def test_verify_indexes_all_indexes_present(self):
        """Test verify_indexes confirms all required indexes are present."""
        result = self.session_manager.verify_indexes()
        for idx_name, exists in result.items():
            self.assertTrue(exists, f"Index '{idx_name}' should exist")

    # ============================================================
    # New tests for exists_session
    # ============================================================

    def test_exists_session_raises_not_implemented(self):
        """Test exists_session raises NotImplementedError (not implemented in SessionSQLAlchemy)."""
        with self.assertRaises(NotImplementedError):
            self.session_manager.exists_session('any-session-id')

    def test_exists_session_empty_session_id_raises_not_implemented(self):
        """Test exists_session with empty session_id still raises NotImplementedError."""
        with self.assertRaises(NotImplementedError):
            self.session_manager.exists_session('')

    def test_exists_session_none_session_id_raises_not_implemented(self):
        """Test exists_session with None session_id still raises NotImplementedError."""
        with self.assertRaises(NotImplementedError):
            self.session_manager.exists_session(None)

    # ============================================================
    # New tests for get_all
    # ============================================================

    def test_get_all_returns_all_sessions(self):
        """Test get_all returns all sessions in the database."""
        mgr = _make_fresh_manager()
        base = datetime(2027, 6, 1, 0, 0, 0)
        for i in range(5):
            mgr.create(_create_session_data(
                session_id=f'ga-session-{i}',
                create_time=base + timedelta(hours=i),
                update_time=base + timedelta(hours=i)
            ))
        all_sessions = mgr.get_all()
        self.assertEqual(len(all_sessions), 5)
        all_ids = [s.session_id for s in all_sessions]
        for i in range(5):
            self.assertIn(f'ga-session-{i}', all_ids)

    def test_get_all_returns_list_of_session_data(self):
        """Test get_all returns a list of SessionData objects."""
        mgr = _make_fresh_manager()
        mgr.create(_create_session_data(session_id='ga-type-test'))
        all_sessions = mgr.get_all()
        self.assertIsInstance(all_sessions, list)
        for session in all_sessions:
            self.assertIsInstance(session, SessionData)

    def test_get_all_empty_database(self):
        """Test get_all on empty database returns empty list."""
        mgr = _make_fresh_manager()
        result = mgr.get_all()
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 0)

    def test_get_all_large_result_set(self):
        """Test get_all handles a large number of sessions."""
        mgr = _make_fresh_manager()
        base = datetime(2027, 7, 1, 0, 0, 0)
        for i in range(50):
            mgr.create(_create_session_data(
                session_id=f'ga-large-{i}',
                create_time=base + timedelta(minutes=i),
                update_time=base + timedelta(minutes=i)
            ))
        all_sessions = mgr.get_all()
        self.assertEqual(len(all_sessions), 50)

    def test_get_all_includes_session_attributes(self):
        """Test get_all returns sessions with all expected attributes."""
        mgr = _make_fresh_manager()
        now = datetime(2027, 8, 1, 12, 0, 0)
        mgr.create(SessionData(
            session_id='ga-attr-test',
            session_name='Attribute Test',
            task='Verify all attributes',
            create_time=now,
            update_time=now,
            processed_msg_id='msg-attr-001'
        ))
        all_sessions = mgr.get_all()
        self.assertEqual(len(all_sessions), 1)
        s = all_sessions[0]
        self.assertEqual(s.session_id, 'ga-attr-test')
        self.assertEqual(s.session_name, 'Attribute Test')
        self.assertEqual(s.task, 'Verify all attributes')
        self.assertEqual(s.processed_msg_id, 'msg-attr-001')

    # ============================================================
    # New tests for get_sessions_before
    # ============================================================

    def test_get_sessions_before_returns_sessions_before_time(self):
        """Test get_sessions_before returns sessions with update_time before cutoff."""
        mgr = _make_fresh_manager()
        base = datetime(2027, 9, 1, 0, 0, 0)
        for i in range(5):
            mgr.create(_create_session_data(
                session_id=f'gb-before-{i}',
                create_time=base + timedelta(hours=i),
                update_time=base + timedelta(hours=i)
            ))
        cutoff = base + timedelta(hours=3)
        results = mgr.get_sessions_before(cutoff)
        result_ids = [r.session_id for r in results]
        # Sessions 0, 1, 2 have update_time < hour 3
        self.assertIn('gb-before-0', result_ids)
        self.assertIn('gb-before-1', result_ids)
        self.assertIn('gb-before-2', result_ids)
        self.assertNotIn('gb-before-3', result_ids)
        self.assertNotIn('gb-before-4', result_ids)

    def test_get_sessions_before_no_sessions_before_timestamp(self):
        """Test get_sessions_before returns empty when no sessions before cutoff."""
        mgr = _make_fresh_manager()
        base = datetime(2027, 10, 1, 12, 0, 0)
        for i in range(3):
            mgr.create(_create_session_data(
                session_id=f'gb-none-{i}',
                create_time=base + timedelta(hours=i),
                update_time=base + timedelta(hours=i)
            ))
        # Cutoff before all sessions
        cutoff = base - timedelta(hours=1)
        results = mgr.get_sessions_before(cutoff)
        self.assertEqual(len(results), 0)

    def test_get_sessions_before_exact_timestamp_boundary(self):
        """Test get_sessions_before with exact timestamp - session at exact time excluded."""
        mgr = _make_fresh_manager()
        exact_time = datetime(2027, 11, 1, 12, 0, 0)
        mgr.create(_create_session_data(
            session_id='gb-exact',
            create_time=exact_time,
            update_time=exact_time
        ))
        mgr.create(_create_session_data(
            session_id='gb-earlier',
            create_time=exact_time - timedelta(hours=1),
            update_time=exact_time - timedelta(hours=1)
        ))
        # Cutoff at exact_time: uses < (strict less than)
        results = mgr.get_sessions_before(exact_time)
        result_ids = [r.session_id for r in results]
        self.assertIn('gb-earlier', result_ids)
        self.assertNotIn('gb-exact', result_ids)

    def test_get_sessions_before_with_mixed_times(self):
        """Test get_sessions_before correctly filters with mixed update times."""
        mgr = _make_fresh_manager()
        base = datetime(2027, 12, 1, 0, 0, 0)
        # Create sessions with different create and update times
        mgr.create(_create_session_data(
            session_id='gb-mixed-1',
            create_time=base,
            update_time=base + timedelta(hours=1)
        ))
        mgr.create(_create_session_data(
            session_id='gb-mixed-2',
            create_time=base,
            update_time=base + timedelta(hours=5)
        ))
        mgr.create(_create_session_data(
            session_id='gb-mixed-3',
            create_time=base,
            update_time=base + timedelta(hours=10)
        ))
        cutoff = base + timedelta(hours=6)
        results = mgr.get_sessions_before(cutoff)
        result_ids = [r.session_id for r in results]
        self.assertIn('gb-mixed-1', result_ids)
        self.assertIn('gb-mixed-2', result_ids)
        self.assertNotIn('gb-mixed-3', result_ids)


if __name__ == '__main__':
    unittest.main()
