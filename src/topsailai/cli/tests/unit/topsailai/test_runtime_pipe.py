"""Exact FIFO contracts with isolated seams and fixture-owned endpoints."""

import errno
import os
from pathlib import Path
import stat
import threading
from types import SimpleNamespace

import pytest

from cli_topsailai import runtime_pipe as pipe


@pytest.fixture
def transport(monkeypatch):
    """Provide an isolated clock and syscall model without patching os."""
    state = SimpleNamespace(now=0.0, opened=[], closed=[], writes=[], info=SimpleNamespace(st_mode=stat.S_IFIFO, st_dev=1, st_ino=2))

    def clock():
        """Read controlled monotonic time."""
        return state.now

    def sleep(seconds):
        """Advance controlled time on retry."""
        state.now += seconds

    def open_fifo(path, flags):
        """Record exact path opening."""
        state.opened.append(path)
        return 17

    def write(fd, data):
        """Record complete default writes."""
        state.writes.append(data)
        return len(data)

    monkeypatch.setattr(pipe, '_clock', clock)
    monkeypatch.setattr(pipe, '_sleep', sleep)
    monkeypatch.setattr(pipe, '_supported', lambda: True)
    monkeypatch.setattr(pipe, '_lstat', lambda path: state.info)
    monkeypatch.setattr(pipe, '_fstat', lambda fd: state.info)
    monkeypatch.setattr(pipe, '_open', open_fifo)
    monkeypatch.setattr(pipe, '_write', write)
    monkeypatch.setattr(pipe, '_close', state.closed.append)
    return state


@pytest.mark.parametrize('message,payload', [('yes', b'yes\nEOF\n'), ('a\nb\n', b'a\nb\nEOF\n'), ('日本 EOF', '日本 EOF\nEOF\n'.encode())])
def test_framing(message, payload):
    """Only protocol framing is appended, preserving UTF-8 and whitespace."""
    assert pipe.format_pipe_payload(message) == payload


@pytest.mark.parametrize('message', ['', '  \n', None, 1, 'EOF', 'a\nEOF\nb', 'a\r\nEOF\r\nb', '\ud800'])
def test_invalid_message_before_io(transport, message):
    """Invalid content causes no open, write or staging."""
    with pytest.raises(pipe.PipeDeliveryError) as error:
        pipe.send_to_pipe(Path('/fixture.pipe'), message)
    assert error.value.exit_code == 2
    assert not transport.opened and not transport.writes


@pytest.mark.parametrize('timeout', [0, -1, float('nan'), float('inf'), True, '1'])
def test_invalid_timeout(transport, timeout):
    """Require a finite positive numeric duration."""
    with pytest.raises(pipe.PipeDeliveryError) as error:
        pipe.send_to_pipe(Path('/fixture.pipe'), 'yes', timeout=timeout)
    assert error.value.exit_code == 2
    assert not transport.opened


@pytest.mark.parametrize('path', ['not-a-Path', Path('relative'), Path('/bad\x00')])
def test_invalid_path(transport, path):
    """Require an absolute non-NUL Path before opening."""
    with pytest.raises(pipe.PipeDeliveryError) as error:
        pipe.send_to_pipe(path, 'yes')
    assert error.value.exit_code == 2


def test_unsupported(transport, monkeypatch):
    """Lack of safe platform support must fail before endpoint I/O."""
    monkeypatch.setattr(pipe, '_supported', lambda: False)
    with pytest.raises(pipe.PipeDeliveryError) as error:
        pipe.send_to_pipe(Path('/fixture.pipe'), 'yes')
    assert error.value.exit_code == 4
    assert not transport.opened


@pytest.mark.parametrize('mode', [stat.S_IFREG, stat.S_IFLNK])
def test_invalid_endpoint(transport, mode):
    """Refuse ordinary files and symlinks without opening."""
    transport.info.st_mode = mode
    with pytest.raises(pipe.PipeDeliveryError) as error:
        pipe.send_to_pipe(Path('/fixture.pipe'), 'yes')
    assert error.value.error_code == 'endpoint_invalid'
    assert not transport.opened


@pytest.mark.parametrize('number,code', [(errno.ENOENT, 'endpoint_missing'), (errno.EACCES, 'permission_denied'), (errno.EPERM, 'permission_denied'), (errno.ELOOP, 'endpoint_invalid'), (errno.ENOTDIR, 'endpoint_invalid'), (errno.EIO, 'transport_error')])
def test_io_error_categories(transport, monkeypatch, number, code):
    """Preserve causes and distinguish unexpected failures from absence."""
    cause = OSError(number, 'fixture error')

    def fail(path):
        """Inject endpoint inspection failure."""
        raise cause

    monkeypatch.setattr(pipe, '_lstat', fail)
    with pytest.raises(pipe.PipeDeliveryError) as error:
        pipe.send_to_pipe(Path('/fixture.pipe'), 'yes')
    assert error.value.error_code == code
    assert error.value.__cause__ is cause


@pytest.mark.parametrize('replacement', [SimpleNamespace(st_mode=stat.S_IFREG, st_dev=1, st_ino=2), SimpleNamespace(st_mode=stat.S_IFIFO, st_dev=1, st_ino=3)])
def test_open_identity(transport, monkeypatch, replacement):
    """Reject replacement before any write, closing the descriptor once."""
    monkeypatch.setattr(pipe, '_fstat', lambda fd: replacement)
    with pytest.raises(pipe.PipeDeliveryError) as error:
        pipe.send_to_pipe(Path('/fixture.pipe'), 'yes')
    assert error.value.exit_code == 4
    assert transport.closed == [17] and not transport.writes


@pytest.mark.parametrize('failure', [OSError(errno.EIO, 'fstat'), KeyboardInterrupt()])
def test_observation_cleanup(transport, monkeypatch, failure):
    """Ownership is armed before fallible fstat, including interruption."""
    def fail(fd):
        """Interrupt the first observation of the owned descriptor."""
        raise failure

    monkeypatch.setattr(pipe, '_fstat', fail)
    with pytest.raises((pipe.PipeDeliveryError, KeyboardInterrupt)):
        pipe.send_to_pipe(Path('/fixture.pipe'), 'yes')
    assert transport.closed == [17]


@pytest.mark.parametrize('number', [errno.ENXIO, errno.EAGAIN, errno.EINTR])
def test_open_deadline(transport, monkeypatch, number):
    """Repeated open failures share one deadline and never try another path."""
    calls = []

    def fail(path, flags):
        """Model a FIFO without an available reader."""
        calls.append(path)
        raise OSError(number, 'retry')

    monkeypatch.setattr(pipe, '_open', fail)
    with pytest.raises(pipe.PipeDeliveryError) as error:
        pipe.send_to_pipe(Path('/fixture.pipe'), 'yes', timeout=.03)
    assert error.value.error_code == 'timeout'
    assert .03 <= transport.now < .04
    assert set(calls) == {Path('/fixture.pipe')}
    assert not transport.closed


def test_open_error(transport, monkeypatch):
    """Nonretryable open failures retain their original cause."""
    def fail(path, flags):
        """Model access denial."""
        raise PermissionError(errno.EACCES, 'denied')

    monkeypatch.setattr(pipe, '_open', fail)
    with pytest.raises(pipe.PipeDeliveryError) as error:
        pipe.send_to_pipe(Path('/fixture.pipe'), 'yes')
    assert error.value.error_code == 'permission_denied'


def test_short_write_retry(transport, monkeypatch):
    """EAGAIN/EINTR and short writes resume only the remaining bytes."""
    actions = iter([2, OSError(errno.EAGAIN, 'busy'), OSError(errno.EINTR, 'interrupt'), 6])
    pieces = []

    def write(fd, data):
        """Apply bounded short writes and temporary backpressure."""
        action = next(actions)
        if isinstance(action, Exception):
            raise action
        pieces.append(data[:action])
        return action

    monkeypatch.setattr(pipe, '_write', write)
    result = pipe.send_to_pipe(Path('/fixture.pipe'), 'yes')
    assert result.bytes_written == 8
    assert b''.join(pieces) == b'yes\nEOF\n'
    assert transport.opened == [Path('/fixture.pipe')] and transport.closed == [17]


@pytest.mark.parametrize('action', [0, OSError(errno.EPIPE, 'broken'), OSError(errno.EIO, 'other')])
def test_partial_failure(transport, monkeypatch, action):
    """Partial input is uncertain, and the whole message is never resent."""
    actions = iter([2, action])

    def write(fd, data):
        """Write a prefix then fail."""
        value = next(actions)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(pipe, '_write', write)
    with pytest.raises(pipe.PipeDeliveryError) as error:
        pipe.send_to_pipe(Path('/fixture.pipe'), 'yes')
    assert error.value.bytes_written == 2 and error.value.delivery_unknown
    assert error.value.exit_code == 5
    assert len(transport.opened) == 1 and transport.closed == [17]


def test_partial_deadline(transport, monkeypatch):
    """Backpressure after a prefix expires the original absolute deadline."""
    calls = []

    def write(fd, data):
        """Accept a prefix and then remain backpressured."""
        calls.append(data)
        if len(calls) == 1:
            return 2
        raise BlockingIOError(errno.EAGAIN, 'busy')

    monkeypatch.setattr(pipe, '_write', write)
    with pytest.raises(pipe.PipeDeliveryError) as error:
        pipe.send_to_pipe(Path('/fixture.pipe'), 'yes', timeout=.03)
    assert error.value.error_code == 'timeout' and error.value.bytes_written == 2
    assert all(data == b's\nEOF\n' for data in calls[1:])
    assert transport.closed == [17]


def test_late_open(transport, monkeypatch):
    """Late opened descriptors are closed before writing."""
    def inspect(fd):
        """Advance time beyond the deadline after opening."""
        transport.now = 6
        return transport.info

    monkeypatch.setattr(pipe, '_fstat', inspect)
    with pytest.raises(pipe.PipeDeliveryError):
        pipe.send_to_pipe(Path('/fixture.pipe'), 'yes')
    assert transport.closed == [17] and not transport.writes


def test_late_write(transport, monkeypatch):
    """Even a complete late write must not be reported successful."""
    def write(fd, data):
        """Complete bytes too late."""
        transport.now = 6
        return len(data)

    monkeypatch.setattr(pipe, '_write', write)
    with pytest.raises(pipe.PipeDeliveryError) as error:
        pipe.send_to_pipe(Path('/fixture.pipe'), 'yes')
    assert error.value.bytes_written == 8 and error.value.delivery_unknown
    assert transport.closed == [17]


@pytest.mark.parametrize('failure', [OSError(errno.EIO, 'write'), KeyboardInterrupt()])
def test_staging_cleanup(transport, monkeypatch, capsys, failure):
    """Stage removal is logged to stderr, even for host interruption."""
    directory = Path(pipe.__file__).absolute().parent.parent / '.tmp'
    before = set(directory.glob('runtime-send-*.tmp'))

    def write(fd, data):
        """Inject failure during staged transport."""
        raise failure

    monkeypatch.setattr(pipe, '_write', write)
    with pytest.raises((pipe.PipeDeliveryError, KeyboardInterrupt)):
        pipe.send_to_pipe(Path('/fixture.pipe'), 'line one\nline two')
    assert set(directory.glob('runtime-send-*.tmp')) == before
    output = capsys.readouterr()
    assert not output.out and 'Removed temporary send payload' in output.err
    assert transport.closed == [17]


def test_cleanup_warning(transport, monkeypatch, capsys):
    """Close failure is logged once and does not alter delivery evidence."""
    def close(fd):
        """Model close returning a failure."""
        transport.closed.append(fd)
        raise OSError('close failed')

    monkeypatch.setattr(pipe, '_close', close)
    assert pipe.send_to_pipe(Path('/fixture.pipe'), 'yes').bytes_written == 8
    assert transport.closed == [17]
    assert 'Failed to close' in capsys.readouterr().err


@pytest.mark.parametrize('message', ['yes', 'line one\nline two', '大' * 50000])
def test_real_fifo(tmp_path, message, capsys):
    """Use one fixture FIFO and a bounded nonblocking reader, no real session."""
    path = tmp_path / 'fixture.pipe'
    os.mkfifo(path)
    reader = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    received = bytearray()
    stop = threading.Event()

    def read():
        """Drain only this descriptor until the fixture is stopped."""
        while not stop.is_set():
            try:
                received.extend(os.read(reader, 65536))
            except BlockingIOError:
                pass
            stop.wait(.001)

    thread = threading.Thread(target=read)
    thread.start()
    try:
        result = pipe.send_to_pipe(path, message, timeout=3)
        expected = pipe.format_pipe_payload(message)
        for _ in range(3000):
            if len(received) == len(expected):
                break
            stop.wait(.001)
        assert bytes(received) == expected
        assert result.bytes_written == len(expected)
    finally:
        stop.set()
        thread.join(3)
        os.close(reader)
    assert not thread.is_alive()
    assert not capsys.readouterr().out


def test_staging_fdopen_failure(transport, monkeypatch, capsys):
    """Failed ownership transfer closes the staged descriptor and removes its file."""
    directory = Path(pipe.__file__).absolute().parent.parent / '.tmp'
    before = set(directory.glob('runtime-send-*.tmp'))
    actual_close = os.close

    def close(fd):
        """Record and actually release the staging descriptor."""
        transport.closed.append(fd)
        actual_close(fd)

    def fail(fd, mode):
        """Reject conversion before the file object takes ownership."""
        raise OSError(errno.EIO, 'fdopen failed')

    monkeypatch.setattr(pipe, '_close', close)
    monkeypatch.setattr(pipe, '_fdopen', fail)
    with pytest.raises(pipe.PipeDeliveryError):
        pipe.send_to_pipe(Path('/fixture.pipe'), 'a\nb')
    assert len(transport.closed) == 1 and not transport.opened
    assert set(directory.glob('runtime-send-*.tmp')) == before
    assert 'Removed temporary' in capsys.readouterr().err


def test_staging_cleanup_warning(transport, monkeypatch, capsys):
    """Cleanup failure is logged without replacing successful write evidence."""
    actual_unlink = os.unlink
    names = []

    def fail(name):
        """Model a failed removal, then let the fixture explicitly clean it."""
        names.append(name)
        raise OSError(errno.EACCES, 'unlink denied')

    monkeypatch.setattr(pipe, '_unlink', fail)
    try:
        assert pipe.send_to_pipe(Path('/fixture.pipe'), 'a\nb').bytes_written == 8
        assert 'Failed to remove' in capsys.readouterr().err
    finally:
        for name in names:
            actual_unlink(name)
            print(f'[INFO] Fixture removed temporary send payload: {name}')


def test_staged_read_failure(transport):
    """A read failure after delivery retains the delivered-byte count."""
    class Stream:
        """Provide one chunk then fail the next staged read."""
        calls = 0

        def read(self, size):
            """Return initial bytes once."""
            self.calls += 1
            if self.calls == 1:
                return b'abc'
            raise OSError(errno.EIO, 'read failed')

    with pytest.raises(pipe.PipeDeliveryError) as error:
        pipe._write_payload(17, Stream(), 5)
    assert error.value.bytes_written == 3 and error.value.delivery_unknown
    assert isinstance(error.value.__cause__, OSError)


def test_open_and_write_share_deadline(transport, monkeypatch):
    """Time spent awaiting a reader reduces time remaining for writes."""
    calls = []

    def open_fifo(path, flags):
        """Spend most of the budget during endpoint opening."""
        calls.append(path)
        if len(calls) < 3:
            raise OSError(errno.ENXIO, 'no reader')
        return 17

    def write(fd, data):
        """Keep the opened pipe backpressured."""
        raise BlockingIOError(errno.EAGAIN, 'busy')

    monkeypatch.setattr(pipe, '_open', open_fifo)
    monkeypatch.setattr(pipe, '_write', write)
    with pytest.raises(pipe.PipeDeliveryError) as error:
        pipe.send_to_pipe(Path('/fixture.pipe'), 'yes', timeout=.03)
    assert error.value.error_code == 'timeout'
    assert .03 <= transport.now < .04 and transport.closed == [17]


@pytest.mark.parametrize('outcome', ['complete', 'partial', 'interrupt'])
@pytest.mark.parametrize('diagnostics_fail', [False, True])
def test_public_cleanup_preserves_evidence(transport, monkeypatch, outcome, diagnostics_fail):
    """Close/removal/diagnostic failures cannot erase public delivery evidence."""
    close_error = OSError(errno.EIO, 'staged close failed')
    primary = OSError(errno.EPIPE, 'primary broken pipe') if outcome == 'partial' else KeyboardInterrupt()
    actual_fdopen, actual_unlink = os.fdopen, os.unlink
    removed, closed_streams, calls = [], [], []

    class Stream:
        """Delegate staging while failing after actually releasing its descriptor."""
        def __init__(self, stream):
            """Own the staging file object."""
            self.stream = stream

        def write(self, data):
            """Stage bytes normally."""
            return self.stream.write(data)

        def seek(self, offset):
            """Rewind staging normally."""
            return self.stream.seek(offset)

        def read(self, size):
            """Read the real staged bytes."""
            return self.stream.read(size)

        def close(self):
            """Close exactly once then expose a cleanup error."""
            closed_streams.append(self.stream)
            self.stream.close()
            raise close_error

    def unlink(name):
        """Record the exact removal attempt and remove the fixture file."""
        removed.append(name)
        actual_unlink(name)

    def write(fd, data):
        """Accept all input or a prefix before a primary failure."""
        calls.append(data)
        if outcome == 'complete':
            return len(data)
        if len(calls) == 1:
            return 2
        raise primary

    def fail_print(*args, **kwargs):
        """Model stderr becoming unavailable during cleanup."""
        raise OSError(errno.EIO, 'stderr failed')

    monkeypatch.setattr(pipe, '_fdopen', lambda fd, mode: Stream(actual_fdopen(fd, mode)))
    monkeypatch.setattr(pipe, '_unlink', unlink)
    monkeypatch.setattr(pipe, '_write', write)
    if diagnostics_fail:
        monkeypatch.setattr(pipe, 'print', fail_print, raising=False)
    expected = KeyboardInterrupt if outcome == 'interrupt' else pipe.PipeDeliveryError
    with pytest.raises(expected) as error:
        pipe.send_to_pipe(Path('/fixture.pipe'), 'a\nb')
    if outcome == 'interrupt':
        assert error.value is primary
    else:
        assert error.value.bytes_written == (8 if outcome == 'complete' else 2)
        assert error.value.delivery_unknown and error.value.exit_code == 5
        assert error.value.__cause__ is (close_error if outcome == 'complete' else primary)
    assert transport.closed == [17] and len(transport.opened) == 1
    assert len(closed_streams) == 1 and closed_streams[0].closed
    assert len(removed) == 1 and not Path(removed[0]).exists()
    assert len(calls) == (1 if outcome == 'complete' else 2)


def test_open_exhausts_budget_before_fstat(transport, monkeypatch):
    """A late successful open is closed without any identity observation/write."""
    inspected = []

    def open_fifo(path, flags):
        """Consume the budget in open itself."""
        transport.opened.append(path)
        transport.now = 5
        return 17

    monkeypatch.setattr(pipe, '_open', open_fifo)
    monkeypatch.setattr(pipe, '_fstat', lambda fd: inspected.append(fd))
    with pytest.raises(pipe.PipeDeliveryError) as error:
        pipe.send_to_pipe(Path('/fixture.pipe'), 'yes')
    assert error.value.error_code == 'timeout' and error.value.bytes_written == 0
    assert transport.closed == [17] and not inspected and not transport.writes


@pytest.mark.parametrize('operation', ['lstat', 'open', 'fstat', 'read', 'write', 'zero_write'])
def test_late_failed_io_public(transport, monkeypatch, operation):
    """Every failing I/O boundary observes the same deadline and preserves causes."""
    cause = OSError(errno.EIO, 'late operation failed')
    actual_fdopen = os.fdopen
    calls = []

    def fail(*args):
        """Exhaust the deadline then fail the selected operation."""
        transport.now = 5
        raise cause

    def write(fd, data):
        """Accept a prefix then return late failure or zero progress."""
        calls.append(data)
        if len(calls) == 1:
            return 2
        transport.now = 5
        if operation == 'zero_write':
            return 0
        raise cause

    class Stream:
        """Advance the clock on the second staged read."""
        def __init__(self, stream):
            """Own a real staging file."""
            self.stream = stream
            self.reads = 0

        def write(self, data):
            """Stage normally."""
            return self.stream.write(data)

        def seek(self, offset):
            """Rewind normally."""
            return self.stream.seek(offset)

        def read(self, size):
            """Return the first chunk, then fail too late."""
            self.reads += 1
            if self.reads == 1:
                return self.stream.read(size)
            return fail()

        def close(self):
            """Release the staging owner."""
            self.stream.close()

    if operation in ('lstat', 'open', 'fstat'):
        monkeypatch.setattr(pipe, '_' + operation, fail)
    elif operation == 'read':
        monkeypatch.setattr(pipe, '_fdopen', lambda fd, mode: Stream(actual_fdopen(fd, mode)))
    else:
        monkeypatch.setattr(pipe, '_write', write)
    with pytest.raises(pipe.PipeDeliveryError) as error:
        pipe.send_to_pipe(Path('/fixture.pipe'), 'a\nb')
    written = 8 if operation == 'read' else 2 if operation in ('write', 'zero_write') else 0
    assert error.value.error_code == 'timeout'
    assert error.value.bytes_written == written
    assert error.value.delivery_unknown == (written > 0)
    if operation != 'zero_write':
        assert error.value.__cause__ is cause
    assert transport.closed == ([] if operation in ('lstat', 'open') else [17])


def test_close_diagnostic_failure_does_not_replace_primary(transport, monkeypatch):
    """FIFO close warnings remain secondary even when stderr fails."""
    primary = KeyboardInterrupt()

    def write(fd, data):
        """Interrupt transport."""
        raise primary

    def close(fd):
        """Record sole close attempt then fail."""
        transport.closed.append(fd)
        raise OSError(errno.EIO, 'close failed')

    def fail_print(*args, **kwargs):
        """Reject cleanup output."""
        raise OSError(errno.EIO, 'stderr failed')

    monkeypatch.setattr(pipe, '_write', write)
    monkeypatch.setattr(pipe, '_close', close)
    monkeypatch.setattr(pipe, 'print', fail_print, raising=False)
    with pytest.raises(KeyboardInterrupt) as error:
        pipe.send_to_pipe(Path('/fixture.pipe'), 'yes')
    assert error.value is primary and transport.closed == [17]
