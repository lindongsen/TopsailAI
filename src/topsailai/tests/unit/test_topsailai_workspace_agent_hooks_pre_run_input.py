"""
Unit tests for workspace/agent/hooks/pre_run_input module.

Test coverage:
- pre_run_set_agent_runtime_input function
- input_on_agent_runtime wrapper
- input_on_agent_runtime_with_timeout wrapper
- HookInstruction integration

Author: mm-m25
"""

import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, MagicMock

import pytest


class TestPreRunSetAgentRuntimeInput(unittest.TestCase):
    """Test cases for pre_run_set_agent_runtime_input function."""

    def setUp(self):
        """Clear thread-local input state before each test."""
        from topsailai.utils.thread_local_tool import rid_all_thread_vars
        rid_all_thread_vars()

    def tearDown(self):
        """Clear thread-local input state after each test."""
        from topsailai.utils.thread_local_tool import rid_all_thread_vars
        rid_all_thread_vars()

    def test_registers_input_on_agent_runtime(self):
        """Test pre_run hook registers input_on_agent_runtime in thread-local."""
        from topsailai.workspace.agent.hooks.pre_run_input import (
            pre_run_set_agent_runtime_input,
        )
        from topsailai.utils.thread_local_tool import (
            get_agent_runtime_input,
            get_agent_runtime_input_with_timeout,
        )

        mock_agent = MagicMock()
        mock_agent.hook_instruction = None

        pre_run_set_agent_runtime_input(mock_agent)

        self.assertIsNotNone(get_agent_runtime_input())
        self.assertIsNotNone(get_agent_runtime_input_with_timeout())

    def test_plain_wrapper_forwards_tips(self):
        """Test input_on_agent_runtime forwards tips to input_one_line."""
        from topsailai.workspace.agent.hooks.pre_run_input import (
            pre_run_set_agent_runtime_input,
        )
        from topsailai.utils.thread_local_tool import get_agent_runtime_input

        mock_agent = MagicMock()
        mock_agent.hook_instruction = MagicMock()

        with patch(
            "topsailai.workspace.agent.hooks.pre_run_input.input_one_line"
        ) as mock_input_one_line:
            mock_input_one_line.return_value = "user input"
            pre_run_set_agent_runtime_input(mock_agent)

            input_func = get_agent_runtime_input()
            result = input_func("Enter something: ")

            self.assertEqual(result, "user input")
            mock_input_one_line.assert_called_once_with(
                tips="Enter something: ", hook=mock_agent.hook_instruction
            )

    def test_timeout_wrapper_forwards_tips_and_timeout(self):
        """Test input_on_agent_runtime_with_timeout forwards tips and timeout."""
        from topsailai.workspace.agent.hooks.pre_run_input import (
            pre_run_set_agent_runtime_input,
        )
        from topsailai.utils.thread_local_tool import (
            get_agent_runtime_input_with_timeout,
        )

        mock_agent = MagicMock()
        mock_agent.hook_instruction = MagicMock()

        with patch(
            "topsailai.workspace.agent.hooks.pre_run_input.input_from_pipe_session"
        ) as mock_input_from_pipe_session:
            mock_input_from_pipe_session.return_value = "user input"
            pre_run_set_agent_runtime_input(mock_agent)

            input_func = get_agent_runtime_input_with_timeout()
            result = input_func("Enter something: ", timeout=5.0)

            self.assertEqual(result, "user input")
            mock_input_from_pipe_session.assert_called_once_with(
                session_id=None,
                single_line=True,
                timeout=5.0,
                prompt="Enter something: ",
            )

    def test_timeout_wrapper_uses_default_timeout(self):
        """Test input_on_agent_runtime_with_timeout uses default timeout."""
        from topsailai.workspace.agent.hooks.pre_run_input import (
            pre_run_set_agent_runtime_input,
        )
        from topsailai.utils.thread_local_tool import (
            get_agent_runtime_input_with_timeout,
        )

        mock_agent = MagicMock()
        mock_agent.hook_instruction = MagicMock()

        with patch(
            "topsailai.workspace.agent.hooks.pre_run_input.input_from_pipe_session"
        ) as mock_input_from_pipe_session:
            mock_input_from_pipe_session.return_value = "user input"
            pre_run_set_agent_runtime_input(mock_agent)

            input_func = get_agent_runtime_input_with_timeout()
            result = input_func("Enter something: ")

            self.assertEqual(result, "user input")
            mock_input_from_pipe_session.assert_called_once_with(
                session_id=None,
                single_line=True,
                timeout=None,
                prompt="Enter something: ",
            )


class TestPreRunInputToolApprovalTransport(unittest.TestCase):
    """Tests demonstrating that the timeout-aware wrapper is consumed by the
    tool-approval local transport, but not by the agent interactive step or
    LLM retry paths.
    """

    def setUp(self):
        """Clear thread-local input state."""
        from topsailai.utils.thread_local_tool import rid_all_thread_vars
        rid_all_thread_vars()

    def tearDown(self):
        """Clear thread-local input state."""
        from topsailai.utils.thread_local_tool import rid_all_thread_vars
        rid_all_thread_vars()

    @patch(
        "topsailai.workspace.agent.hooks.pre_run_input.input_from_pipe_session"
    )
    def test_tool_approval_transport_uses_timeout_wrapper(self, mock_input_from_pipe):
        """LocalApprovalTransport._read_stdin_input uses the timeout-aware
        agent-runtime input function registered by the pre_run hook.
        """
        from topsailai.workspace.agent.hooks.pre_run_input import (
            pre_run_set_agent_runtime_input,
        )
        from topsailai.ai_base.tool_approval.transport import LocalApprovalTransport
        from topsailai.ai_base.tool_approval.instance import ToolApprovalInstance

        mock_agent = MagicMock()
        mock_agent.hook_instruction = MagicMock()
        mock_input_from_pipe.return_value = "approve"

        pre_run_set_agent_runtime_input(mock_agent)

        transport = LocalApprovalTransport()
        instance = ToolApprovalInstance(
            tool_name="cmd_tool-exec_cmd",
            tool_args={"cmd": "echo hello"},
            transport=transport,
        )
        instance.timeout = 7.0

        transport._read_stdin_input(instance)

        self.assertEqual(instance.status, instance.STATUS_APPROVED)
        mock_input_from_pipe.assert_called_once_with(
            session_id=None,
            single_line=True,
            timeout=7.0,
            prompt=unittest.mock.ANY,
        )

    def test_tool_approval_transport_falls_back_to_input_with_timeout(self):
        """When the timeout-aware function is not registered,
        LocalApprovalTransport falls back to input_with_timeout.
        """
        from topsailai.ai_base.tool_approval.transport import LocalApprovalTransport
        from topsailai.ai_base.tool_approval.instance import ToolApprovalInstance

        transport = LocalApprovalTransport()
        instance = ToolApprovalInstance(
            tool_name="cmd_tool-exec_cmd",
            tool_args={"cmd": "echo hello"},
            transport=transport,
        )
        instance.timeout = 3.0

        with patch(
            "topsailai.utils.input_tool.input_with_timeout",
            return_value="deny",
        ) as mock_input_with_timeout:
            transport._read_stdin_input(instance)

        self.assertEqual(instance.status, instance.STATUS_DENIED)
        mock_input_with_timeout.assert_called_once()
        call_kwargs = mock_input_with_timeout.call_args.kwargs
        self.assertIn("timeout", call_kwargs)
        self.assertEqual(call_kwargs["timeout"], 3.0)


class TestPreRunTimeoutWrapperRealPipe(unittest.TestCase):
    """Real FIFO tests for input_on_agent_runtime_with_timeout."""

    def setUp(self):
        """Clear thread-local input state before each test."""
        from topsailai.utils.thread_local_tool import rid_all_thread_vars
        rid_all_thread_vars()

    def tearDown(self):
        """Clear thread-local input state after each test."""
        from topsailai.utils.thread_local_tool import rid_all_thread_vars
        rid_all_thread_vars()

    def _write_to_pipe(self, pipe_path: str, payload: str, delay: float = 0.02):
        """Start a daemon thread that writes *payload* to *pipe_path*."""
        import errno

        def writer():
            time.sleep(delay)
            fd = None
            for _ in range(100):
                try:
                    fd = os.open(pipe_path, os.O_WRONLY | os.O_NONBLOCK)
                    break
                except FileNotFoundError:
                    time.sleep(0.01)
                except OSError as exc:
                    if exc.errno == errno.ENXIO:
                        time.sleep(0.01)
                    else:
                        raise
            if fd is None:
                return
            try:
                os.write(fd, payload.encode("utf-8"))
            finally:
                os.close(fd)

        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        return thread

    def test_timeout_wrapper_times_out_on_real_pipe(self):
        """The wrapper actually raises TimeoutError when no data arrives."""
        from topsailai.workspace.agent.hooks.pre_run_input import (
            pre_run_set_agent_runtime_input,
        )
        from topsailai.utils.thread_local_tool import (
            get_agent_runtime_input_with_timeout,
        )
        from topsailai.utils import env_tool

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("topsailai.workspace.input_tool.FOLDER_WORKSPACE_TASK", tmpdir):
                mock_agent = MagicMock()
                mock_agent.hook_instruction = MagicMock()
                pre_run_set_agent_runtime_input(mock_agent)

                input_func = get_agent_runtime_input_with_timeout()
                start = time.monotonic()
                with pytest.raises(TimeoutError):
                    input_func("prompt", timeout=0.1)
                elapsed = time.monotonic() - start

                self.assertGreaterEqual(elapsed, 0.08)
                self.assertLess(elapsed, 0.3)

    def test_timeout_wrapper_returns_data_before_timeout(self):
        """The wrapper returns pipe data when it arrives before timeout."""
        from topsailai.workspace.agent.hooks.pre_run_input import (
            pre_run_set_agent_runtime_input,
        )
        from topsailai.utils.thread_local_tool import (
            get_agent_runtime_input_with_timeout,
        )
        from topsailai.utils import env_tool

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("topsailai.workspace.input_tool.FOLDER_WORKSPACE_TASK", tmpdir):
                mock_agent = MagicMock()
                mock_agent.hook_instruction = MagicMock()
                pre_run_set_agent_runtime_input(mock_agent)

                input_func = get_agent_runtime_input_with_timeout()
                session_id = env_tool.get_session_id() or "topsailai"
                pipe_path = os.path.join(
                    tmpdir, f"{session_id}.{os.getpid()}.session.pipe"
                )

                writer_thread = self._write_to_pipe(
                    pipe_path, "approve\nEOF\n", delay=0.02
                )

                start = time.monotonic()
                result = input_func("prompt", timeout=1.0)
                elapsed = time.monotonic() - start

                self.assertEqual(result, "approve")
                self.assertLess(elapsed, 0.3)
                writer_thread.join(timeout=0.5)


if __name__ == "__main__":
    unittest.main()
        self.assertIn("timeout", call_kwargs)
        self.assertEqual(call_kwargs["timeout"], 3.0)


if __name__ == "__main__":
    unittest.main()
