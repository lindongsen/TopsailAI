"""Follow one selected session log through a single owned descriptor.

Author: DawsonLin
"""

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cli_topsailai import runtime_logs as logs


def target(folder, data=b"", name="session.x.123.session.stdout"):
    """Create one synthetic log and resolve its offline identity."""
    (folder / name).write_bytes(data)
    return logs.resolve_log_target(folder, pid=123)


def follower(item, count=20, **kwargs):
    """Build a follower with an injected sleep so no test really waits."""
    kwargs.setdefault("sleep", Mock())
    return logs.LogFollower(item, count, **kwargs)


def test_initial_tail_then_appended_records(tmp_path):
    """The initial tail is the -n snapshot and later appends are streamed."""
    item = target(tmp_path, b"a\nb\nc\n")
    with follower(item, 2) as stream:
        assert stream.tail.lines == ("b", "c")
        assert stream.tail.requested_lines == 2
        assert stream.poll() == ()
        with open(item.stdout_path, "ab") as writer:
            writer.write(b"d\ne\n")
        assert stream.poll() == ("d", "e")
        assert stream.poll() == ()


def test_partial_record_is_held_until_terminated(tmp_path):
    """A record written in several writes is emitted exactly once."""
    item = target(tmp_path, b"")
    with follower(item) as stream:
        with open(item.stdout_path, "ab") as writer:
            writer.write(b"par")
        assert stream.poll() == ()
        with open(item.stdout_path, "ab") as writer:
            writer.write(b"tial\nnext")
        assert stream.poll() == ("partial",)
        assert stream.poll() == ()
        with open(item.stdout_path, "ab") as writer:
            writer.write(b"\n")
        assert stream.poll() == ("next",)


def test_crlf_and_blank_records(tmp_path):
    """Followed records use the same CRLF and blank-record rules as the tail."""
    item = target(tmp_path, b"")
    with follower(item) as stream:
        with open(item.stdout_path, "ab") as writer:
            writer.write(b"a\r\n\nb\r")
        assert stream.poll() == ("a", "")
        assert stream.flush() == ("b\r",)
        assert stream.flush() == ()


def test_flush_emits_pending_once(tmp_path):
    """The held unterminated remainder is emitted once and then cleared."""
    item = target(tmp_path, b"")
    with follower(item) as stream:
        with open(item.stdout_path, "ab") as writer:
            writer.write(b"tail-without-newline")
        assert stream.poll() == ()
        assert stream.flush() == ("tail-without-newline",)
        assert stream.flush() == ()


def test_truncation_restarts_at_beginning(tmp_path):
    """Shrinkage is normal for a followed log and restarts at offset zero."""
    item = target(tmp_path, b"old\nold\n")
    with follower(item) as stream:
        assert stream.tail.lines == ("old", "old")
        Path(item.stdout_path).write_bytes(b"n\n")
        assert stream.poll() == ("n",)
        with open(item.stdout_path, "ab") as writer:
            writer.write(b"after\n")
        assert stream.poll() == ("after",)


def test_rotation_keeps_original_descriptor(tmp_path):
    """Rotation after open keeps reading the original file, like tail -f."""
    item = target(tmp_path, b"old\n")
    with follower(item) as stream:
        Path(item.stdout_path).rename(tmp_path / "rotated")
        Path(item.stdout_path).write_bytes(b"replacement\n")
        with open(tmp_path / "rotated", "ab") as writer:
            writer.write(b"appended\n")
        assert stream.poll() == ("appended",)


def test_identity_change_fails(tmp_path, monkeypatch):
    """A replaced descriptor identity is a classified follow failure."""
    item = target(tmp_path, b"a\n")
    real_fstat = os.fstat
    calls = 0

    def fstat(fd):
        """Report a different inode after the follower opened its descriptor."""
        nonlocal calls
        calls += 1
        result = real_fstat(fd)
        fields = {name: getattr(result, name) for name in
                  ("st_size", "st_ino", "st_dev", "st_mode")}
        if calls > 1:
            fields["st_ino"] += 1
        return SimpleNamespace(**fields)

    monkeypatch.setattr(logs, "os", SimpleNamespace(**{name: getattr(os, name) for name in
        ("O_RDONLY", "O_BINARY", "O_NOFOLLOW", "O_NONBLOCK") if hasattr(os, name)},
        open=os.open, fdopen=os.fdopen, fstat=fstat, close=os.close))
    with follower(item) as stream:
        with pytest.raises(logs.RuntimeLogError) as error:
            stream.poll()
    assert error.value.error_code == "log_changed"


def test_read_error_is_classified(tmp_path, monkeypatch):
    """A poll read failure keeps the existing I/O classification."""
    item = target(tmp_path, b"a\n")
    with follower(item) as stream:
        stream._stream.read = Mock(side_effect=OSError("private"))
        with pytest.raises(logs.RuntimeLogError) as error:
            stream.poll()
    assert error.value.error_code == "log_read_failed"
    assert error.value.exit_code == 5


def test_oversized_pending_stays_bounded(tmp_path):
    """An unterminated record is emitted in bounded pieces, never buffered whole."""
    item = target(tmp_path, b"")
    with follower(item, max_pending=4) as stream:
        with open(item.stdout_path, "ab") as writer:
            writer.write(b"0123456789")
        assert stream.poll() == ("0123", "4567")
        assert stream.flush() == ("89",)


def test_descriptor_closed_on_every_exit(tmp_path):
    """The owned descriptor is closed on normal and exceptional exits."""
    item = target(tmp_path, b"a\n")
    stream = follower(item)
    with stream:
        assert not stream._stream.closed
    assert stream._stream is None
    with pytest.raises(RuntimeError):
        with follower(item) as failing:
            owned = failing._stream
            raise RuntimeError("host failure")
    assert owned.closed


def test_use_outside_lifetime_is_rejected(tmp_path):
    """A follower cannot poll or report a tail before it is opened."""
    item = target(tmp_path, b"a\n")
    stream = follower(item)
    with pytest.raises(logs.RuntimeTargetError):
        stream.poll()
    with pytest.raises(logs.RuntimeTargetError):
        stream.tail


@pytest.mark.parametrize("kwargs", [
    {"count": True}, {"count": 0}, {"count": 10001}, {"count": "20"},
    {"poll_interval": 0}, {"poll_interval": "1"}, {"max_pending": 0},
    {"chunk_size": 0}, {"budget": 0},
])
def test_invalid_bounds(tmp_path, kwargs):
    """Follow bounds are validated before any file access."""
    item = target(tmp_path, b"a\n")
    with pytest.raises(logs.RuntimeTargetError) as error:
        logs.LogFollower(item, **kwargs)
    assert error.value.error_code == "usage_error"


def test_wait_uses_injected_sleep(tmp_path):
    """Polling waits through the injected seam, never a real sleep."""
    item = target(tmp_path, b"a\n")
    sleep = Mock()
    with follower(item, poll_interval=0.25, sleep=sleep) as stream:
        stream.wait()
    sleep.assert_called_once_with(0.25)


def test_missing_file_is_endpoint_error(tmp_path):
    """A selected file disappearing before open keeps its endpoint category."""
    item = target(tmp_path, b"a\n")
    Path(item.stdout_path).unlink()
    with pytest.raises(logs.RuntimeTargetError) as error:
        with follower(item):
            pass
    assert error.value.error_code == "endpoint_missing"
