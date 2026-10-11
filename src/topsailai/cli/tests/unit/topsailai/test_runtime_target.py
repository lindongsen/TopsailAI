"""Unit checks for exact runtime target selection without live session I/O."""

from dataclasses import FrozenInstanceError
import errno
from pathlib import Path
import socket
from types import SimpleNamespace

import pytest

from cli_topsailai import runtime_target as rt


def alive(_pid):
    """Provide an injected living-process observation."""
    return rt.ProcessState.ALIVE


def dead(_pid):
    """Provide an injected exited-process observation."""
    return rt.ProcessState.DEAD


def record(folder, session="team.release.001", pid=123):
    """Create fixture-owned stdout evidence without starting any process."""
    path = folder / f"{session}.{pid}.session.stdout"
    path.touch()
    return path


def expect_error(code, exit_code, function, *args, **kwargs):
    """Assert exact structured classifications from a failing operation."""
    with pytest.raises(rt.RuntimeTargetError) as caught:
        function(*args, **kwargs)
    assert caught.value.error_code == code
    assert caught.value.exit_code == exit_code
    return caught.value


@pytest.mark.parametrize("session", ["team.release.001", "topsailai", "literal*id", " spaced "])
@pytest.mark.parametrize("selectors", ["session", "pid", "both"])
def test_exact_selection(tmp_path, session, selectors):
    """Support dotted and literal IDs under each selector combination."""
    stdout = record(tmp_path, session)
    kwargs = {"process_probe": alive}
    if selectors != "pid":
        kwargs["session_id"] = session
    if selectors != "session":
        kwargs["pid"] = 123
    target = rt.resolve_runtime_target(tmp_path, **kwargs)
    assert target == rt.RuntimeTarget(session, 123, stdout, tmp_path)
    with pytest.raises(FrozenInstanceError):
        target.pid = 9


@pytest.mark.parametrize("kwargs", [{}, {"pid": True}, {"pid": 0}, {"pid": -1},
    {"pid": "1"}, {"session_id": ""}, {"session_id": "."}, {"session_id": ".."},
    {"session_id": "a/b"}, {"session_id": "a\\b"}, {"session_id": "a\0b"},
    {"session_id": 12}])
def test_invalid_selectors_before_io(monkeypatch, tmp_path, kwargs):
    """Invalid selectors must fail before enumerating or probing."""
    def forbidden(*_args, **_kwargs):
        """Fail the test if validation performs dependent I/O."""
        pytest.fail("unexpected I/O")
    monkeypatch.setattr(rt, "_check_directory", forbidden)
    expect_error("usage_error", 2, rt.resolve_runtime_target, tmp_path,
                 process_probe=forbidden, **kwargs)


def test_bad_path_and_missing_directory(tmp_path):
    """Classify invalid and unavailable directory inputs distinctly."""
    for path in [Path("relative"), str(tmp_path)]:
        expect_error("usage_error", 2, rt.resolve_runtime_target, path, pid=1)
    expect_error("target_not_found", 3, rt.resolve_runtime_target,
                 tmp_path / "missing", pid=1)
    file = record(tmp_path)
    expect_error("endpoint_invalid", 4, rt.resolve_runtime_target, file, pid=1)
    expect_error("target_not_found", 3, rt.resolve_runtime_target,
                 tmp_path, pid=1, process_probe=alive)


def test_dead_mismatch_and_no_fallback(tmp_path):
    """Never substitute another session or PID after an exact failure."""
    record(tmp_path, "a", 1)
    record(tmp_path, "a", 2)
    expect_error("stale_target", 3, rt.resolve_runtime_target, tmp_path,
                 session_id="a", pid=1, process_probe=dead)
    expect_error("target_mismatch", 3, rt.resolve_runtime_target, tmp_path,
                 session_id="b", pid=1, process_probe=alive)
    expect_error("target_not_found", 3, rt.resolve_runtime_target, tmp_path,
                 session_id="a", pid=99, process_probe=alive)


@pytest.mark.parametrize("selector", [{"session_id": "a"}, {"pid": 1}])
def test_ambiguity_before_endpoints(tmp_path, selector):
    """Endpoint availability must not suppress an alive candidate."""
    record(tmp_path, "a", 1)
    if "pid" in selector:
        record(tmp_path, "b", 1)
    else:
        record(tmp_path, "a", 2)
    (tmp_path / "a.1.session.pipe").touch()
    expect_error("ambiguous_target", 3, rt.resolve_runtime_target, tmp_path,
                 process_probe=alive, **selector)


def test_dead_and_unknown_candidates(tmp_path):
    """Exclude dead candidates but never exclude an unknown candidate."""
    record(tmp_path, "a", 1)
    record(tmp_path, "a", 2)
    target = rt.resolve_runtime_target(tmp_path, session_id="a",
        process_probe=lambda pid: alive(pid) if pid == 1 else dead(pid))
    assert target.pid == 1
    for unknown in [rt.ProcessState.UNKNOWN, None, "alive"]:
        expect_error("unsupported_transport", 4, rt.resolve_runtime_target,
            tmp_path, session_id="a",
            process_probe=lambda pid: alive(pid) if pid == 1 else unknown)


def test_invalid_stdout_evidence(tmp_path):
    """Ignore task-only, symlink, nonregular and malformed filenames."""
    record(tmp_path, "other", 9)
    (tmp_path / "a.1.session.stdout").symlink_to(tmp_path / "other.9.session.stdout")
    (tmp_path / "a.2.session.stdout").mkdir()
    for name in ["a.3.task.stdout", "a.4.stdout", "a.bad.session.stdout",
                 "a.0.session.stdout", "a.-2.session.stdout", "5.session.stdout"]:
        (tmp_path / name).touch()
    expect_error("target_not_found", 3, rt.resolve_runtime_target, tmp_path,
                 session_id="a", process_probe=alive)
    expect_error("target_not_found", 3, rt.resolve_runtime_target, tmp_path,
                 pid=3, process_probe=alive)


def test_permissions_and_unexpected_io(monkeypatch, tmp_path):
    """Access failures are classified and unexpected I/O retains its identity."""
    record(tmp_path)
    def denied(_pid):
        """Inject a process observation permission failure."""
        raise PermissionError("denied")
    error = expect_error("permission_denied", 4, rt.resolve_runtime_target,
                         tmp_path, pid=123, process_probe=denied)
    assert isinstance(error.__cause__, PermissionError)
    def failing_iter(_path):
        """Inject denied directory enumeration."""
        raise PermissionError("denied")
    monkeypatch.setattr(Path, "iterdir", failing_iter)
    expect_error("permission_denied", 4, rt.resolve_runtime_target, tmp_path, pid=123)
    failure = OSError(errno.EIO, "device failure")
    def failing_stat(_path):
        """Inject unexpected filesystem error without normalizing it."""
        raise failure
    monkeypatch.setattr(Path, "lstat", failing_stat)
    with pytest.raises(OSError) as caught:
        rt.resolve_runtime_target(tmp_path, pid=123)
    assert caught.value is failure


@pytest.mark.parametrize("failure", [ProcessLookupError(), PermissionError(),
    OSError(errno.EIO, "io"), OverflowError(), ValueError(), NotImplementedError(), None])
def test_default_probe(monkeypatch, failure):
    """Use an isolated os stand-in, checking only signal zero."""
    calls = []
    def kill(pid, sig):
        """Record the safe probe and inject an observation result."""
        calls.append((pid, sig))
        if failure is not None:
            raise failure
    monkeypatch.setattr(rt, "os", SimpleNamespace(name="posix", kill=kill))
    if isinstance(failure, PermissionError):
        expect_error("permission_denied", 4, rt.probe_process, 123)
    else:
        expected = rt.ProcessState.ALIVE if failure is None else rt.ProcessState.UNKNOWN
        if isinstance(failure, ProcessLookupError):
            expected = rt.ProcessState.DEAD
        assert rt.probe_process(123) is expected
    assert calls == [(123, 0)]
    monkeypatch.setattr(rt, "os", SimpleNamespace(name="nt"))
    assert rt.probe_process(123) is rt.ProcessState.UNKNOWN


def test_revalidate(tmp_path):
    """Recheck original evidence and process, never reselect a candidate."""
    stdout = record(tmp_path, "a", 1)
    target = rt.resolve_runtime_target(tmp_path, pid=1, process_probe=alive)
    rt.revalidate_runtime_target(target, process_probe=alive)
    expect_error("stale_target", 3, rt.revalidate_runtime_target,
                 target, process_probe=dead)
    record(tmp_path, "a", 2)
    stdout.unlink()
    print(f"Deleted fixture: {stdout}")
    expect_error("stale_target", 3, rt.revalidate_runtime_target,
                 target, process_probe=alive)
    stdout.symlink_to(tmp_path / "a.2.session.stdout")
    expect_error("stale_target", 3, rt.revalidate_runtime_target,
                 target, process_probe=alive)
    changed = rt.RuntimeTarget("b", 2, tmp_path / "a.2.session.stdout", tmp_path)
    expect_error("stale_target", 3, rt.revalidate_runtime_target,
                 changed, process_probe=alive)
    outside = rt.RuntimeTarget("a", 1, tmp_path.parent / "a.1.session.stdout", tmp_path)
    expect_error("stale_target", 3, rt.revalidate_runtime_target,
                 outside, process_probe=alive)


def test_endpoint_validation(tmp_path):
    """Validate missing and existing endpoints without creating a destination."""
    target = rt.RuntimeTarget("a", 1, record(tmp_path, "a", 1), tmp_path)
    destination = tmp_path / "a.inject.jsonl"
    assert rt.validate_runtime_endpoint(target, endpoint_path=destination,
        endpoint_kind="injection") == destination
    assert not destination.exists()
    for kind in ["fifo", "socket"]:
        expect_error("endpoint_missing", 4, rt.validate_runtime_endpoint, target,
                     endpoint_path=destination, endpoint_kind=kind)
    destination.touch()
    assert rt.validate_runtime_endpoint(target, endpoint_path=destination,
        endpoint_kind="injection") == destination
    for kind in ["fifo", "socket"]:
        expect_error("endpoint_invalid", 4, rt.validate_runtime_endpoint, target,
                     endpoint_path=destination, endpoint_kind=kind)
    for path in [tmp_path, tmp_path / ".." / "escape", tmp_path.parent / "escape"]:
        expect_error("endpoint_invalid", 4, rt.validate_runtime_endpoint, target,
                     endpoint_path=path, endpoint_kind="injection")
    link = tmp_path / "link"
    link.symlink_to(destination)
    expect_error("endpoint_invalid", 4, rt.validate_runtime_endpoint, target,
                 endpoint_path=link, endpoint_kind="injection")
    expect_error("usage_error", 2, rt.validate_runtime_endpoint, target,
                 endpoint_path=destination, endpoint_kind="wrong")
    nested = tmp_path / "nested"
    nested.mkdir()
    assert rt.validate_runtime_endpoint(target, endpoint_path=nested / "new",
        endpoint_kind="injection") == nested / "new"
    directory_link = tmp_path / "linked"
    directory_link.symlink_to(nested, target_is_directory=True)
    expect_error("endpoint_invalid", 4, rt.validate_runtime_endpoint, target,
                 endpoint_path=directory_link / "new", endpoint_kind="injection")


def test_real_fixture_endpoint_types(tmp_path):
    """Use only fixture FIFO/socket resources, never live session endpoints."""
    import os
    if not hasattr(os, "mkfifo") or not hasattr(socket, "AF_UNIX"):
        pytest.skip("fixture FIFO/Unix sockets unsupported")
    target = rt.RuntimeTarget("a", 1, record(tmp_path, "a", 1), tmp_path)
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    assert rt.validate_runtime_endpoint(target, endpoint_path=fifo, endpoint_kind="fifo") == fifo
    with socket.socket(socket.AF_UNIX) as server:
        endpoint = tmp_path / "socket"
        server.bind(str(endpoint))
        assert rt.validate_runtime_endpoint(target, endpoint_path=endpoint,
                                            endpoint_kind="socket") == endpoint
    fifo.unlink()
    print(f"Deleted fixture: {fifo}")
    fifo.touch()
    expect_error("endpoint_invalid", 4, rt.validate_runtime_endpoint, target,
                 endpoint_path=fifo, endpoint_kind="fifo")


def test_stat_permission_and_disappearing_evidence(monkeypatch, tmp_path):
    """Preserve permission causes and handle a vanished directory entry."""
    def denied(_path):
        """Inject lstat permission failure."""
        raise PermissionError("denied")
    monkeypatch.setattr(Path, "lstat", denied)
    expect_error("permission_denied", 4, rt.resolve_runtime_target, tmp_path, pid=1)
    monkeypatch.undo()
    ghost = tmp_path / "a.1.session.stdout"
    monkeypatch.setattr(Path, "iterdir", lambda _path: iter([ghost]))
    expect_error("target_not_found", 3, rt.resolve_runtime_target, tmp_path, pid=1)
