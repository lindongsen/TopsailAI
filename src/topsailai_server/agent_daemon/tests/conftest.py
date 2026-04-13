"""
Pytest Configuration and Shared Fixtures

This module provides shared pytest fixtures for the agent_daemon tests.
These fixtures help create consistent test environments across all test files.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-04-13
"""

import os
import stat
import tempfile
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Set required environment variables before importing project modules
os.environ.setdefault('TOPSAILAI_AGENT_DAEMON_PROCESSOR', '/bin/echo')
os.environ.setdefault('TOPSAILAI_AGENT_DAEMON_SUMMARIZER', '/bin/echo')
os.environ.setdefault('TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER', '/bin/echo')

from topsailai_server.agent_daemon.storage import Storage
from topsailai_server.agent_daemon.storage.session_manager import SessionSQLAlchemy, SessionData
from topsailai_server.agent_daemon.storage.message_manager import MessageSQLAlchemy, MessageData
from topsailai_server.agent_daemon.configer import get_config
from topsailai_server.agent_daemon.worker.process_manager import WorkerManager


# ============================================================================
# Database Fixtures
# ============================================================================

@pytest.fixture(scope='function')
def temp_db_path():
    """
    Fixture providing a temporary database file path.
    
    Creates a temporary SQLite database file that is cleaned up after the test.
    This ensures test isolation and prevents conflicts between tests.
    
    Yields:
        str: Path to the temporary database file
    """
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    
    yield db_path
    
    # Cleanup: remove temporary database file
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture(scope='function')
def db_engine(temp_db_path):
    """
    Fixture providing a SQLAlchemy engine with test database.
    
    Creates a SQLAlchemy engine connected to a temporary SQLite database.
    The engine is disposed after the test.
    
    Args:
        temp_db_path: Path to temporary database file
        
    Yields:
        Engine: SQLAlchemy engine instance
    """
    engine = create_engine(f'sqlite:///{temp_db_path}')
    
    yield engine
    
    # Cleanup: dispose engine connections
    engine.dispose()


@pytest.fixture(scope='function')
def db_session(db_engine):
    """
    Fixture providing a database session with transaction rollback.
    
    Creates a SQLAlchemy session that automatically rolls back
    after each test to ensure test isolation.
    
    Args:
        db_engine: SQLAlchemy engine fixture
        
    Yields:
        Session: Database session
    """
    Session = sessionmaker(bind=db_engine)
    session = Session()
    
    yield session
    
    # Cleanup: rollback any pending transactions
    session.rollback()
    session.close()


@pytest.fixture(scope='function')
def init_database(db_engine):
    """
    Fixture that initializes database tables.
    
    Creates all required tables in the test database.
    This fixture can be used by tests that need a fresh database.
    
    Args:
        db_engine: SQLAlchemy engine fixture
        
    Returns:
        Engine: The same engine with tables initialized
    """
    from topsailai_server.agent_daemon.storage import Base
    Base.metadata.create_all(db_engine)
    return db_engine


@pytest.fixture(scope='function')
def storage(temp_db_path):
    """
    Fixture providing a Storage instance with a temporary database.
    
    Creates a Storage instance connected to a temporary SQLite database.
    The database is initialized with all required tables.
    
    Args:
        temp_db_path: Path to temporary database file
        
    Yields:
        Storage: Configured Storage instance
    """
    engine = create_engine(f'sqlite:///{temp_db_path}')
    storage = Storage(engine)
    storage.init_db()
    
    yield storage
    
    # Cleanup: dispose engine connections
    engine.dispose()


@pytest.fixture(scope='function')
def session_manager(storage):
    """
    Fixture providing a SessionManager instance.
    
    Creates a SessionManager (SessionSQLAlchemy) instance using the
    storage's session manager.
    
    Args:
        storage: Storage fixture providing database access
        
    Yields:
        SessionSQLAlchemy: Session manager instance
    """
    yield storage.session


@pytest.fixture(scope='function')
def message_manager(storage):
    """
    Fixture providing a MessageManager instance.
    
    Creates a MessageManager (MessageSQLAlchemy) instance using the
    storage's message manager.
    
    Args:
        storage: Storage fixture providing database access
        
    Yields:
        MessageSQLAlchemy: Message manager instance
    """
    yield storage.message


# ============================================================================
# Component Fixtures
# ============================================================================

@pytest.fixture(scope='function')
def config():
    """
    Fixture providing a Config instance with test settings.
    
    Creates an EnvConfig instance with validate_scripts=False
    to allow testing without actual script files.
    
    Yields:
        EnvConfig: Configuration instance
    """
    # Use get_config with validate_scripts=False for testing
    cfg = get_config(validate_scripts=False)
    yield cfg
    # Reset global config for next test
    from topsailai_server.agent_daemon.configer import _config
    import topsailai_server.agent_daemon.configer as configer_module
    configer_module._config = None


@pytest.fixture(scope='function')
def worker_manager(config):
    """
    Fixture providing a WorkerManager instance with test config.
    
    Creates a WorkerManager instance using the test config.
    
    Args:
        config: Config fixture
        
    Yields:
        WorkerManager: Worker manager instance
    """
    manager = WorkerManager(config)
    yield manager
    # Cleanup: stop any running processes
    manager.stop_all()


@pytest.fixture(scope='function')
def session_state_checker(temp_dir):
    """
    Fixture providing a session state checker script.
    
    Creates a mock session state checker script that outputs 'idle'.
    
    Args:
        temp_dir: Temporary directory fixture
        
    Yields:
        str: Path to the mock state checker script
    """
    script_path = os.path.join(temp_dir, 'mock_state_checker.py')
    script_content = '''#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Mock session state checker for testing"""
import os

# Always return idle for testing
print("idle")
'''
    with open(script_path, 'w') as f:
        f.write(script_content)
    os.chmod(script_path, stat.S_IRWXU)
    
    yield script_path


# ============================================================================
# Test Data Fixtures
# ============================================================================

@pytest.fixture(scope='function')
def sample_session(session_manager):
    """
    Fixture providing a sample session for testing.
    
    Creates a sample session with known session_id that can be used
    in tests. The session is automatically cleaned up after the test.
    
    Args:
        session_manager: Session manager fixture
        
    Yields:
        SessionData: Sample session data
    """
    session_id = 'test-session-sample'
    session_data = SessionData(
        session_id=session_id,
        session_name='Sample Test Session',
        task='Sample task for testing',
        create_time=datetime.now(),
        update_time=datetime.now(),
        processed_msg_id=None
    )
    
    # Create the session
    session_manager.create(session_data)
    
    yield session_data
    
    # Cleanup: delete the sample session if it exists
    try:
        session_manager.delete(session_id)
    except Exception:
        pass


@pytest.fixture(scope='function')
def sample_message(message_manager, sample_session):
    """
    Fixture providing a sample message for testing.
    
    Creates a sample message linked to the sample_session that can be used
    in tests. The message is automatically cleaned up after the test.
    
    Args:
        message_manager: Message manager fixture
        sample_session: Sample session fixture
        
    Yields:
        MessageData: Sample message data
    """
    msg_id = 'test-msg-sample'
    message_data = MessageData(
        msg_id=msg_id,
        session_id=sample_session.session_id,
        message='Sample message content for testing',
        create_time=datetime.now(),
        update_time=datetime.now(),
        task_id=None,
        task_result=None
    )
    
    # Create the message
    message_manager.create(message_data)
    
    yield message_data
    
    # Cleanup: delete the sample message if it exists
    try:
        message_manager.delete(msg_id, sample_session.session_id)
    except Exception:
        pass


@pytest.fixture(scope='function')
def sample_messages(message_manager):
    """
    Fixture providing multiple sample messages for testing.
    
    Creates multiple sample messages (not linked to a specific session fixture)
    that can be used in tests. The messages are automatically cleaned up.
    
    Args:
        message_manager: Message manager fixture
        
    Yields:
        list: List of MessageData objects
    """
    session_id = 'test-session-messages'
    messages = []
    
    # Create session first
    session_data = SessionData(
        session_id=session_id,
        session_name='Multiple Messages Test Session',
        task='Testing multiple messages',
        create_time=datetime.now(),
        update_time=datetime.now(),
        processed_msg_id=None
    )
    message_manager.session_manager.create(session_data)
    
    # Create multiple messages
    for i in range(5):
        msg_id = f'test-msg-{i}'
        msg_data = MessageData(
            msg_id=msg_id,
            session_id=session_id,
            message=f'Message {i} content for testing',
            create_time=datetime.now(),
            update_time=datetime.now(),
            task_id=None,
            task_result=None
        )
        message_manager.create(msg_data)
        messages.append(msg_data)
    
    yield messages
    
    # Cleanup: delete all messages and session
    try:
        for msg in messages:
            message_manager.delete(msg.msg_id, session_id)
    except Exception:
        pass
    
    try:
        message_manager.session_manager.delete(session_id)
    except Exception:
        pass


@pytest.fixture(scope='function')
def sample_task(message_manager, sample_session):
    """
    Fixture providing a sample task result for testing.
    
    Creates a sample message with task_id and task_result that can be used
    in tests. The message is automatically cleaned up after the test.
    
    Args:
        message_manager: Message manager fixture
        sample_session: Sample session fixture
        
    Yields:
        MessageData: Sample message with task data
    """
    msg_id = 'test-msg-task'
    message_data = MessageData(
        msg_id=msg_id,
        session_id=sample_session.session_id,
        message='Sample message that generates a task',
        create_time=datetime.now(),
        update_time=datetime.now(),
        task_id='test-task-123',
        task_result='Sample task result content'
    )
    
    # Create the message
    message_manager.create(message_data)
    
    yield message_data
    
    # Cleanup: delete the sample message if it exists
    try:
        message_manager.delete(msg_id, sample_session.session_id)
    except Exception:
        pass


@pytest.fixture(scope='function')
def sample_session_with_messages(session_manager, message_manager):
    """
    Fixture providing a session with multiple messages for testing.
    
    Creates a session with multiple messages that can be used to test
    message processing and session state checking.
    
    Args:
        session_manager: Session manager fixture
        message_manager: Message manager fixture
        
    Yields:
        dict: Dictionary containing session and messages
    """
    session_id = 'test-session-multi-msg'
    session_data = SessionData(
        session_id=session_id,
        session_name='Multi Message Test Session',
        task='Testing multiple messages',
        create_time=datetime.now(),
        update_time=datetime.now(),
        processed_msg_id=None
    )
    
    # Create session
    session_manager.create(session_data)
    
    # Create multiple messages
    messages = []
    for i in range(3):
        msg_id = f'test-msg-{i}'
        msg_data = MessageData(
            msg_id=msg_id,
            session_id=session_id,
            message=f'Message {i} content',
            create_time=datetime.now(),
            update_time=datetime.now(),
            task_id=None,
            task_result=None
        )
        message_manager.create(msg_data)
        messages.append(msg_data)
    
    yield {
        'session': session_data,
        'messages': messages
    }
    
    # Cleanup: delete all messages and session
    try:
        for msg in messages:
            message_manager.delete(msg.msg_id, session_id)
    except Exception:
        pass
    
    try:
        session_manager.delete(session_id)
    except Exception:
        pass


# ============================================================================
# Utility Fixtures
# ============================================================================

@pytest.fixture(scope='function')
def temp_dir():
    """
    Fixture providing a temporary directory for test files.
    
    Creates a temporary directory that is cleaned up after the test.
    
    Yields:
        str: Path to the temporary directory
    """
    tmpdir = tempfile.mkdtemp()
    
    yield tmpdir
    
    # Cleanup: remove temporary directory and contents
    import shutil
    if os.path.exists(tmpdir):
        shutil.rmtree(tmpdir)


@pytest.fixture(scope='function')
def mock_processor_script(temp_dir):
    """
    Fixture providing a mock processor script.
    
    Creates an executable mock processor script that simulates
    the real processor. It reads environment variables and outputs
    a simple response.
    
    Args:
        temp_dir: Temporary directory fixture
        
    Yields:
        str: Path to the mock processor script
    """
    script_path = os.path.join(temp_dir, 'mock_processor.py')
    script_content = '''#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Mock processor script for testing"""
import os
import sys

# Read environment variables
msg_id = os.environ.get('TOPSAILAI_MSG_ID', '')
session_id = os.environ.get('TOPSAILAI_SESSION_ID', '')
task = os.environ.get('TOPSAILAI_TASK', '')

# Check if this should generate a task result
task_id = os.environ.get('TOPSAILAI_TASK_ID')

if task_id:
    # Write task result
    print(f"TASK_RESULT:Processed task {task_id}")
    sys.exit(0)
else:
    # Direct answer
    print(f"MESSAGE:Processed message {msg_id}")
    sys.exit(0)
'''
    with open(script_path, 'w') as f:
        f.write(script_content)
    os.chmod(script_path, stat.S_IRWXU)
    
    yield script_path


@pytest.fixture(scope='function')
def mock_summarizer_script(temp_dir):
    """
    Fixture providing a mock summarizer script.
    
    Creates an executable mock summarizer script that simulates
    the real summarizer. It reads environment variables and outputs
    a summary.
    
    Args:
        temp_dir: Temporary directory fixture
        
    Yields:
        str: Path to the mock summarizer script
    """
    script_path = os.path.join(temp_dir, 'mock_summarizer.py')
    script_content = '''#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Mock summarizer script for testing"""
import os

# Read environment variables
session_id = os.environ.get('TOPSAILAI_SESSION_ID', '')
task = os.environ.get('TOPSAILAI_TASK', '')

# Output summary
print(f"SUMMARY:Summary for session {session_id}")
'''
    with open(script_path, 'w') as f:
        f.write(script_content)
    os.chmod(script_path, stat.S_IRWXU)
    
    yield script_path


@pytest.fixture(scope='function')
def mock_state_checker_script(temp_dir):
    """
    Fixture providing a mock state checker script.
    
    Creates an executable mock state checker script that outputs 'idle'.
    
    Args:
        temp_dir: Temporary directory fixture
        
    Yields:
        str: Path to the mock state checker script
    """
    script_path = os.path.join(temp_dir, 'mock_state_checker.py')
    script_content = '''#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Mock session state checker for testing"""
import os

# Always return idle for testing
print("idle")
'''
    with open(script_path, 'w') as f:
        f.write(script_content)
    os.chmod(script_path, stat.S_IRWXU)
    
    yield script_path