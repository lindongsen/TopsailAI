"""
Pytest fixtures for integration tests
"""

import pytest
import os
import sys
import uuid
import tempfile
import subprocess
import time
import signal
from datetime import datetime
from pathlib import Path

# Add the parent directory to the path for imports
sys.path.insert(0, '/root/ai/TopsailAI/src')

# Integration test directory
INTEGRATION_DIR = '/root/ai/TopsailAI/src/topsailai_server/agent_daemon/tests/integration'
WORKSPACE_DIR = '/root/ai/TopsailAI/src/topsailai_server/agent_daemon'


def pytest_addoption(parser):
    """Add custom command-line options"""
    parser.addoption(
        "--start-server",
        action="store_true",
        default=False,
        help="Automatically start the agent daemon server for integration tests"
    )


def is_server_running():
    """Check if the server is running by checking port 7373"""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    try:
        result = sock.connect_ex(('127.0.0.1', 7373))
        sock.close()
        return result == 0
    except Exception:
        return False


def start_server():
    """Start the agent daemon server"""
    workspace = Path(WORKSPACE_DIR)
    daemon_script = workspace / "topsailai_agent_daemon.py"
    scripts_dir = workspace / "scripts"
    
    # Ensure scripts exist
    processor = scripts_dir / "processor.sh"
    summarizer = scripts_dir / "summarizer.sh"
    state_checker = scripts_dir / "session_state_checker.py"
    
    # Prepare environment
    env = os.environ.copy()
    env["HOME"] = INTEGRATION_DIR
    
    # Database path - use absolute path for the test database
    db_url = f"sqlite:///{os.path.join(INTEGRATION_DIR, 'test.db')}"
    
    # Start server
    proc = subprocess.Popen(
        [
            sys.executable,
            str(daemon_script),
            "start",
            "--processor", str(processor),
            "--summarizer", str(summarizer),
            "--session_state_checker", str(state_checker),
            "--db_url", db_url
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=os.setsid if hasattr(os, 'setsid') else None
    )
    
    # Wait for server to be ready (max 30 seconds)
    max_wait = 30
    for i in range(max_wait):
        if is_server_running():
            return proc
        time.sleep(1)
    
    # Server didn't start in time, terminate and raise
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    raise RuntimeError("Server failed to start within 30 seconds")


def stop_server():
    """Stop the agent daemon server gracefully"""
    workspace = Path(WORKSPACE_DIR)
    daemon_script = workspace / "topsailai_agent_daemon.py"
    
    # Try graceful stop first
    try:
        subprocess.run(
            [sys.executable, str(daemon_script), "stop"],
            timeout=10,
            capture_output=True
        )
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        pass
    
    # Force kill if still running
    if is_server_running():
        try:
            # Find and kill process on port 7373
            result = subprocess.run(
                ["lsof", "-ti", ":7373"],
                capture_output=True,
                text=True
            )
            if result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    try:
                        os.kill(int(pid), signal.SIGKILL)
                    except (ValueError, ProcessLookupError, PermissionError):
                        pass
        except Exception:
            pass
    
    # Wait for port to be released
    time.sleep(1)


@pytest.fixture(scope="session")
def require_server(request):
    """
    Fixture to ensure server is running for tests.
    If --start-server flag is provided, automatically starts the server.
    Otherwise, skips tests if server is not running.
    """
    auto_start = request.config.getoption("--start-server", default=False)
    server_proc = None
    
    if not is_server_running():
        if auto_start:
            # Start server automatically
            server_proc = start_server()
            # Register cleanup to stop server after all tests
            request.addfinalizer(stop_server)
        else:
            pytest.skip("Server not running. Use --start-server flag to auto-start or start manually with: ./topsailai_agent_daemon.py start")
    else:
        # Server is already running, register cleanup only if we started it
        if auto_start:
            # We might have started it in a previous fixture, check if we need cleanup
            pass
    
    yield
    
    # Cleanup is handled by addfinalizer


@pytest.fixture
def session_id():
    """Generate a unique session ID for testing"""
    return f"test-session-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def message():
    """Default test message"""
    return "This is a test message for integration testing"


@pytest.fixture
def role():
    """Default role for message"""
    return "user"


@pytest.fixture(scope='function')
def temp_db_path():
    """Create a temporary database path for each test"""
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    yield path
    # Cleanup
    try:
        os.unlink(path)
    except Exception:
        pass


@pytest.fixture(scope='function')
def mock_processor_script():
    """Path to mock processor script"""
    return os.path.join(INTEGRATION_DIR, 'mock_processor.sh')


@pytest.fixture(scope='function')
def mock_summarizer_script():
    """Path to mock summarizer script"""
    return os.path.join(INTEGRATION_DIR, 'mock_summarizer.sh')


@pytest.fixture(scope='function')
def mock_state_checker_script():
    """Path to mock state checker script"""
    return os.path.join(INTEGRATION_DIR, 'mock_state_checker.sh')
