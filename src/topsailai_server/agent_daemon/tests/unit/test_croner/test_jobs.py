'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-14
  Purpose: Unit tests for Croner Jobs
'''

import unittest
import os
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

# Set test environment variables before imports
os.environ['TOPSAILAI_AGENT_DAEMON_PROCESSOR'] = '/bin/echo'
os.environ['TOPSAILAI_AGENT_DAEMON_SUMMARIZER'] = '/bin/echo'
os.environ['TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER'] = '/bin/echo'

from sqlalchemy import create_engine

from topsailai_server.agent_daemon import logger
from topsailai_server.agent_daemon.storage import Storage
from topsailai_server.agent_daemon.storage.session_manager.base import SessionData
from topsailai_server.agent_daemon.storage.message_manager.base import MessageData
from topsailai_server.agent_daemon.croner.jobs.message_consumer import MessageConsumer, _processor_circuit_breaker
from topsailai_server.agent_daemon.croner.jobs.message_summarizer import MessageSummarizer
from topsailai_server.agent_daemon.croner.jobs.session_cleaner import SessionCleaner
from topsailai_server.agent_daemon.worker import WorkerManager


class TestMessageConsumer(unittest.TestCase):
    """Test cases for MessageConsumer job"""

    def setUp(self):
        """Set up each test with fresh database"""
        # Reset circuit breaker before each test
        _processor_circuit_breaker.reset()
        
        # Create fresh in-memory database for each test
        self.engine = create_engine('sqlite:///:memory:')
        self.storage = Storage(self.engine)
        self.storage.init_db()
        self.mock_worker_manager = Mock(spec=WorkerManager)
        self.mock_worker_manager.check_session_state.return_value = 'idle'
        self.mock_worker_manager.start_processor.return_value = True

    def tearDown(self):
        """Clean up after each test"""
        # Dispose engine to close connections
        self.engine.dispose()

    def test_no_recent_messages(self):
        """Test when there are no recent messages"""
        # Create a session but no recent messages
        session_data = SessionData(
            session_id='test-session-no-msg',
            session_name='Test Session No Messages',
            task=None,
            create_time=datetime.now(),
            update_time=datetime.now(),
            processed_msg_id=None
        )
        self.storage.session.create(session_data)

        job = MessageConsumer(
            interval_seconds=60,
            storage=self.storage,
            worker_manager=self.mock_worker_manager
        )

        # Run the job with no recent messages
        job.run()

        # Verify no processor was started
        self.mock_worker_manager.start_processor.assert_not_called()
        logger.info("test_no_recent_messages: passed")

    def test_recent_messages_found_triggers_processing(self):
        """Test when recent messages are found and processing is triggered"""
        # Create a session
        session_data = SessionData(
            session_id='test-session-trigger',
            session_name='Test Session Trigger',
            task=None,
            create_time=datetime.now(),
            update_time=datetime.now(),
            processed_msg_id=None
        )
        self.storage.session.create(session_data)

        # Create a recent message
        message_data = MessageData(
            msg_id='msg-trigger-1',
            session_id='test-session-trigger',
            message='Test message',
            role='user',
            create_time=datetime.now(),
            update_time=datetime.now(),
            task_id=None,
            task_result=None
        )
        self.storage.message.create(message_data)

        job = MessageConsumer(
            interval_seconds=60,
            storage=self.storage,
            worker_manager=self.mock_worker_manager
        )

        # Run the job
        job.run()

        # Verify processor was started
        self.mock_worker_manager.start_processor.assert_called_once()
        call_args = self.mock_worker_manager.start_processor.call_args
        self.assertEqual(call_args.kwargs['session_id'], 'test-session-trigger')
        self.assertEqual(call_args.kwargs['msg_id'], 'msg-trigger-1')
        logger.info("test_recent_messages_found_triggers_processing: passed")

    def test_multiple_sessions_with_messages(self):
        """Test when multiple sessions have messages"""
        # Create first session
        session1 = SessionData(
            session_id='test-session-multi-1',
            session_name='Test Session Multi 1',
            task=None,
            create_time=datetime.now(),
            update_time=datetime.now(),
            processed_msg_id=None
        )
        self.storage.session.create(session1)

        # Create second session
        session2 = SessionData(
            session_id='test-session-multi-2',
            session_name='Test Session Multi 2',
            task=None,
            create_time=datetime.now(),
            update_time=datetime.now(),
            processed_msg_id=None
        )
        self.storage.session.create(session2)

        # Create messages for both sessions
        message1 = MessageData(
            msg_id='msg-multi-1',
            session_id='test-session-multi-1',
            message='Test message 1',
            role='user',
            create_time=datetime.now(),
            update_time=datetime.now(),
            task_id=None,
            task_result=None
        )
        message2 = MessageData(
            msg_id='msg-multi-2',
            session_id='test-session-multi-2',
            message='Test message 2',
            role='user',
            create_time=datetime.now(),
            update_time=datetime.now(),
            task_id=None,
            task_result=None
        )
        self.storage.message.create(message1)
        self.storage.message.create(message2)

        job = MessageConsumer(
            interval_seconds=60,
            storage=self.storage,
            worker_manager=self.mock_worker_manager
        )

        # Run the job
        job.run()

        # Verify processor was started for both sessions
        self.assertEqual(self.mock_worker_manager.start_processor.call_count, 2)
        logger.info("test_multiple_sessions_with_messages: passed")

    def test_error_handling_during_processing(self):
        """Test error handling when processing fails"""
        # Create a session
        session_data = SessionData(
            session_id='test-session-error',
            session_name='Test Session Error',
            task=None,
            create_time=datetime.now(),
            update_time=datetime.now(),
            processed_msg_id=None
        )
        self.storage.session.create(session_data)

        # Create a recent message
        message_data = MessageData(
            msg_id='msg-error-1',
            session_id='test-session-error',
            message='Test message',
            role='user',
            create_time=datetime.now(),
            update_time=datetime.now(),
            task_id=None,
            task_result=None
        )
        self.storage.message.create(message_data)

        # Make worker manager raise an error
        self.mock_worker_manager.start_processor.side_effect = Exception("Test error")

        job = MessageConsumer(
            interval_seconds=60,
            storage=self.storage,
            worker_manager=self.mock_worker_manager
        )

        # Run should not raise exception
        try:
            job.run()
            logger.info("test_error_handling_during_processing: passed")
        except Exception as e:
            self.fail(f"Job raised unexpected exception: {e}")

    def test_session_already_processing(self):
        """Test when session is already being processed"""
        # Create a session
        session_data = SessionData(
            session_id='test-session-processing',
            session_name='Test Session Processing',
            task=None,
            create_time=datetime.now(),
            update_time=datetime.now(),
            processed_msg_id=None
        )
        self.storage.session.create(session_data)

        # Create a recent message
        message_data = MessageData(
            msg_id='msg-processing-1',
            session_id='test-session-processing',
            message='Test message',
            role='user',
            create_time=datetime.now(),
            update_time=datetime.now(),
            task_id=None,
            task_result=None
        )
        self.storage.message.create(message_data)

        # Set session state to processing
        self.mock_worker_manager.check_session_state.return_value = 'processing'

        job = MessageConsumer(
            interval_seconds=60,
            storage=self.storage,
            worker_manager=self.mock_worker_manager
        )

        # Run the job
        job.run()

        # Verify processor was NOT started
        self.mock_worker_manager.start_processor.assert_not_called()
        logger.info("test_session_already_processing: passed")

    def test_all_messages_are_assistant(self):
        """Test when all unprocessed messages are from assistant (avoid infinite loop)"""
        # Create a session with processed message
        session_data = SessionData(
            session_id='test-session-assistant',
            session_name='Test Session Assistant',
            task=None,
            create_time=datetime.now(),
            update_time=datetime.now(),
            processed_msg_id='msg-old-assistant'
        )
        self.storage.session.create(session_data)

        # Create old processed message
        old_message = MessageData(
            msg_id='msg-old-assistant',
            session_id='test-session-assistant',
            message='Old assistant message',
            role='assistant',
            create_time=datetime.now() - timedelta(minutes=5),
            update_time=datetime.now() - timedelta(minutes=5),
            task_id=None,
            task_result=None
        )
        self.storage.message.create(old_message)

        # Create new assistant-only messages (all assistant)
        new_message = MessageData(
            msg_id='msg-new-assistant',
            session_id='test-session-assistant',
            message='New assistant message',
            role='assistant',
            create_time=datetime.now(),
            update_time=datetime.now(),
            task_id=None,
            task_result=None
        )
        self.storage.message.create(new_message)

        job = MessageConsumer(
            interval_seconds=60,
            storage=self.storage,
            worker_manager=self.mock_worker_manager
        )

        # Run the job
        job.run()

        # Verify processor was NOT started (to avoid infinite loop)
        self.mock_worker_manager.start_processor.assert_not_called()
        logger.info("test_all_messages_are_assistant: passed")


class TestMessageSummarizer(unittest.TestCase):
    """Test cases for MessageSummarizer job"""

    def setUp(self):
        """Set up each test with fresh database"""
        # Create fresh in-memory database for each test
        self.engine = create_engine('sqlite:///:memory:')
        self.storage = Storage(self.engine)
        self.storage.init_db()
        self.mock_worker_manager = Mock(spec=WorkerManager)
        self.mock_worker_manager.start_summarizer.return_value = MagicMock()

    def tearDown(self):
        """Clean up after each test"""
        # Dispose engine to close connections
        self.engine.dispose()

    def test_no_messages_in_last_24h(self):
        """Test when there are no messages in the last 24 hours"""
        # Create a session but no recent messages
        session_data = SessionData(
            session_id='summarize-session-empty',
            session_name='Summarize Test Session Empty',
            task=None,
            create_time=datetime.now(),
            update_time=datetime.now(),
            processed_msg_id=None
        )
        self.storage.session.create(session_data)

        job = MessageSummarizer(
            storage=self.storage,
            worker_manager=self.mock_worker_manager
        )

        # Run the job
        job.run()

        # Verify no summarizer was started
        self.mock_worker_manager.start_summarizer.assert_not_called()
        logger.info("test_no_messages_in_last_24h: passed")

    def test_messages_found_triggers_summarizer(self):
        """Test when messages are found and summarizer is triggered"""
        # Create a session
        session_data = SessionData(
            session_id='summarize-session-found',
            session_name='Summarize Test Session Found',
            task=None,
            create_time=datetime.now(),
            update_time=datetime.now(),
            processed_msg_id=None
        )
        self.storage.session.create(session_data)

        # Create a recent message (within 24 hours)
        message_data = MessageData(
            msg_id='sum-msg-found-1',
            session_id='summarize-session-found',
            message='Test message for summarization',
            role='user',
            create_time=datetime.now(),
            update_time=datetime.now(),
            task_id=None,
            task_result=None
        )
        self.storage.message.create(message_data)

        job = MessageSummarizer(
            storage=self.storage,
            worker_manager=self.mock_worker_manager
        )

        # Run the job
        job.run()

        # Verify summarizer was started
        self.mock_worker_manager.start_summarizer.assert_called_once()
        call_args = self.mock_worker_manager.start_summarizer.call_args
        self.assertEqual(call_args.kwargs['session_id'], 'summarize-session-found')
        logger.info("test_messages_found_triggers_summarizer: passed")

    def test_messages_sorted_by_create_time(self):
        """Test that messages are sorted by create_time"""
        # Create a session
        session_data = SessionData(
            session_id='summarize-session-sorted',
            session_name='Summarize Test Session Sorted',
            task=None,
            create_time=datetime.now(),
            update_time=datetime.now(),
            processed_msg_id=None
        )
        self.storage.session.create(session_data)

        # Create messages with different timestamps
        message1 = MessageData(
            msg_id='sum-msg-sorted-1',
            session_id='summarize-session-sorted',
            message='First message',
            role='user',
            create_time=datetime.now() - timedelta(hours=2),
            update_time=datetime.now() - timedelta(hours=2),
            task_id=None,
            task_result=None
        )
        message2 = MessageData(
            msg_id='sum-msg-sorted-2',
            session_id='summarize-session-sorted',
            message='Second message',
            role='assistant',
            create_time=datetime.now() - timedelta(hours=1),
            update_time=datetime.now() - timedelta(hours=1),
            task_id=None,
            task_result=None
        )
        message3 = MessageData(
            msg_id='sum-msg-sorted-3',
            session_id='summarize-session-sorted',
            message='Third message',
            role='user',
            create_time=datetime.now(),
            update_time=datetime.now(),
            task_id=None,
            task_result=None
        )
        self.storage.message.create(message1)
        self.storage.message.create(message2)
        self.storage.message.create(message3)

        job = MessageSummarizer(
            storage=self.storage,
            worker_manager=self.mock_worker_manager
        )

        # Run the job
        job.run()

        # Verify summarizer was called
        self.mock_worker_manager.start_summarizer.assert_called_once()
        call_args = self.mock_worker_manager.start_summarizer.call_args
        task_content = call_args.kwargs['task']

        # Verify messages are in chronological order
        first_pos = task_content.find('First message')
        second_pos = task_content.find('Second message')
        third_pos = task_content.find('Third message')

        self.assertLess(first_pos, second_pos)
        self.assertLess(second_pos, third_pos)
        logger.info("test_messages_sorted_by_create_time: passed")

    def test_error_handling(self):
        """Test error handling during summarization"""
        # Create a session
        session_data = SessionData(
            session_id='summarize-session-error',
            session_name='Summarize Test Session Error',
            task=None,
            create_time=datetime.now(),
            update_time=datetime.now(),
            processed_msg_id=None
        )
        self.storage.session.create(session_data)

        # Create a recent message
        message_data = MessageData(
            msg_id='sum-msg-error-1',
            session_id='summarize-session-error',
            message='Test message',
            role='user',
            create_time=datetime.now(),
            update_time=datetime.now(),
            task_id=None,
            task_result=None
        )
        self.storage.message.create(message_data)

        # Make summarizer raise an error
        self.mock_worker_manager.start_summarizer.side_effect = Exception("Test error")

        job = MessageSummarizer(
            storage=self.storage,
            worker_manager=self.mock_worker_manager
        )

        # Run should not raise exception
        try:
            job.run()
            logger.info("test_error_handling: passed")
        except Exception as e:
            self.fail(f"Job raised unexpected exception: {e}")


class TestSessionCleaner(unittest.TestCase):
    """Test cases for SessionCleaner job"""

    def setUp(self):
        """Set up each test with fresh database"""
        # Create fresh in-memory database for each test
        self.engine = create_engine('sqlite:///:memory:')
        self.storage = Storage(self.engine)
        self.storage.init_db()

    def tearDown(self):
        """Clean up after each test"""
        # Dispose engine to close connections
        self.engine.dispose()

    def test_no_old_sessions_to_clean(self):
        """Test when there are no old sessions to clean"""
        # Create a recent session
        session_data = SessionData(
            session_id='recent-session-cleaner',
            session_name='Recent Session Cleaner',
            task=None,
            create_time=datetime.now(),
            update_time=datetime.now(),
            processed_msg_id=None
        )
        self.storage.session.create(session_data)

        job = SessionCleaner(storage=self.storage)

        # Run the job
        job.run()

        # Verify session was NOT deleted
        session = self.storage.session.get('recent-session-cleaner')
        self.assertIsNotNone(session)
        logger.info("test_no_old_sessions_to_clean: passed")

    def test_old_sessions_found_and_deleted(self):
        """Test when old sessions are found and deleted"""
        # Create an old session (more than 1 year old)
        old_time = datetime.now() - timedelta(days=400)
        session_data = SessionData(
            session_id='old-session-cleaner-1',
            session_name='Old Session Cleaner 1',
            task=None,
            create_time=old_time,
            update_time=old_time,
            processed_msg_id=None
        )
        self.storage.session.create(session_data)

        job = SessionCleaner(storage=self.storage)

        # Run the job
        job.run()

        # Verify session was deleted
        session = self.storage.session.get('old-session-cleaner-1')
        self.assertIsNone(session)
        logger.info("test_old_sessions_found_and_deleted: passed")

    def test_related_messages_also_deleted(self):
        """Test that related messages are also deleted when session is deleted"""
        # Create an old session
        old_time = datetime.now() - timedelta(days=400)
        session_data = SessionData(
            session_id='old-session-cleaner-2',
            session_name='Old Session with Messages Cleaner',
            task=None,
            create_time=old_time,
            update_time=old_time,
            processed_msg_id=None
        )
        self.storage.session.create(session_data)

        # Create messages for the old session
        message_data = MessageData(
            msg_id='old-msg-cleaner-1',
            session_id='old-session-cleaner-2',
            message='Old message cleaner',
            role='user',
            create_time=old_time,
            update_time=old_time,
            task_id=None,
            task_result=None
        )
        self.storage.message.create(message_data)

        job = SessionCleaner(storage=self.storage)

        # Run the job
        job.run()

        # Verify both session and messages were deleted
        session = self.storage.session.get('old-session-cleaner-2')
        self.assertIsNone(session)

        messages = self.storage.message.get_by_session('old-session-cleaner-2')
        self.assertEqual(len(messages), 0)
        logger.info("test_related_messages_also_deleted: passed")

    def test_error_handling(self):
        """Test error handling during session deletion"""
        # Create an old session
        old_time = datetime.now() - timedelta(days=400)
        session_data = SessionData(
            session_id='old-session-error-cleaner',
            session_name='Old Session Error Cleaner',
            task=None,
            create_time=old_time,
            update_time=old_time,
            processed_msg_id=None
        )
        self.storage.session.create(session_data)

        # Mock storage to raise error on delete
        with patch.object(self.storage.session, 'delete', side_effect=Exception("Delete error")):
            job = SessionCleaner(storage=self.storage)

            # Run should not raise exception
            try:
                job.run()
                logger.info("test_error_handling: passed")
            except Exception as e:
                self.fail(f"Job raised unexpected exception: {e}")


if __name__ == '__main__':
    unittest.main()
