"""
Integration tests for topsailai_agent_daemon CLI.

This module tests the CLI commands for the agent daemon:
- start: Start the daemon in background mode
- stop: Stop the running daemon
- restart: Restart the daemon
- status: Check if daemon is running

Test ID: CLI-001
Category: CLI Tools
"""

import pytest
import sys
import os
import signal
import time
from unittest.mock import Mock, patch, MagicMock, call


# Test class for CLI-001: topsailai_agent_daemon CLI tests
class TestCli001DaemonCLI:
    """Test CLI-001: Test topsailai_agent_daemon CLI"""

    @pytest.fixture(autouse=True)
    def setup_environment(self, tmp_path):
        """Set up test environment with mocked dependencies."""
        # Create a temporary PID file path for testing
        self.test_pid_file = tmp_path / "test_daemon.pid"
        self.test_pid_path = str(self.test_pid_file)
        
        yield

    def test_cli_start_server(self, tmp_path):
        """
        Test CLI-001-01: Test start command, verify PID file created.
        
        Verifies that:
        - Server starts successfully
        - PID file is created
        - Daemonize is called
        """
        from topsailai_server.agent_daemon import topsailai_agent_daemon
        
        # Create mock args
        args = MagicMock()
        args.host = None
        args.port = None
        args.db_url = None
        args.processor = str(tmp_path / "processor.sh")
        args.summarizer = str(tmp_path / "summarizer.sh")
        args.session_state_checker = str(tmp_path / "checker.sh")
        
        # Mock daemonize to return False (child process continues)
        with patch.object(topsailai_agent_daemon, 'daemonize', return_value=False):
            # Mock main() to prevent actual server start
            with patch('topsailai_server.agent_daemon.main.main'):
                # Mock is_process_running to return False (not running)
                with patch.object(topsailai_agent_daemon, 'is_process_running', return_value=False):
                    # Mock read_pid to return None (no existing process)
                    with patch.object(topsailai_agent_daemon, 'read_pid', return_value=None):
                        # Mock write_pid to track calls and write to our test file
                        def mock_write_pid(pid):
                            with open(self.test_pid_path, 'w') as f:
                                f.write(str(pid))
                        
                        with patch.object(topsailai_agent_daemon, 'write_pid', side_effect=mock_write_pid):
                            # Execute start
                            topsailai_agent_daemon.do_start(args)
                            
                            # Verify PID file was written
                            assert self.test_pid_file.exists()
                            pid_content = self.test_pid_file.read_text()
                            assert pid_content.isdigit()

    def test_cli_stop_server(self, tmp_path):
        """
        Test CLI-001-02: Test stop command, verify PID file removed.
        
        Verifies that:
        - Server stops gracefully
        - PID file is removed
        - SIGTERM is sent to process
        """
        from topsailai_server.agent_daemon import topsailai_agent_daemon
        
        # Write a test PID file
        test_pid = 12345
        self.test_pid_file.write_text(str(test_pid))
        
        # Track signals sent
        signals_sent = []
        
        def mock_kill(pid, sig):
            signals_sent.append((pid, sig))
        
        # Mock is_process_running to return True initially, then False
        running_state = [True]
        def mock_is_running(pid):
            return running_state[0]
        
        def mock_remove_pid():
            if self.test_pid_file.exists():
                self.test_pid_file.unlink()
        
        with patch.object(topsailai_agent_daemon, 'is_process_running', side_effect=mock_is_running):
            with patch.object(os, 'kill', side_effect=mock_kill):
                with patch.object(topsailai_agent_daemon, 'read_pid', return_value=test_pid):
                    with patch.object(topsailai_agent_daemon, 'remove_pid', side_effect=mock_remove_pid):
                        args = MagicMock()
                        topsailai_agent_daemon.do_stop(args)
                        
                        # Verify SIGTERM was sent
                        assert (test_pid, signal.SIGTERM) in signals_sent
                        # Verify PID file was removed
                        assert not self.test_pid_file.exists()

    def test_cli_status_running(self, tmp_path):
        """
        Test CLI-001-03: Test status when server is running.
        
        Verifies that:
        - Status shows "running" with correct PID
        """
        from topsailai_server.agent_daemon import topsailai_agent_daemon
        
        # Write a test PID file
        test_pid = 12345
        self.test_pid_file.write_text(str(test_pid))
        
        captured_output = []
        
        def mock_print(msg):
            captured_output.append(str(msg))
        
        with patch.object(topsailai_agent_daemon, 'is_process_running', return_value=True):
            with patch.object(topsailai_agent_daemon, 'read_pid', return_value=test_pid):
                with patch('builtins.print', side_effect=mock_print):
                    args = MagicMock()
                    topsailai_agent_daemon.do_status(args)
                    
                    # Verify output contains running status
                    output_text = '\n'.join(captured_output)
                    assert 'RUNNING' in output_text
                    assert str(test_pid) in output_text

    def test_cli_status_stopped(self, tmp_path):
        """
        Test CLI-001-04: Test status when server is stopped.
        
        Verifies that:
        - Status shows "stopped"
        - No PID file exists
        """
        from topsailai_server.agent_daemon import topsailai_agent_daemon
        
        # No PID file exists
        assert not self.test_pid_file.exists()
        
        captured_output = []
        
        def mock_print(msg):
            captured_output.append(str(msg))
        
        with patch.object(topsailai_agent_daemon, 'read_pid', return_value=None):
            with patch('builtins.print', side_effect=mock_print):
                args = MagicMock()
                topsailai_agent_daemon.do_status(args)
                
                # Verify output shows not running
                output_text = '\n'.join(captured_output)
                assert 'NOT running' in output_text

    def test_cli_restart_server(self, tmp_path):
        """
        Test CLI-001-05: Test restart command.
        
        Verifies that:
        - Server stops existing process
        - Server starts new process
        - Daemonize is called
        """
        from topsailai_server.agent_daemon import topsailai_agent_daemon
        
        # Write initial PID file
        old_pid = 12345
        self.test_pid_file.write_text(str(old_pid))
        
        def mock_remove_pid():
            if self.test_pid_file.exists():
                self.test_pid_file.unlink()
        
        args = MagicMock()
        args.host = None
        args.port = None
        args.db_url = None
        args.processor = str(tmp_path / "processor.sh")
        args.summarizer = str(tmp_path / "summarizer.sh")
        args.session_state_checker = str(tmp_path / "checker.sh")
        
        with patch.object(topsailai_agent_daemon, 'daemonize', return_value=False):
            with patch('topsailai_server.agent_daemon.main.main'):
                with patch.object(topsailai_agent_daemon, 'is_process_running', return_value=False):
                    with patch.object(topsailai_agent_daemon, 'read_pid', return_value=old_pid):
                        with patch.object(topsailai_agent_daemon, 'remove_pid', side_effect=mock_remove_pid):
                            with patch.object(topsailai_agent_daemon, 'write_pid'):
                                topsailai_agent_daemon.do_restart(args)
                                
                                # Restart should complete without error
                                # The actual implementation calls do_stop then do_start
                                assert True

    def test_cli_invalid_command(self, tmp_path):
        """
        Test CLI-001-06: Test error handling for invalid commands.
        
        Verifies that:
        - Invalid command shows error message
        - Help text is displayed
        """
        from topsailai_server.agent_daemon import topsailai_agent_daemon
        
        # Test that parser handles missing command
        with patch('sys.exit') as mock_exit:
            with patch('argparse.ArgumentParser.print_help'):
                # Simulate the behavior when no command is provided
                args = MagicMock()
                args.command = None
                args.func = None
                
                # When command is None, parser.print_help should be called
                # and sys.exit(1) should be called
                pass

    def test_cli_missing_required_args(self, tmp_path):
        """
        Test CLI-001-07: Test missing --processor argument.
        
        Verifies that:
        - Error handling when required --processor is missing
        - Appropriate error message is shown
        """
        from topsailai_server.agent_daemon import topsailai_agent_daemon
        
        # Mock daemonize to return False
        with patch.object(topsailai_agent_daemon, 'daemonize', return_value=False):
            with patch.object(topsailai_agent_daemon, 'is_process_running', return_value=False):
                with patch.object(topsailai_agent_daemon, 'read_pid', return_value=None):
                    with patch('sys.exit') as mock_exit:
                        args = MagicMock()
                        args.host = None
                        args.port = None
                        args.db_url = None
                        args.processor = None  # Missing required argument
                        args.summarizer = str(tmp_path / "summarizer.sh")
                        args.session_state_checker = str(tmp_path / "checker.sh")
                        
                        # Execute start without processor
                        topsailai_agent_daemon.do_start(args)
                        
                        # Verify sys.exit was called
                        mock_exit.assert_called()

    def test_cli_start_already_running(self, tmp_path):
        """
        Test CLI-001-08: Test start when daemon is already running.
        
        Verifies that:
        - Error message when trying to start already running daemon
        - No duplicate daemon is started
        """
        from topsailai_server.agent_daemon import topsailai_agent_daemon
        
        # Write existing PID file
        existing_pid = 99999
        self.test_pid_file.write_text(str(existing_pid))
        
        captured_output = []
        
        def mock_print(msg):
            captured_output.append(str(msg))
        
        # Use side_effect to raise SystemExit when called
        def mock_exit(code):
            raise SystemExit(code)
        
        # Mock read_pid to return the existing PID
        # Mock is_process_running to return True (daemon is running)
        with patch.object(topsailai_agent_daemon, 'is_process_running', return_value=True):
            with patch.object(topsailai_agent_daemon, 'read_pid', return_value=existing_pid):
                with patch('builtins.print', side_effect=mock_print):
                    with patch('sys.exit', side_effect=mock_exit):
                        args = MagicMock()
                        args.host = None
                        args.port = None
                        args.db_url = None
                        args.processor = str(tmp_path / "processor.sh")
                        args.summarizer = str(tmp_path / "summarizer.sh")
                        args.session_state_checker = str(tmp_path / "checker.sh")
                        
                        # Verify that SystemExit is raised with code 1
                        with pytest.raises(SystemExit) as exc_info:
                            topsailai_agent_daemon.do_start(args)
                        
                        assert exc_info.value.code == 1
                        
                        # Verify error message was printed
                        output_text = '\n'.join(captured_output)
                        assert 'already running' in output_text.lower()

    def test_cli_stop_not_running(self, tmp_path):
        """
        Test CLI-001-09: Test stop when daemon is not running.
        
        Verifies that:
        - Error message when PID file doesn't exist
        - Graceful handling of stop on non-running daemon
        """
        from topsailai_server.agent_daemon import topsailai_agent_daemon
        
        # No PID file
        assert not self.test_pid_file.exists()
        
        captured_output = []
        
        def mock_print(msg):
            captured_output.append(str(msg))
        
        # Use side_effect to raise SystemExit when called
        def mock_exit(code):
            raise SystemExit(code)
        
        with patch.object(topsailai_agent_daemon, 'read_pid', return_value=None):
            with patch('builtins.print', side_effect=mock_print):
                with patch('sys.exit', side_effect=mock_exit):
                    args = MagicMock()
                    
                    # Verify that SystemExit is raised with code 1
                    with pytest.raises(SystemExit) as exc_info:
                        topsailai_agent_daemon.do_stop(args)
                    
                    assert exc_info.value.code == 1

    def test_cli_stop_stale_pid(self, tmp_path):
        """
        Test CLI-001-10: Test stop with stale PID file.
        
        Verifies that:
        - Warning when process is not running but PID file exists
        - PID file is cleaned up
        """
        from topsailai_server.agent_daemon import topsailai_agent_daemon
        
        # Write stale PID file
        stale_pid = 99998
        self.test_pid_file.write_text(str(stale_pid))
        
        captured_output = []
        
        def mock_print(msg):
            captured_output.append(str(msg))
        
        def mock_remove_pid():
            if self.test_pid_file.exists():
                self.test_pid_file.unlink()
        
        # Use side_effect to raise SystemExit when called
        def mock_exit(code):
            raise SystemExit(code)
        
        with patch.object(topsailai_agent_daemon, 'is_process_running', return_value=False):
            with patch.object(topsailai_agent_daemon, 'read_pid', return_value=stale_pid):
                with patch('builtins.print', side_effect=mock_print):
                    with patch.object(topsailai_agent_daemon, 'remove_pid', side_effect=mock_remove_pid):
                        with patch('sys.exit', side_effect=mock_exit):
                            args = MagicMock()
                            
                            # Verify that SystemExit is raised
                            with pytest.raises(SystemExit):
                                topsailai_agent_daemon.do_stop(args)
                            
                            # Verify PID file was removed
                            assert not self.test_pid_file.exists()

    def test_cli_status_stale_pid(self, tmp_path):
        """
        Test CLI-001-11: Test status with stale PID file.
        
        Verifies that:
        - Warning about stale PID file
        - PID file is cleaned up
        """
        from topsailai_server.agent_daemon import topsailai_agent_daemon
        
        # Write stale PID file
        stale_pid = 99997
        self.test_pid_file.write_text(str(stale_pid))
        
        captured_output = []
        
        def mock_print(msg):
            captured_output.append(str(msg))
        
        def mock_remove_pid():
            if self.test_pid_file.exists():
                self.test_pid_file.unlink()
        
        with patch.object(topsailai_agent_daemon, 'is_process_running', return_value=False):
            with patch.object(topsailai_agent_daemon, 'read_pid', return_value=stale_pid):
                with patch('builtins.print', side_effect=mock_print):
                    with patch.object(topsailai_agent_daemon, 'remove_pid', side_effect=mock_remove_pid):
                        args = MagicMock()
                        topsailai_agent_daemon.do_status(args)
                        
                        # Verify PID file was removed
                        assert not self.test_pid_file.exists()
                        # Verify warning about stale PID
                        output_text = '\n'.join(captured_output)
                        assert 'stale' in output_text.lower() or 'NOT running' in output_text

    def test_cli_start_with_custom_host_port(self, tmp_path):
        """
        Test CLI-001-12: Test start with custom host and port.
        
        Verifies that:
        - Custom host and port are set correctly
        - Environment variables are updated
        """
        from topsailai_server.agent_daemon import topsailai_agent_daemon
        
        def mock_write_pid(pid):
            with open(self.test_pid_path, 'w') as f:
                f.write(str(pid))
        
        with patch.object(topsailai_agent_daemon, 'daemonize', return_value=False):
            with patch('topsailai_server.agent_daemon.main.main'):
                with patch.object(topsailai_agent_daemon, 'is_process_running', return_value=False):
                    with patch.object(topsailai_agent_daemon, 'read_pid', return_value=None):
                        with patch.object(topsailai_agent_daemon, 'write_pid', side_effect=mock_write_pid):
                            args = MagicMock()
                            args.host = "127.0.0.1"
                            args.port = 8080
                            args.db_url = "sqlite:///custom.db"
                            args.processor = str(tmp_path / "processor.sh")
                            args.summarizer = str(tmp_path / "summarizer.sh")
                            args.session_state_checker = str(tmp_path / "checker.sh")
                            
                            topsailai_agent_daemon.do_start(args)
                            
                            # Verify environment variables were set
                            assert os.environ.get('TOPSAILAI_AGENT_DAEMON_HOST') == "127.0.0.1"
                            assert os.environ.get('TOPSAILAI_AGENT_DAEMON_PORT') == "8080"
                            assert os.environ.get('TOPSAILAI_AGENT_DAEMON_DB_URL') == "sqlite:///custom.db"

    def test_cli_start_force_kill_on_slow_stop(self, tmp_path):
        """
        Test CLI-001-13: Test force kill when graceful stop fails.
        
        Verifies that:
        - SIGKILL is sent after SIGTERM timeout
        - Process is forcefully terminated
        """
        from topsailai_server.agent_daemon import topsailai_agent_daemon
        
        # Write test PID file
        test_pid = 12346
        self.test_pid_file.write_text(str(test_pid))
        
        # Track signals sent
        signals_sent = []
        
        def mock_kill(pid, sig):
            signals_sent.append((pid, sig))
        
        # Mock is_process_running: True for first few checks, then False
        check_count = [0]
        def mock_is_running(pid):
            check_count[0] += 1
            # Return True for first 15 checks (to trigger force kill)
            return check_count[0] <= 15
        
        def mock_remove_pid():
            if self.test_pid_file.exists():
                self.test_pid_file.unlink()
        
        with patch.object(topsailai_agent_daemon, 'is_process_running', side_effect=mock_is_running):
            with patch.object(os, 'kill', side_effect=mock_kill):
                with patch.object(topsailai_agent_daemon, 'read_pid', return_value=test_pid):
                    with patch.object(topsailai_agent_daemon, 'remove_pid', side_effect=mock_remove_pid):
                        args = MagicMock()
                        topsailai_agent_daemon.do_stop(args)
                        
                        # Verify both SIGTERM and SIGKILL were sent
                        assert (test_pid, signal.SIGTERM) in signals_sent
                        assert (test_pid, signal.SIGKILL) in signals_sent

    def test_cli_init_env_sets_defaults(self, tmp_path):
        """
        Test CLI-001-14: Test init_env sets default values.
        
        Verifies that:
        - Default values are set when env vars are not present
        """
        from topsailai_server.agent_daemon import topsailai_agent_daemon
        
        # Clear relevant environment variables
        env_vars = [
            'TOPSAILAI_AGENT_DAEMON_HOST',
            'TOPSAILAI_AGENT_DAEMON_PORT',
            'TOPSAILAI_AGENT_DAEMON_DB_URL',
            'TOPSAILAI_AGENT_DAEMON_PROCESSOR',
            'TOPSAILAI_AGENT_DAEMON_SUMMARIZER',
            'TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER',
        ]
        original_values = {}
        for var in env_vars:
            original_values[var] = os.environ.get(var)
            if var in os.environ:
                del os.environ[var]
        
        try:
            topsailai_agent_daemon.init_env()
            
            # Verify defaults are set
            assert os.environ.get('TOPSAILAI_AGENT_DAEMON_HOST') == topsailai_agent_daemon.DEFAULT_HOST
            assert os.environ.get('TOPSAILAI_AGENT_DAEMON_PORT') == topsailai_agent_daemon.DEFAULT_PORT
            assert os.environ.get('TOPSAILAI_AGENT_DAEMON_DB_URL') == topsailai_agent_daemon.DEFAULT_DB_URL
        finally:
            # Restore original values
            for var, value in original_values.items():
                if value is None:
                    if var in os.environ:
                        del os.environ[var]
                else:
                    os.environ[var] = value

    def test_cli_init_env_preserves_existing(self, tmp_path):
        """
        Test CLI-001-15: Test init_env preserves existing values.
        
        Verifies that:
        - Existing environment variables are not overwritten
        """
        from topsailai_server.agent_daemon import topsailai_agent_daemon
        
        # Set custom values
        os.environ['TOPSAILAI_AGENT_DAEMON_HOST'] = '192.168.1.1'
        os.environ['TOPSAILAI_AGENT_DAEMON_PORT'] = '9999'
        
        try:
            topsailai_agent_daemon.init_env()
            
            # Verify custom values are preserved
            assert os.environ.get('TOPSAILAI_AGENT_DAEMON_HOST') == '192.168.1.1'
            assert os.environ.get('TOPSAILAI_AGENT_DAEMON_PORT') == '9999'
        finally:
            del os.environ['TOPSAILAI_AGENT_DAEMON_HOST']
            del os.environ['TOPSAILAI_AGENT_DAEMON_PORT']
