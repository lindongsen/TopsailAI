"""
Reproduction test for the tool_approval pipe input EOF bug.

Scenario:
1. A normal user message is sent through the session pipe with an EOF marker.
2. input_from_pipe returns the message but buffers the EOF marker.
3. A tool call triggers approval.
4. The approval reader thread reads from the same pipe via the agent-runtime
   input function registered by the pre_run hook.
5. Without the fix, the buffered EOF marker causes input_from_pipe to raise
   EOFError (when raise_eof_error=True), killing the reader thread and making
   the approval time out.
6. With the fix (raise_eof_error=False in the wrapper and EOFError handled in
   the transport), the approval can read the next real input.
"""

import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import pytest


class TestToolApprovalPipeEofRepro(unittest.TestCase):
    """Reproduce and verify the EOF-after-normal-message approval bug."""

    def _write_to_pipe(self, pipe_path: str, payload: str, delay: float = 0.02):
        """Start a daemon thread that writes *payload* to *pipe_path*."""
        import errno

        def writer():
            time.sleep(delay)
            fd = None
            for _ in range(200):
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

    def test_approval_input_after_eof_marker(self):
        """Approval input works after a previous message consumed an EOF marker."""
        from topsailai.utils import env_tool
        from topsailai.utils.input_tool import input_from_pipe
        from topsailai.workspace.agent.hooks.pre_run_input import (
            pre_run_set_agent_runtime_input,
        )
        from topsailai.utils.thread_local_tool import (
            get_agent_runtime_input_with_timeout,
            rid_all_thread_vars,
        )
        from topsailai.ai_base.tool_approval.transport import LocalApprovalTransport
        from topsailai.ai_base.tool_approval.instance import ToolApprovalInstance

        rid_all_thread_vars()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                with patch(
                    "topsailai.workspace.input_tool.FOLDER_WORKSPACE_TASK", tmpdir
                ):
                    session_id = env_tool.get_session_id() or "topsailai"
                    pipe_path = os.path.join(
                        tmpdir, f"{session_id}.{os.getpid()}.session.pipe"
                    )

                    # Step 1: simulate the first user message arriving with EOF.
                    # Keep the pipe alive so the approval step can reuse it.
                    writer1 = self._write_to_pipe(
                        pipe_path, "hello\nEOF\n", delay=0.02
                    )
                    first_line = input_from_pipe(
                        pipe_path,
                        single_line=True,
                        timeout=1.0,
                        cleanup_pipe=False,
                    )
                    writer1.join(timeout=0.5)
                    self.assertEqual(first_line, "hello")

                    # Step 2: register the agent-runtime input function exactly
                    # as AgentChat.run() does via the pre_run hook.
                    mock_agent = unittest.mock.MagicMock()
                    mock_agent.hook_instruction = unittest.mock.MagicMock()
                    pre_run_set_agent_runtime_input(mock_agent)
                    input_func = get_agent_runtime_input_with_timeout()
                    self.assertIsNotNone(input_func)

                    # Step 3: simulate the approval decision arriving.
                    writer2 = self._write_to_pipe(
                        pipe_path, "approve\nEOF\n", delay=0.05
                    )

                    # Step 4: run the transport reader as LocalApprovalTransport does.
                    transport = LocalApprovalTransport()
                    instance = ToolApprovalInstance(
                        tool_name="cmd_tool-exec_cmd",
                        tool_args={"cmd": "echo hello"},
                        transport=transport,
                    )
                    instance.timeout = 2.0

                    transport._read_stdin_input(instance)
                    writer2.join(timeout=0.5)

                    self.assertEqual(instance.status, instance.STATUS_APPROVED)
        finally:
            rid_all_thread_vars()
            try:
                os.unlink(pipe_path)
            except FileNotFoundError:
                pass


if __name__ == "__main__":
    unittest.main()
