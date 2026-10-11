"""Public control transport contracts and fixture-only UDS verification."""

import errno
import json
import socket
import stat
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from cli_topsailai import runtime_control as transport


class FakeSocket:
    """Deterministic socket with explicit delivery and cleanup evidence."""

    def __init__(self):
        """Initialize one response, no implicit retries."""
        self.frames = []
        self.calls = []
        self.request = None
        self.hooks = {}
        self.closed = 0

    def invoke(self, name):
        """Inject failures or clock advances at a selected boundary."""
        self.calls.append(name)
        if name in self.hooks:
            self.hooks[name]()

    def settimeout(self, value):
        """Record the current remaining socket budget."""
        self.invoke('timeout')
        self.budget = value

    def connect(self, path):
        """Record the single exact connection path."""
        self.path = path
        self.invoke('connect')

    def sendall(self, data):
        """Record the schema before any injected uncertain send failure."""
        self.request = json.loads(data)
        self.invoke('send')

    def recv(self, size):
        """Return bounded response fragments using the outgoing request ID."""
        self.invoke('read')
        self.size = size
        if self.frames:
            return self.frames.pop(0)
        return json.dumps({'request_id': self.request['request_id'],
                           'status': 'ok'}).encode() + b'\n'

    def close(self):
        """Count exactly one cleanup attempt."""
        self.closed += 1
        self.invoke('close')


@pytest.fixture
def channel(monkeypatch):
    """Provide module-local I/O seams without mutating socket/os singletons."""
    sock = FakeSocket()
    clock = [0.0]
    monkeypatch.setattr(transport, '_clock', lambda: clock[0])
    monkeypatch.setattr(transport, '_new_socket', lambda: sock)
    monkeypatch.setattr(transport, '_lstat', lambda p: SimpleNamespace(st_mode=stat.S_IFSOCK))
    monkeypatch.setattr(transport, '_request_id', lambda: 'correlation')
    monkeypatch.setattr(transport, 'get_control_actions', lambda: ['plugin', 'hard_interrupt'])
    return sock, clock


def send():
    """Exercise the public operation, never an actual session endpoint."""
    return transport.send_to_control('/fixture/control.sock', 'plugin', {'text': '你好'})


def fail(exc):
    """Build a one-boundary failure injection."""
    def raise_error():
        """Raise the exact retained exception instance."""
        raise exc
    return raise_error


def test_schema_and_rejection_tuple(channel):
    """Separate correlated acknowledgement from old transport-only success."""
    sock, _ = channel
    result = send()
    assert result.response['status'] == 'ok'
    assert sock.request == {'request_id': 'correlation', 'action': 'plugin',
                            'payload': {'text': '你好'}}
    assert sock.path == '/fixture/control.sock' and sock.closed == 1
    sock.frames = [b'{"request_id":"correlation","status":"error","error":"no"}\n']
    with pytest.raises(transport.ControlDeliveryError) as caught:
        send()
    assert caught.value.exit_code == 6
    assert not caught.value.delivery_unknown
    sock.frames = [b'{"request_id":"correlation","status":"error"}\n']
    ok, response = transport.send_control_request('/fixture/control.sock', 'plugin', {}, 5)
    assert ok and response['status'] == 'error'


@pytest.mark.parametrize('kwargs', [
    {'socket_path': 3}, {'socket_path': 'relative'}, {'socket_path': '/bad\0path'},
    {'action': ''}, {'action': 1}, {'action': ' plugin'}, {'action': 'unknown'},
    {'payload': []}, {'payload': {'bad': object()}}, {'payload': {'bad': float('nan')}},
    {'payload': {'bad': '\ud800'}}, {'timeout': True}, {'timeout': '5'},
    {'timeout': 0}, {'timeout': -1}, {'timeout': float('inf')}, {'timeout': float('nan')},
])
def test_preflight(channel, monkeypatch, kwargs):
    """Invalid inputs perform no endpoint I/O or connection."""
    def forbidden(path):
        """Fail if parameter validation reaches endpoint inspection."""
        pytest.fail('endpoint accessed')
    monkeypatch.setattr(transport, '_lstat', forbidden)
    arguments = dict(socket_path='/fixture/control.sock', action='plugin', payload={}, timeout=5)
    arguments.update(kwargs)
    with pytest.raises(transport.ControlDeliveryError) as caught:
        transport.send_to_control(**arguments)
    assert caught.value.exit_code == 2
    assert not channel[0].calls


@pytest.mark.parametrize('frame', [b'', b'{', b'not-json\n', b'\xff\n', b'[]\n',
    b'{}\n', b'{"request_id":"wrong","status":"ok"}\n',
    b'{"request_id":"correlation","status":"unknown"}\n'])
def test_invalid_response(channel, frame):
    """EOF truncation, malformed encoding and correlation are never success."""
    sock, _ = channel
    sock.frames = [frame, b'']
    with pytest.raises(transport.ControlDeliveryError) as caught:
        send()
    assert caught.value.exit_code == 6 and caught.value.delivery_unknown
    assert sock.closed == 1 and sock.calls.count('send') == 1


def test_fragmented_utf8_and_blank_lines(channel):
    """Decode only a complete byte frame, including split UTF-8 sequences."""
    sock, _ = channel
    data = json.dumps({'request_id': 'correlation', 'status': 'ok', 'result': '你好'},
                      ensure_ascii=False).encode() + b'\n'
    sock.frames = [b'\n  \n'] + [bytes([item]) for item in data]
    assert send().response['result'] == '你好'


@pytest.mark.parametrize('blank', [False, True])
def test_response_limit(channel, monkeypatch, blank):
    """Blank bytes also consume the aggregate limit plus one allowance."""
    monkeypatch.setattr(transport, 'RESPONSE_LIMIT', 8)
    channel[0].frames = [b'\n' * 8 if blank else b'x' * 8, b'x']
    with pytest.raises(transport.ControlDeliveryError) as caught:
        send()
    assert caught.value.exit_code == 6 and channel[0].size == 1


@pytest.mark.parametrize('stage', ['connect', 'send', 'read'])
@pytest.mark.parametrize('late', [False, True])
@pytest.mark.parametrize('raises', [False, True])
def test_deadline_and_errors(channel, stage, late, raises):
    """Success/failure on each operation observes one deadline and its cause."""
    sock, clock = channel
    cause = OSError(errno.EIO, 'fixture failure')
    def boundary():
        """Advance the shared clock and optionally raise after exhaustion."""
        if late:
            clock[0] = 6
        if raises:
            raise cause
    sock.hooks[stage] = boundary
    if not late and not raises:
        assert send().response['status'] == 'ok'
    else:
        with pytest.raises(transport.ControlDeliveryError) as caught:
            send()
        assert caught.value.error_code == ('timeout' if late else 'transport_error')
        assert caught.value.delivery_unknown == (stage != 'connect')
        if raises:
            assert caught.value.__cause__ is cause
    assert sock.closed == 1
    assert sock.calls.count('connect') == 1
    assert sock.calls.count('send') <= 1


def test_drip_deadline(channel):
    """Repeated blank lines cannot reset the original budget."""
    sock, clock = channel
    sock.frames = [b'\n'] * 10
    def drip():
        """Consume one second from the same absolute budget per read."""
        clock[0] += 1
    sock.hooks['read'] = drip
    with pytest.raises(transport.ControlDeliveryError) as caught:
        send()
    assert caught.value.error_code == 'timeout' and sock.calls.count('read') == 5
    assert sock.budget == 1


@pytest.mark.parametrize('stage', ['connect', 'send', 'read'])
def test_cleanup_preserves_primary(channel, stage):
    """Close failure retains original error, delivery facts and cause."""
    sock, _ = channel
    cause = OSError(errno.EIO, 'primary')
    sock.hooks[stage] = fail(cause)
    sock.hooks['close'] = fail(OSError('cleanup'))
    with pytest.raises(transport.ControlDeliveryError) as caught:
        send()
    assert caught.value.__cause__ is cause
    assert caught.value.delivery_unknown == (stage != 'connect')
    assert caught.value.__notes__ and sock.closed == 1


def test_cleanup_interrupt(channel):
    """A host interrupt is not converted or replaced by ordinary cleanup."""
    sock, _ = channel
    primary = KeyboardInterrupt()
    sock.hooks['send'] = fail(primary)
    sock.hooks['close'] = fail(OSError('cleanup'))
    with pytest.raises(KeyboardInterrupt) as caught:
        send()
    assert caught.value is primary and sock.closed == 1


def test_cleanup_after_success(channel):
    """A standalone cleanup failure retains conservative sent evidence."""
    channel[0].hooks['close'] = fail(OSError('cleanup'))
    with pytest.raises(transport.ControlDeliveryError) as caught:
        send()
    assert caught.value.delivery_unknown and caught.value.exit_code == 5


@pytest.mark.parametrize('error,code', [(FileNotFoundError(), 4),
    (PermissionError(), 4), (OSError(errno.EAFNOSUPPORT, 'unsupported'), 4),
    (TimeoutError(), 5), (OSError(errno.EIO, 'bad'), 5)])
def test_endpoint_errors(channel, monkeypatch, error, code):
    """Endpoint failures classify facts and preserve underlying exceptions."""
    def inspect(path):
        """Raise fixture filesystem error."""
        raise error
    monkeypatch.setattr(transport, '_lstat', inspect)
    with pytest.raises(transport.ControlDeliveryError) as caught:
        send()
    assert caught.value.exit_code == code and caught.value.__cause__ is error


@pytest.mark.parametrize('mode', [stat.S_IFREG, stat.S_IFLNK])
def test_wrong_endpoint(channel, monkeypatch, mode):
    """Reject ordinary files and symlink endpoints before socket creation."""
    monkeypatch.setattr(transport, '_lstat', lambda p: SimpleNamespace(st_mode=mode))
    with pytest.raises(transport.ControlDeliveryError) as caught:
        send()
    assert caught.value.error_code == 'endpoint_invalid'


def test_late_inspection(channel, monkeypatch):
    """Filesystem latency counts in the shared budget too."""
    def inspect(path):
        """Exhaust the clock before returning endpoint facts."""
        channel[1][0] = 6
        return SimpleNamespace(st_mode=stat.S_IFSOCK)
    monkeypatch.setattr(transport, '_lstat', inspect)
    with pytest.raises(transport.ControlDeliveryError) as caught:
        send()
    assert caught.value.error_code == 'timeout' and not channel[0].calls


@pytest.mark.parametrize('status', ['ok', 'error'])
def test_real_fixture_socket(tmp_path, monkeypatch, status):
    """Exchange one request with a test-owned Unix socket, never a session."""
    if not hasattr(socket, 'AF_UNIX'):
        pytest.skip('Unix sockets unavailable')
    monkeypatch.setattr(transport, 'get_control_actions', lambda: ['plugin'])
    path = tmp_path / 'control.sock'
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen(1)
    server.settimeout(5)
    evidence = []
    def respond():
        """Echo the request correlation from exactly one fixture connection."""
        try:
            with server.accept()[0] as client:
                client.settimeout(5)
                data = b''
                while b'\n' not in data:
                    data += client.recv(4096)
                request = json.loads(data)
                evidence.append(request)
                client.sendall(json.dumps({'request_id': request['request_id'],
                                           'status': status}).encode() + b'\n')
        except BaseException as exc:
            evidence.append(exc)
    thread = threading.Thread(target=respond)
    thread.start()
    try:
        if status == 'ok':
            assert transport.send_to_control(path, 'plugin', {}).response['status'] == 'ok'
        else:
            with pytest.raises(transport.ControlDeliveryError) as caught:
                transport.send_to_control(path, 'plugin', {})
            assert caught.value.error_code == 'control_rejected'
    finally:
        thread.join(6)
        server.close()
        path.unlink()
        print(f'Deleted fixture socket: {path}')
    assert not thread.is_alive()
    assert len(evidence) == 1 and isinstance(evidence[0], dict)


def test_lazy_registry_and_path():
    """The real adapters preserve registered actions and canonical paths."""
    assert 'hard_interrupt' in transport.get_control_actions()
    assert transport.build_socket_path('/fixture', 's', '1').endswith('s.1.session.sock')


def test_late_socket_creation_closes(channel, monkeypatch):
    """Record socket custody before observing a late creation result."""
    sock, clock = channel
    def create():
        """Return an owned socket only after consuming the budget."""
        clock[0] = 6
        return sock
    monkeypatch.setattr(transport, '_new_socket', create)
    with pytest.raises(transport.ControlDeliveryError) as caught:
        send()
    assert caught.value.error_code == 'timeout' and sock.closed == 1
    assert sock.calls == ['close']


@pytest.mark.parametrize('late', [False, True])
def test_creation_error(channel, monkeypatch, late):
    """Observe creation errors and late failures without inventing ownership."""
    cause = OSError(errno.EIO, 'creation')
    def create():
        """Fail before acquiring a descriptor."""
        if late:
            channel[1][0] = 6
        raise cause
    monkeypatch.setattr(transport, '_new_socket', create)
    with pytest.raises(transport.ControlDeliveryError) as caught:
        send()
    assert caught.value.error_code == ('timeout' if late else 'transport_error')
    assert caught.value.__cause__ is cause and channel[0].closed == 0


def test_unsupported_platform(channel, monkeypatch):
    """Use a consumer-local stand-in instead of mutating the socket singleton."""
    monkeypatch.setattr(transport, 'socket', SimpleNamespace())
    with pytest.raises(transport.ControlDeliveryError) as caught:
        send()
    assert caught.value.error_code == 'unsupported_transport'


def test_remaining_before_operation(channel):
    """No connect/write follows an already exhausted budget."""
    channel[1][0] = 10
    with pytest.raises(transport.ControlDeliveryError):
        transport._operation(lambda: pytest.fail('late I/O'), 5, 'id', False)


def test_lazy_import(monkeypatch):
    """Reloading the shared module does not import runtime control handlers."""
    import builtins
    original = builtins.__import__
    def guarded(name, *args, **kwargs):
        """Reject eager handler/registry loading while permitting standard imports."""
        if name.startswith('topsailai.workspace.control'):
            pytest.fail('eager runtime import')
        return original(name, *args, **kwargs)
    with monkeypatch.context() as local:
        local.setattr(builtins, '__import__', guarded)
        exec(compile(Path(transport.__file__).read_text(), transport.__file__, "exec"),
             {"__name__": transport.__name__})


def test_dynamic_registry(monkeypatch):
    """Registration queries reflect plugin actions rather than a static list."""
    import sys
    class Registry:
        """Represent the real registration interface with a detached fake."""
        def list_actions(self):
            """Return actions installed by this registration call."""
            return self.actions
    def register(registry):
        """Install a plugin action absent from the built-in inventory."""
        registry.actions = ['plugin.new']
    monkeypatch.setitem(sys.modules, 'topsailai.workspace.control_channel.handler',
                        SimpleNamespace(ControlHandlerRegistry=Registry))
    monkeypatch.setitem(sys.modules, 'topsailai.workspace.control_handlers',
                        SimpleNamespace(register_control_handlers=register))
    assert transport.get_control_actions() == ['plugin.new']


def test_exact_limit(channel, monkeypatch):
    """A complete response exactly at the limit is accepted without truncation."""
    data = b'{"request_id":"correlation","status":"ok"}\n'
    monkeypatch.setattr(transport, 'RESPONSE_LIMIT', len(data))
    channel[0].frames = [data]
    assert send().response['status'] == 'ok'


def test_no_stdout(channel, capsys):
    """Protocol helpers emit neither success nor error diagnostic output."""
    send()
    channel[0].frames = [b'invalid\n']
    assert not transport.send_control_request('/fixture/control.sock', 'plugin', {}, 5)[0]
    captured = capsys.readouterr()
    assert not captured.out and not captured.err
