"""Focused tests for strict, side-effect-free selection mapping decoders."""
from __future__ import annotations
import json
import os
import subprocess
import sys
from pathlib import Path
import pytest
from topsailai.hooks.resource_selection_contracts import HookResourceSelection
from topsailai.hooks.resource_selection_mapping import (
    decode_point_resource_selection,
    decode_resource_selection,
)
@pytest.mark.parametrize(
    ("kind", "source", "expected_files", "expected_folder"),
    [
        ("modules", {"file": "module.py"}, ("module.py",), None),
        ("modules", {"files": ["a.py", "b.py"]}, ("a.py", "b.py"), None),
        ("modules", {"folder": "modules"}, (), "modules"),
        ("scripts", {"file": "run.sh"}, ("run.sh",), None),
        ("scripts", {"files": ["a.sh", "b.sh"]}, ("a.sh", "b.sh"), None),
        ("scripts", {"folder": "scripts"}, (), "scripts"),
    ],
)
def test_decoder_supports_both_point_kinds_and_all_source_forms(
    kind: str,
    source: dict[str, object],
    expected_files: tuple[str, ...],
    expected_folder: str | None,
) -> None:
    """Modules and Scripts decode to exact values with the other kind absent."""
    point = decode_point_resource_selection({kind: source})
    selected = getattr(point, kind)
    other = point.scripts if kind == "modules" else point.modules
    assert isinstance(selected, HookResourceSelection)
    assert selected.files == expected_files
    assert selected.folder == expected_folder
    assert other is None
def test_decoder_normalizes_and_detaches_nested_values() -> None:
    """Later caller mutations do not alter decoded records."""
    source = {"modules": {"files": ["a.py", "b.py"]}, "scripts": {"folder": "scripts"}}
    point = decode_point_resource_selection(source)
    source["modules"]["files"].append("changed.py")  # type: ignore[index]
    source["scripts"]["folder"] = "changed"  # type: ignore[index]
    assert point.modules is not None and point.modules.files == ("a.py", "b.py")
    assert point.scripts is not None and point.scripts.folder == "scripts"
    assert decode_resource_selection({"file": "one.py"}).files == ("one.py",)
    assert decode_point_resource_selection({}).modules is None
@pytest.mark.parametrize("path", ["x" * 4096, "目录/脚本.sh", "/absolute/path"])
def test_decoder_preserves_boundary_and_unicode_paths(path: str) -> None:
    """Accepted paths remain unresolved text, including Unicode and absolute paths."""
    source_forms = ("file", "folder") if len(path) == 4096 else ("folder",)
    for key in source_forms:
        selection = decode_resource_selection({key: path})
        assert selection.files == ((path,) if key == "file" else ())
        assert selection.folder == (path if key == "folder" else None)
def test_decoder_rejects_path_boundaries_and_nul_in_every_path_source() -> None:
    """NUL and 4097-character paths fail for file, files, and folder."""
    invalid = (
        {"file": "a\x00b"},
        {"files": ["a", "b\x00c"]},
        {"folder": "a\x00b"},
        {"file": "x" * 4097},
        {"files": ["x" * 4097]},
        {"folder": "x" * 4097},
    )
    for value in invalid:
        with pytest.raises(ValueError, match="invalid Hook resource selection mapping"):
            decode_resource_selection(value)
@pytest.mark.parametrize(
    "value",
    [
        {},
        {"file": "a", "folder": "b"},
        {"file": "a", "files": ["a"]},
        {"file": True},
        {"file": 1},
        {"files": []},
        {"files": ()},
        {"files": ["a", True]},
        {"files": ["a", 1]},
        {"files": ["a", "a"]},
        {"folder": ""},
        {"folder": None},
        {"unknown": "a"},
        [],
        None,
        {1: "a"},
    ],
)
def test_decoder_rejects_malformed_selection(value: object) -> None:
    """Malformed containers, types, nulls, conflicts, unknowns, and duplicates fail closed."""
    with pytest.raises((TypeError, ValueError)):
        decode_resource_selection(value)
def test_decoder_rejects_malformed_point_selection() -> None:
    """Point mappings accept only modules and scripts with non-null selectors."""
    for value in (
        {"unknown": {"file": "a"}},
        {"modules": None},
        {"scripts": []},
        {"modules": {"file": "a", "files": ["b"]}},
        [],
        None,
    ):
        with pytest.raises(ValueError, match="invalid Hook resource selection mapping"):
            decode_point_resource_selection(value)
def test_decoder_enforces_exact_member_boundary() -> None:
    """The exact 1024 boundary is accepted and the next member fails."""
    accepted = [str(index) for index in range(1024)]
    assert decode_resource_selection({"files": accepted}).files == tuple(accepted)
    with pytest.raises(ValueError, match="invalid Hook resource selection mapping"):
        decode_resource_selection({"files": accepted + ["1024"]})
class _MaliciousList(list[str]):
    """A list lookalike whose behavior must not be invoked by the decoder."""
    def __iter__(self):
        raise AssertionError("custom iteration must not run")
    def __len__(self):
        raise AssertionError("custom length must not run")
    def __eq__(self, other: object) -> bool:
        raise AssertionError("custom equality must not run")
class _MaliciousString(str):
    """A string lookalike whose content operations must not be invoked."""
    def __bool__(self):
        raise AssertionError("custom truth testing must not run")
    def __len__(self):
        raise AssertionError("custom length must not run")
    def __contains__(self, value: object) -> bool:
        raise AssertionError("custom containment must not run")
    def __eq__(self, other: object) -> bool:
        raise AssertionError("custom equality must not run")
    def __str__(self) -> str:
        raise AssertionError("custom string conversion must not run")
class _MaliciousDict(dict):
    """A mapping lookalike rejected before custom mapping behavior runs."""
    def __iter__(self):
        raise AssertionError("custom mapping iteration must not run")
    def __len__(self):
        raise AssertionError("custom mapping length must not run")
    def __getitem__(self, key):
        raise AssertionError("custom mapping item access must not run")
    def __eq__(self, other: object) -> bool:
        raise AssertionError("custom mapping equality must not run")
    def __str__(self) -> str:
        raise AssertionError("custom mapping string conversion must not run")
@pytest.mark.parametrize(
    ("source", "argument"),
    [
        ({"files": _MaliciousList(["a"])}, "mapping"),
        (_MaliciousDict(file="a"), "mapping"),
        ({"file": _MaliciousString("a")}, "path"),
        ({"files": [_MaliciousString("a")]}, "path"),
        ({"folder": _MaliciousString("a")}, "path"),
    ],
)
def test_decoder_rejects_lookalikes_without_invoking_them(
    source: object, argument: str
) -> None:
    """Exact built-in checks prevent arbitrary mapping, container, and path behavior."""
    with pytest.raises(ValueError, match="invalid Hook resource selection mapping"):
        decode_resource_selection(source)
@pytest.mark.parametrize("path_source", ["file", "files", "folder"])
def test_decoder_rejects_malicious_string_on_each_path_branch(path_source: str) -> None:
    """Path lookalikes are rejected before content operations execute."""
    value: object
    if path_source == "files":
        value = {"files": [_MaliciousString("a")]}
    else:
        value = {path_source: _MaliciousString("a")}
    with pytest.raises(ValueError, match="invalid Hook resource selection mapping"):
        decode_resource_selection(value)
def _run_bounded_child(script: str, cwd: str, *, args: tuple[str, ...] = ()) -> tuple[int, bytes, bytes, bool]:
    """Run one owned child with bounded output and independent cleanup."""
    import selectors
    import time
    limit = 65536
    state = {
        "output": {"stdout": bytearray(), "stderr": bytearray()},
        "selector": None, "primary": None, "host_primary": None,
        "cleanup_errors": [], "overflow": False,
    }
    process = None
    def capture(error: BaseException, *, primary: bool = False) -> None:
        if isinstance(error, (KeyboardInterrupt, SystemExit, GeneratorExit)):
            if state["host_primary"] is None:
                state["host_primary"] = error
            return
        if primary and state["primary"] is None:
            state["primary"] = error
        else:
            state["cleanup_errors"].append(error)
    def attempt(action, *, primary: bool = False) -> None:
        try:
            action()
        except BaseException as error:
            capture(error, primary=primary)
    def settle() -> None:
        running = True
        try:
            running = process.poll() is None
        except BaseException as error:
            capture(error)
        if not running:
            return
        attempt(process.terminate)
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            attempt(process.kill)
            attempt(lambda: process.wait(timeout=2))
        except BaseException as error:
            capture(error)
            attempt(process.kill)
            attempt(lambda: process.wait(timeout=2))
    command = [sys.executable, "-c", script, *args]
    process = subprocess.Popen(
        command, cwd=cwd, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        state["selector"] = selectors.DefaultSelector()
        selector = state["selector"]
        assert process.stdout is not None and process.stderr is not None
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        deadline = time.monotonic() + 10
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("bounded child output timeout")
            for key, _ in selector.select(remaining):
                buffer = state["output"][key.data]
                chunk = os.read(key.fileobj.fileno(), limit - len(buffer) + 1)
                if not chunk:
                    selector.unregister(key.fileobj)
                    attempt(key.fileobj.close)
                    continue
                available = limit - len(buffer)
                if len(chunk) > available:
                    buffer.extend(chunk[:available])
                    state["overflow"] = True
                    raise OverflowError(f"{key.data} output limit exceeded")
                buffer.extend(chunk)
        if process.poll() is None:
            process.wait(timeout=2)
    except BaseException as error:
        capture(error, primary=True)
    finally:
        attempt(settle)
        selector = state.get("selector")
        if selector is not None:
            attempt(selector.close)
        for stream in (getattr(process, "stdout", None), getattr(process, "stderr", None)):
            if stream is not None: attempt(stream.close)
    host_primary = state["host_primary"]
    primary = state["primary"]
    if host_primary is not None:
        if primary is not None:
            host_primary.__context__ = primary
        raise host_primary
    if primary is not None:
        if state["cleanup_errors"]:
            primary.add_note("cleanup failures: " + "; ".join(type(error).__name__ for error in state["cleanup_errors"]))
        raise primary
    if state["cleanup_errors"]:
        raise RuntimeError("child cleanup failed: " + "; ".join(type(error).__name__ for error in state["cleanup_errors"]))
    return process.returncode, bytes(state["output"]["stdout"]), bytes(state["output"]["stderr"]), state["overflow"]
class _CollectorStream:
    """Minimal pipe stand-in recording independent closure and failures."""
    def __init__(self, name: str, close_error: BaseException | bool = False) -> None:
        self.name, self.closed, self.close_error = name, False, close_error
    def fileno(self) -> int:
        return 1 if self.name == "stdout" else 2
    def close(self) -> None:
        self.closed = True
        if self.close_error:
            if isinstance(self.close_error, BaseException):
                raise self.close_error
            raise OSError(f"{self.name} close failed")
class _CollectorProcess:
    """Exact-child stand-in with a configurable settlement state machine."""
    def __init__(self, *, completes=False, wait_error=False, poll_error=False,
                 stdout_close_error=False, stderr_close_error=False) -> None:
        self.stdout, self.stderr = _CollectorStream("stdout", stdout_close_error), _CollectorStream("stderr", stderr_close_error)
        self.returncode = 0 if completes else None
        self.wait_error, self.poll_error = wait_error, poll_error
        self.terminate_calls, self.kill_calls, self.wait_calls = 0, 0, []
        self.terminate_targets, self.kill_targets = [], []
        self.terminate_reaps, self.reaped, self.call_order = True, completes, []
    def poll(self):
        self.call_order.append("poll")
        if self.poll_error:
            self.poll_error = False
            raise OSError("poll failed")
        return self.returncode
    def terminate(self) -> None:
        self.call_order.append("terminate")
        self.terminate_calls += 1
        self.terminate_targets.append(self)
        if self.returncode is None and self.terminate_reaps:
            self.returncode, self.reaped = -15, True
    def kill(self) -> None:
        self.call_order.append("kill")
        self.kill_calls += 1
        self.kill_targets.append(self)
        self.returncode = -9
    def wait(self, timeout=None) -> int:
        self.call_order.append(("wait", timeout))
        self.wait_calls.append(timeout)
        if self.wait_error:
            self.wait_error = False
            raise OSError("wait failed")
        if self.returncode is None:
            raise subprocess.TimeoutExpired("child", timeout)
        self.reaped = True
        return self.returncode

class _CollectorSelector:
    """Selector fake with independent setup, read, and close failures."""
    def __init__(self, failure=None, close_error: BaseException | bool = False) -> None:
        self.failure, self.close_error, self.registered, self.closed = failure, close_error, [], False

    def register(self, stream, _events, data) -> None:
        if self.failure == "register":
            raise OSError("registration failed")
        self.registered.append((stream, data))

    def get_map(self):
        return self.registered

    def select(self, _timeout):
        if self.failure == "select":
            raise OSError("selection failed")
        if self.failure == "timeout":
            raise TimeoutError("bounded child output timeout")
        entries = self.registered
        if self.failure == "stderr-overflow":
            entries = [item for item in entries if item[1] == "stderr"]
        stream, data = entries[0]
        return [(type("Key", (), {"fileobj": stream, "data": data}), None)]

    def unregister(self, stream) -> None:
        self.registered = [(item, data) for item, data in self.registered if item is not stream]

    def close(self) -> None:
        self.closed = True
        if self.close_error:
            if isinstance(self.close_error, BaseException):
                raise self.close_error
            raise OSError("selector close failed")

def _exercise_collector_failure(monkeypatch, failure: str):
    """Run the real collector helper with concise controlled seams."""
    import selectors
    process = _CollectorProcess(
        completes=failure in {"normal", "selector-close", "stdout-close", "stderr-close"},
        wait_error=failure == "wait", poll_error=failure == "poll",
        stdout_close_error=failure == "stdout-close", stderr_close_error=failure == "stderr-close",
    )
    process.terminate_reaps = failure not in {"timeout", "wait"}
    selector = _CollectorSelector(failure if failure in {"register", "select", "timeout", "stderr-overflow"} else None,
                                  close_error=failure == "selector-close")
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(selectors, "DefaultSelector", lambda: (_ for _ in ()).throw(OSError("setup failed")) if failure == "setup" else selector)
    if failure in {"read", "primary-poll", "primary-wait"}:
        monkeypatch.setattr(os, "read", lambda *_args: (_ for _ in ()).throw(OSError("primary read failed")))
    elif failure in {"stdout-overflow", "stderr-overflow"}:
        target = 1 if failure == "stdout-overflow" else 2
        monkeypatch.setattr(os, "read", lambda fd, _size: b"x" * 65537 if fd == target else b"")
    else:
        monkeypatch.setattr(os, "read", lambda *_args: b"")
    return process, selector
@pytest.mark.parametrize("failure", ["normal", "stdout-overflow", "stderr-overflow", "timeout", "setup", "register", "select", "read", "poll", "wait", "selector-close", "stdout-close", "stderr-close"])
def test_bounded_collector_failure_matrix(monkeypatch, failure: str) -> None:
    process, selector = _exercise_collector_failure(monkeypatch, failure)
    expected = {"setup": "setup failed", "register": "registration failed", "select": "selection failed", "read": "primary read failed"}.get(failure)
    if expected:
        with pytest.raises(OSError, match=expected):
            _run_bounded_child("", ".")
    elif failure in {"selector-close", "stdout-close", "stderr-close", "poll", "wait"}:
        with pytest.raises((RuntimeError, OSError)):
            _run_bounded_child("", ".")
    elif failure in {"stdout-overflow", "stderr-overflow", "timeout"}:
        with pytest.raises((OverflowError, TimeoutError)):
            _run_bounded_child("", ".")
    else:
        result = _run_bounded_child("", ".")
        assert result[3] is False
    assert process.stdout.closed and process.stderr.closed
    if failure != "setup":
        assert selector.closed
    assert all(timeout == 2 for timeout in process.wait_calls)
    assert process.terminate_targets == [process] if process.terminate_calls else True
    assert process.kill_targets == [process] if process.kill_calls else True

def test_bounded_collector_primary_exception_survives_poll_and_wait_cleanup_failures(monkeypatch) -> None:
    for failure in ("primary-poll", "primary-wait"):
        process, selector = _exercise_collector_failure(monkeypatch, failure)
        if failure == "primary-poll":
            process.poll_error = True
        else:
            process.wait_error = True
        with pytest.raises(OSError, match="primary read failed") as caught:
            _run_bounded_child("", ".")
        assert caught.value.__notes__ and process.stderr.closed and selector.closed

def test_bounded_collector_non_timeout_wait_failure_continues_settlement(monkeypatch) -> None:
    process, _selector = _exercise_collector_failure(monkeypatch, "wait")
    with pytest.raises(OSError, match="wait failed"):
        _run_bounded_child("", ".")
    assert process.terminate_calls == 1 and process.kill_calls == 1
    assert process.wait_calls == [2, 2, 2] and process.reaped

def test_bounded_collector_termination_escalates_after_timeout(monkeypatch) -> None:
    process, _selector = _exercise_collector_failure(monkeypatch, "timeout")
    with pytest.raises(TimeoutError):
        _run_bounded_child("", ".")
    assert process.call_order[-4:] == ["terminate", ("wait", 2), "kill", ("wait", 2)]
    assert process.terminate_targets == process.kill_targets == [process]
    assert process.wait_calls == [2, 2] and process.reaped

def test_bounded_collector_forwards_child_arguments(monkeypatch) -> None:
    """Optional child arguments are appended without changing ownership."""
    import selectors
    process, launched = _CollectorProcess(completes=True), []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: (launched.append(a[0]), process)[1])
    monkeypatch.setattr(selectors, "DefaultSelector", _CollectorSelector)
    monkeypatch.setattr(os, "read", lambda *_args: b"")
    assert _run_bounded_child("", ".", args=("root",)) == (0, b"", b"", False)
    assert launched == [[sys.executable, "-c", "", "root"]]

def test_bounded_collector_requests_remaining_capacity_plus_one_and_retains_cap(monkeypatch) -> None:
    import selectors
    process, selector = _CollectorProcess(completes=True), _CollectorSelector()
    requested_sizes, chunks = [], iter((b"a" * (65536 - 2), b"bc", b""))
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(selectors, "DefaultSelector", lambda: selector)
    def read(fd, size):
        if fd != 1:
            return b""
        requested_sizes.append(size)
        chunk = next(chunks)
        return chunk[:size]
    monkeypatch.setattr(os, "read", read)
    result = _run_bounded_child("", ".")
    assert requested_sizes == [65537, 3, 1]
    assert len(result[1]) <= 65536 and len(result[2]) <= 65536
    assert process.stdout.closed and process.stderr.closed
def _exception_graph_nodes(error: BaseException) -> tuple[BaseException, ...]:
    """Return exception graph nodes while rejecting only active-path cycles."""
    active, visited, nodes = set(), set(), []
    def visit(current):
        if current is None: return
        identity = id(current)
        assert identity not in active
        if identity in visited: return
        active.add(identity); nodes.append(current)
        visit(current.__cause__); visit(current.__context__)
        active.remove(identity); visited.add(identity)
    visit(error)
    return tuple(nodes)
_assert_exception_graph_acyclic = _exception_graph_nodes
def _capture_collector_call(*args, **kwargs):
    """Capture host-control exceptions locally so pytest remains in control."""
    try:
        _run_bounded_child(*args, **kwargs)
    except BaseException as error:
        return error
    raise AssertionError("collector unexpectedly completed")
@pytest.mark.parametrize("has_primary", [False, True])
def test_bounded_collector_owns_child_before_earliest_initialization_failure(monkeypatch, has_primary) -> None:
    """Earliest post-launch failure settles the child and closes independent streams."""
    import selectors
    process = _CollectorProcess(completes=not has_primary)
    process.terminate_reaps = False
    injected = OSError("earliest initialization failed")
    selector_error, later_error = SystemExit("earliest cleanup host control"), OSError("later cleanup")
    selector = _CollectorSelector("select" if has_primary else None, close_error=selector_error)
    process.stdout.close_error = later_error
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: process)
    if has_primary:
        monkeypatch.setattr(selectors, "DefaultSelector", lambda: (_ for _ in ()).throw(injected))
    else:
        monkeypatch.setattr(os, "read", lambda *_args: b"")
        monkeypatch.setattr(selectors, "DefaultSelector", lambda: selector)
    caught = _capture_collector_call("", ".")
    assert caught is (injected if has_primary else selector_error)
    if has_primary:
        assert process.terminate_targets == process.kill_targets == [process]
        assert process.wait_calls == [2, 2] and process.reaped
        assert not selector.closed
    else:
        assert process.terminate_targets == process.kill_targets == []
        assert process.wait_calls == [] and selector.closed
        assert _exception_graph_nodes(caught) == (selector_error,)
    assert process.stdout.closed and process.stderr.closed and _assert_exception_graph_acyclic(caught)
@pytest.mark.parametrize("host_type", [KeyboardInterrupt, SystemExit, GeneratorExit])
def test_bounded_collector_host_control_active_primary(host_type, monkeypatch) -> None:
    """An active host-control primary wins over later ordinary cleanup failure."""
    import selectors
    process = _CollectorProcess(completes=True, stdout_close_error=True)
    selector = _CollectorSelector()
    injected = host_type()
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(selectors, "DefaultSelector", lambda: selector)
    monkeypatch.setattr(os, "read", lambda *a: (_ for _ in ()).throw(injected))
    caught = _capture_collector_call("", ".")
    assert caught is injected and process.stdout.closed and process.stderr.closed and selector.closed
    _assert_exception_graph_acyclic(caught)

def test_bounded_collector_host_control_cleanup_precedence(monkeypatch) -> None:
    """Cleanup host control wins while retaining the ordinary primary."""
    import selectors
    process = _CollectorProcess(completes=True, stderr_close_error=OSError("later cleanup"))
    ordinary = OSError("ordinary primary")
    selector = _CollectorSelector(close_error=SystemExit("first cleanup host control"))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(selectors, "DefaultSelector", lambda: selector)
    monkeypatch.setattr(os, "read", lambda *a: (_ for _ in ()).throw(ordinary))
    caught = _capture_collector_call("", ".")
    nodes = _assert_exception_graph_acyclic(caught)
    assert caught is selector.close_error and ordinary in nodes
    assert process.stderr.closed and process.stdout.closed and selector.closed

def test_bounded_collector_host_control_earliest_cleanup_wins(monkeypatch) -> None:
    """The first cleanup host control wins while all independent closes run."""
    import selectors
    process = _CollectorProcess(completes=True, stdout_close_error=SystemExit())
    selector = _CollectorSelector("select", close_error=GeneratorExit())
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(selectors, "DefaultSelector", lambda: selector)
    monkeypatch.setattr(os, "read", lambda *a: b"")
    caught = _capture_collector_call("", ".")
    assert caught is selector.close_error
    assert selector.closed and process.stdout.closed and process.stderr.closed
    assert _assert_exception_graph_acyclic(caught)

def test_exception_graph_allows_shared_ancestor_and_rejects_context_cycle() -> None:
    """Both exception edges are checked without rejecting shared ancestry."""
    ancestor, cause, context, root = (OSError(name) for name in ("ancestor", "cause", "context", "root"))
    cause.__context__, context.__cause__, root.__cause__, root.__context__ = ancestor, ancestor, cause, context
    assert ancestor in _assert_exception_graph_acyclic(root)
    context.__context__ = root
    with pytest.raises(AssertionError):
        _assert_exception_graph_acyclic(root)

def test_decoder_has_no_external_side_effects_in_isolated_process(monkeypatch) -> None:
    """Load and exercise both U1 modules in a guarded child process."""
    source_root = str(Path(__file__).resolve().parents[3])
    script = r'''
import builtins
import importlib.util
import json
import os
import pathlib
import sys
import types

root = pathlib.Path(sys.argv[1])
required_stdlib = {"__future__", "dataclasses", "typing"}
allowed_project = {"topsailai.hooks.resource_selection_contracts", "topsailai.hooks.resource_selection_mapping"}
original_import = builtins.__import__
seen_imports = []

def guard_import(name, globals=None, locals=None, fromlist=(), level=0):
    seen_imports.append((name, tuple(fromlist or ()), level))
    if "runtime" in name.lower() or any(type(item) is str and "runtime" in item.lower() for item in (fromlist or ())):
        raise AssertionError("forbidden Runtime import")
    if name not in required_stdlib and name not in allowed_project:
        raise AssertionError("import outside explicit U1 allowlist: " + repr((name, tuple(fromlist or ()), level)))
    return original_import(name, globals, locals, fromlist, level)

def namespace_has_runtime_origin(namespace):
    if type(namespace) is not dict:
        return False
    for value in namespace.values():
        if type(value) is types.ModuleType:
            module_name = vars(value).get("__name__")
        elif type(value) is types.FunctionType:
            module_name = value.__module__
        elif type(value) is type:
            module_name = vars(value).get("__module__")
        else:
            continue
        if type(module_name) is str and "runtime" in module_name.lower():
            return True
    return False

package = types.ModuleType("topsailai")
package.__path__ = [str(root)]
hooks = types.ModuleType("topsailai.hooks")
hooks.__path__ = [str(root / "hooks")]
sys.modules["topsailai"] = package
sys.modules["topsailai.hooks"] = hooks
for name in ("resource_selection_contracts", "resource_selection_mapping"):
    path = root / "hooks" / (name + ".py")
    spec = importlib.util.spec_from_file_location("topsailai.hooks." + name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
contracts = sys.modules["topsailai.hooks.resource_selection_contracts"]
mapping = sys.modules["topsailai.hooks.resource_selection_mapping"]

builtins.__import__ = guard_import
try:
    try:
        builtins.__import__("topsailai.not_allowed", fromlist=("x",))
    except AssertionError as error:
        assert str(error).startswith("import outside explicit U1 allowlist:")
    else:
        raise AssertionError("non-allowlisted project import was accepted")
    try:
        builtins.__import__("topsailai.hooks.runtime", fromlist=())
    except AssertionError as error:
        assert str(error) == "forbidden Runtime import"
    else:
        raise AssertionError("Runtime import-name rejection was not proven")
    try:
        builtins.__import__("dataclasses", fromlist=("RuntimeAlias",))
    except AssertionError as error:
        assert str(error) == "forbidden Runtime import"
    else:
        raise AssertionError("Runtime fromlist rejection was masked")
    RuntimeOrigin = type("RuntimeOrigin", (), {})
    RuntimeOrigin.__module__ = "topsailai.hooks.runtime"
    assert namespace_has_runtime_origin({"helper": RuntimeOrigin})
    class AttributeAccessSentinel:
        def __getattribute__(self, name):
            raise AssertionError("arbitrary metadata access was invoked: " + name)
    assert not namespace_has_runtime_origin({"innocuous": AttributeAccessSentinel()})

    for module in (contracts, mapping):
        assert not namespace_has_runtime_origin(module.__dict__)
    calls = []
    def blocked(name):
        def probe(*args, **kwargs):
            calls.append(name)
            raise AssertionError(name)
        return probe
    builtins.open = blocked("open")
    for name in ("stat", "lstat", "listdir", "scandir", "getenv"):
        setattr(os, name, blocked(name))
    class EnvironmentProxy:
        def __getitem__(self, key):
            calls.append("environ")
            raise AssertionError("environ")
        def get(self, *args, **kwargs):
            calls.append("environ")
            raise AssertionError("environ")
    os.environ = EnvironmentProxy()
    importlib.import_module = blocked("import_module")
    for name, action in (("open", lambda: builtins.open("blocked")), ("stat", lambda: os.stat("blocked")), ("getenv", lambda: os.getenv("blocked")), ("environ", lambda: os.environ["blocked"]), ("import_module", lambda: importlib.import_module("blocked"))):
        try:
            action()
        except AssertionError as error:
            assert str(error) == name
        else:
            raise AssertionError(name)
    calls.clear()
    try:
        builtins.__import__("fractions", fromlist=())
    except AssertionError as error:
        assert str(error).startswith("import outside explicit U1 allowlist:")
    else:
        raise AssertionError("ordinary prohibited import was not rejected")
    try:
        builtins.__import__("topsailai.hooks.runtime", fromlist=())
    except AssertionError:
        pass
    else:
        raise AssertionError("Runtime import was not rejected")
    calls.clear()
    seen_imports.clear()
    contracts_type = contracts.HookResourceSelection
    for label, source in (("file", {"file": "module.py"}), ("files", {"files": ["a.py", "b.py"]}), ("folder", {"folder": "modules"})):
        decoded = mapping.decode_resource_selection(source)
        assert decoded.files == (("module.py",) if label == "file" else ("a.py", "b.py") if label == "files" else ())
        assert decoded.folder == ("modules" if label == "folder" else None)
        contracts_type(files=("module.py",)) if label == "file" else contracts_type(files=("a.py", "b.py")) if label == "files" else contracts_type(folder="modules")
    for kind in ("modules", "scripts"):
        for _, source in (("file", {"file": "module.py"}), ("files", {"files": ["a.py", "b.py"]}), ("folder", {"folder": "modules"})):
            decoded = mapping.decode_point_resource_selection({kind: source})
            assert getattr(decoded, kind) is not None
            assert getattr(decoded, "scripts" if kind == "modules" else "modules") is None
    assert calls == []
    assert all(name in required_stdlib or name in allowed_project for name, _, _ in seen_imports), seen_imports
    print(json.dumps({"calls": calls, "target_modules_loaded": True}))
finally:
    builtins.__import__ = original_import
'''
    original_runner, invocations = _run_bounded_child, []
    def recording_runner(child_script, cwd, *, args=()):
        invocations.append((child_script, cwd, args)); return original_runner(child_script, cwd, args=args)
    monkeypatch.setattr(sys.modules[__name__], "_run_bounded_child", recording_runner)
    returncode, stdout, stderr, overflow = _run_bounded_child(
        script, source_root, args=(source_root,)
    )
    assert len(invocations) == 1 and invocations[0][1:] == (source_root, (source_root,))
    assert not overflow and not stderr and returncode == 0
    assert json.loads(stdout) == {"calls": [], "target_modules_loaded": True}
