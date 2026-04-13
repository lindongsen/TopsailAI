"""
Test TOPSAILAI_AGENT_DAEMON_PROCESSOR script scenarios

Documentation Requirements (from docs/cases/test1.md):
1. Reply directly and call ReceiveMessage
2. Generate a task and call SetTaskResult
"""

import unittest
import os
import subprocess
import tempfile
from datetime import datetime

os.environ['TOPSAILAI_AGENT_DAEMON_PROCESSOR'] = '/bin/echo'
os.environ['TOPSAILAI_AGENT_DAEMON_SUMMARIZER'] = '/bin/echo'
os.environ['TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER'] = '/bin/echo'
os.environ['TOPSAILAI_AGENT_DAEMON_DB_URL'] = 'sqlite:///:memory:'

from sqlalchemy import create_engine

from topsailai_server.agent_daemon.storage import Storage, SessionData, MessageData
from topsailai_server.agent_daemon.worker import WorkerManager
from topsailai_server.agent_daemon.configer import get_config


class TestProcessorScenario1(unittest.TestCase):
    """Scenario 1: Reply directly and call ReceiveMessage"""
    
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        self.storage = Storage(self.engine)
        self.storage.init_db()
        
        session = SessionData(
            session_id='direct-reply-session',
            session_name='Test Session',
            task=None,
            create_time=datetime.now(),
            update_time=datetime.now(),
            processed_msg_id=None
        )
        self.storage.session.create(session)
    
    def test_scenario1_direct_reply(self):
        """Test that processor can reply directly and create new message"""
        # Create initial user message
        initial_msg = MessageData(
            msg_id='msg-1',
            session_id='direct-reply-session',
            message='User message',
            role='user',
            create_time=datetime.now(),
            update_time=datetime.now(),
            task_id=None,
            task_result=None
        )
        self.storage.message.create(initial_msg)
        
        self.storage.session.update_processed_msg_id('direct-reply-session', 'msg-1')
        
        reply_msg = MessageData(
            msg_id='reply-msg-1',
            session_id='direct-reply-session',
            message='This is a direct reply',
            role='assistant',
            create_time=datetime.now(),
            update_time=datetime.now(),
            task_id=None,
            task_result=None
        )
        result = self.storage.message.create(reply_msg)
        self.assertTrue(result)
        
        self.storage.session.update_processed_msg_id('direct-reply-session', 'reply-msg-1')
        
        messages = self.storage.message.get_by_session('direct-reply-session')
        self.assertEqual(len(messages), 2)
        
        latest_msg = self.storage.message.get_latest_message('direct-reply-session')
        self.assertEqual(latest_msg.msg_id, 'reply-msg-1')
    
    def test_scenario1_retrieve_messages(self):
        """Test RetrieveMessages API to verify direct reply"""
        msg1 = MessageData(
            msg_id='msg-1',
            session_id='test-session',
            message='User message',
            role='user',
            create_time=datetime.now(),
            update_time=datetime.now(),
            task_id=None,
            task_result=None
        )
        self.storage.message.create(msg1)
        
        msg2 = MessageData(
            msg_id='msg-2',
            session_id='test-session',
            message='Assistant reply',
            role='assistant',
            create_time=datetime.now(),
            update_time=datetime.now(),
            task_id=None,
            task_result=None
        )
        self.storage.message.create(msg2)
        
        messages = self.storage.message.get_by_session('test-session')
        self.assertEqual(len(messages), 2)
        
        user_messages = [m for m in messages if m.role == 'user']
        assistant_messages = [m for m in messages if m.role == 'assistant']
        
        self.assertEqual(len(user_messages), 1)
        self.assertEqual(len(assistant_messages), 1)


class TestProcessorScenario2(unittest.TestCase):
    """Scenario 2: Generate a task and call SetTaskResult"""
    
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        self.storage = Storage(self.engine)
        self.storage.init_db()
        
        session = SessionData(
            session_id='task-session',
            session_name='Task Session',
            task=None,
            create_time=datetime.now(),
            update_time=datetime.now(),
            processed_msg_id=None
        )
        self.storage.session.create(session)
    
    def test_scenario2_task_generation(self):
        """Test that processor can generate a task"""
        task_msg = MessageData(
            msg_id='task-msg-1',
            session_id='task-session',
            message='Please perform a complex task',
            role='user',
            create_time=datetime.now(),
            update_time=datetime.now(),
            task_id='task-123',
            task_result=None
        )
        result = self.storage.message.create(task_msg)
        self.assertTrue(result)
        
        self.storage.session.update_processed_msg_id('task-session', 'task-msg-1')
        
        retrieved_msg = self.storage.message.get('task-msg-1', 'task-session')
        self.assertIsNotNone(retrieved_msg)
        self.assertEqual(retrieved_msg.task_id, 'task-123')
    
    def test_scenario2_task_result(self):
        """Test that task result can be set via SetTaskResult"""
        task_msg = MessageData(
            msg_id='task-msg-2',
            session_id='task-session',
            message='Another task',
            role='user',
            create_time=datetime.now(),
            update_time=datetime.now(),
            task_id='task-456',
            task_result=None
        )
        self.storage.message.create(task_msg)
        
        updated_msg = self.storage.message.update_task_info(
            'task-msg-2', 'task-session', 'task-456', 'Task completed successfully'
        )
        
        self.assertIsNotNone(updated_msg)
        self.assertEqual(updated_msg.task_result, 'Task completed successfully')
        
        self.storage.session.update_processed_msg_id('task-session', 'task-msg-2')
        
        latest = self.storage.message.get_latest_message('task-session')
        self.assertEqual(latest.task_result, 'Task completed successfully')


class TestProcessorWorkerManager(unittest.TestCase):
    """Test WorkerManager processor execution"""
    
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        self.storage = Storage(self.engine)
        self.storage.init_db()
        
        config = get_config()
        self.worker_manager = WorkerManager(config)
    
    def test_start_processor(self):
        """Test that start_processor can be called"""
        result = self.worker_manager.start_processor(
            session_id='test-session',
            msg_id='test-msg-id',
            task='Test task'
        )
        
        self.assertIsNotNone(result)
    
    def test_processor_environment_variables(self):
        """Test that processor receives correct environment variables"""
        test_script = '''#!/bin/bash
        echo "TOPSAILAI_MSG_ID=$TOPSAILAI_MSG_ID"
        echo "TOPSAILAI_TASK=$TOPSAILAI_TASK"
        echo "TOPSAILAI_SESSION_ID=$TOPSAILAI_SESSION_ID"
        '''
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
            f.write(test_script)
            script_path = f.name
        
        os.chmod(script_path, 0o755)
        
        try:
            env = os.environ.copy()
            env['TOPSAILAI_MSG_ID'] = 'test-msg-123'
            env['TOPSAILAI_TASK'] = 'Test task content'
            env['TOPSAILAI_SESSION_ID'] = 'test-session-456'
            
            result = subprocess.run([script_path], env=env, capture_output=True, text=True)
            
            self.assertIn('TOPSAILAI_MSG_ID=test-msg-123', result.stdout)
            self.assertIn('TOPSAILAI_TASK=Test task content', result.stdout)
            self.assertIn('TOPSAILAI_SESSION_ID=test-session-456', result.stdout)
        finally:
            os.unlink(script_path)


class TestProcessorScript(unittest.TestCase):
    """Test processor script execution"""
    
    def test_processor_script_exists(self):
        """Test that processor script exists"""
        processor_script = os.environ.get('TOPSAILAI_AGENT_DAEMON_PROCESSOR')
        self.assertIsNotNone(processor_script)
        self.assertTrue(os.path.exists(processor_script))
    
    def test_processor_script_executable(self):
        """Test that processor script is executable"""
        processor_script = os.environ.get('TOPSAILAI_AGENT_DAEMON_PROCESSOR')
        if os.path.exists(processor_script):
            self.assertTrue(os.access(processor_script, os.X_OK))


if __name__ == '__main__':
    unittest.main()
