"""Real FIFO regressions for complete messages and stable endpoints.

Author: DawsonLin
"""

import os
import threading
import time
from unittest.mock import Mock

import pytest

from topsailai.utils import input_tool as reader
from topsailai.workspace import input_tool as workspace


@pytest.mark.parametrize("multiline", [False, True])
@pytest.mark.parametrize("fragmented", [False, True])
def test_complete_messages(tmp_path, monkeypatch, multiline, fragmented):
    """Preserve newlines and blank lines across serial sends and split writes."""
    fifo = tmp_path / "session.pipe"
    os.mkfifo(fifo)
    inode = fifo.stat().st_ino
    messages = ["first\nsecond\n第三行", "first\n\nlast", "next\nmessage"]
    consumed = [threading.Event() for _ in messages]
    errors = []
    monkeypatch.setattr(workspace, "_build_pipe_path", lambda *args: str(fifo))
    monkeypatch.setattr(workspace.env_tool, "is_input_pipe_enabled", lambda: True)
    monkeypatch.setattr(workspace.env_tool, "is_chat_multi_line", lambda: multiline)
    monkeypatch.setattr(workspace.env_tool, "get_input_pipe_timeout", lambda: 3)
    history = Mock()
    monkeypatch.setattr(workspace, "_append_input_history_jsonl", history)
    monkeypatch.setattr(reader.sys, "stdin", None)

    def send():
        """Write owned frames with bounded nonblocking FIFO-open retries."""
        try:
            for index, message in enumerate(messages):
                deadline = time.monotonic() + 5
                while True:
                    try:
                        fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise TimeoutError("Reader did not open FIFO")
                        time.sleep(0.01)
                try:
                    frame = (message + "\nEOF\n").encode()
                    split = frame.index(b"\n") + 1 if fragmented else len(frame)
                    assert os.write(fd, frame[:split]) == split
                    if fragmented:
                        time.sleep(0.05)
                        assert os.write(fd, frame[split:]) == len(frame) - split
                finally:
                    os.close(fd)
                assert consumed[index].wait(5), "Receiver did not consume frame"
        except BaseException as exc:
            errors.append(exc)

    writer = threading.Thread(target=send, daemon=True)
    writer.start()
    try:
        for index, message in enumerate(messages):
            assert workspace.input_message("PROBE> ") == message
            assert fifo.stat().st_ino == inode
            consumed[index].set()
        assert [call.args[0] for call in history.call_args_list] == messages
    finally:
        for event in consumed:
            event.set()
        writer.join(6)
        reader._clear_leftover_buffer(str(fifo))
    assert not writer.is_alive()
    assert not errors, repr(errors)


def test_reject_non_fifo_without_deletion(tmp_path):
    """Reject an unrelated file without destroying its contents."""
    path = tmp_path / "not-a-fifo"
    path.write_text("unrelated")
    with pytest.raises(ValueError, match="not a FIFO"):
        reader._ensure_fifo(str(path))
    assert path.read_text() == "unrelated"
