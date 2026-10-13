"""Hosting command and ownership regressions. Author: DawsonLin."""

from contextlib import contextmanager
from types import SimpleNamespace
import threading
from unittest.mock import Mock

import pytest

from topsailai.workspace.plugin_instruction import hosting as module
from topsailai.workspace.plugin_instruction.hosting import HostingController, hosting


class Child:
    """Model a child with observable exit and cleanup."""

    def __init__(self):
        """Initialize a running fake process."""
        self.pid = 123
        self.returncode = None

    def poll(self):
        """Expose the current completion status."""
        return self.returncode


@pytest.fixture
def launched():
    """Supply a launcher with exact context-entry and exit evidence."""
    calls = []
    exited = threading.Event()
    child = Child()

    @contextmanager
    def launcher(path, args):
        """Keep the fake child running until context exit."""
        calls.append((path, args))
        try:
            yield child
        finally:
            child.returncode = 0
            exited.set()

    controller = HostingController(launcher=launcher)
    yield controller, child, calls, exited
    controller.close()


@pytest.mark.parametrize("session_id", [None, "", " \t\n", 123])
def test_missing_session_zero_resources(session_id, monkeypatch):
    """Reject missing session before thread or launcher construction."""
    launcher = Mock()
    thread = Mock(side_effect=AssertionError("thread must not be created"))
    monkeypatch.setattr(module.threading, "Thread", thread)
    controller = HostingController(launcher=launcher)
    with pytest.raises(ValueError, match="session_id is required"):
        hosting(session_id=session_id, controller=controller)
    launcher.assert_not_called()
    thread.assert_not_called()
    controller.close()


def test_exact_call_background_duplicate_and_close(launched):
    """Return while running and keep only one owned child."""
    controller, child, calls, exited = launched
    assert "started" in controller.start(" session-1 ")
    assert calls == [("session_agent_driver/session_agent_driver", ["--session", "session-1"])]
    assert not exited.is_set()
    assert "already running" in controller.start("session-1")
    assert len(calls) == 1
    controller.close()
    assert exited.is_set()
    assert not controller._launch.thread.is_alive()
    controller.close()
    with pytest.raises(RuntimeError, match="closed"):
        controller.start("session-1")


def test_natural_exit_and_restart(launched):
    """Replace only a settled natural-exit slot."""
    controller, child, calls, exited = launched
    controller.start("first")
    child.returncode = 0
    assert controller._launch.done.wait(2)
    child.returncode = None
    controller.start("second")
    assert len(calls) == 2


def test_nonzero_exit_is_logged(launched, caplog):
    """Publish nonzero post-spawn termination diagnostics."""
    controller, child, calls, exited = launched
    controller.start("session")
    child.returncode = 7
    assert controller._launch.done.wait(2)
    assert "code=7" in caplog.text


def test_spawn_failure():
    """Relay pre-publication errors and settle supervision."""
    launcher = Mock(side_effect=PermissionError("denied"))
    controller = HostingController(launcher=launcher)
    try:
        with pytest.raises(PermissionError, match="denied"):
            controller.start("session")
        assert not controller._launch.thread.is_alive()
    finally:
        controller.close()


def test_thread_start_failure(monkeypatch):
    """An unproven start failure retains cancellation and shutdown fallback."""
    controller = HostingController(launcher=Mock(), startup_timeout=0.001)
    monkeypatch.setattr(module.threading.Thread, "start", Mock(side_effect=RuntimeError("thread")))
    try:
        with pytest.raises(RuntimeError, match="thread") as caught:
            controller.start("session")
        assert "unresolved" in caught.value.__notes__[0]
        assert controller._launch.stop.is_set()
        with pytest.raises(RuntimeError, match="startup remains unresolved"):
            controller.close()
        assert controller._exit_registered
    finally:
        # The test double is known not to create a thread; settle that exact fixture.
        controller._launch.done.set()
        controller.close()


@pytest.mark.parametrize("interruption", [KeyboardInterrupt, SystemExit])
def test_native_thread_start_before_ident_interruption(monkeypatch, interruption):
    """Cancel an actual native worker before its ident publication, retaining custody."""
    release = threading.Event()
    entered = threading.Event()
    launcher = Mock(side_effect=AssertionError("cancelled worker must not launch"))
    controller = HostingController(launcher=launcher, startup_timeout=0.01)
    original_bootstrap = threading.Thread._bootstrap_inner
    original_wait = threading.Event.wait
    worker = None

    def bootstrap(thread):
        """Gate only the owned native thread before Python publishes ident."""
        if thread.name == "hosting-supervisor":
            entered.set()
            original_wait(release, 5)
        original_bootstrap(thread)

    def wait(event, timeout=None):
        """Interrupt start's publication wait after native creation is proven."""
        if (threading.current_thread() is threading.main_thread()
                and controller._launch is not None
                and event is controller._launch.thread._started):
            assert original_wait(entered, 2)
            raise interruption("before ident")
        return original_wait(event, timeout)

    monkeypatch.setattr(threading.Thread, "_bootstrap_inner", bootstrap)
    monkeypatch.setattr(threading.Event, "wait", wait)
    try:
        with pytest.raises(interruption, match="before ident"):
            controller.start("session")
        launch = controller._launch
        worker = launch.thread
        assert entered.is_set() and worker.ident is None
        assert launch.stop.is_set() and not launch.done.is_set()
        with pytest.raises(RuntimeError, match="startup remains unresolved"):
            controller.close()
        assert controller._launch is launch and controller._exit_registered
        launcher.assert_not_called()
        release.set()
        assert original_wait(launch.done, 2)
        controller.close()
        assert not worker.is_alive() and not controller._exit_registered
        launcher.assert_not_called()
    finally:
        release.set()
        if worker is not None:
            original_wait(controller._launch.done, 2)
            controller.close()


def test_cleanup_failure_retains_debt(caplog):
    """Do not report clean settlement after launcher exit fails."""
    error = RuntimeError("cleanup")

    @contextmanager
    def launcher(path, args):
        """Raise during launcher cleanup only."""
        yield Child()
        raise error

    controller = HostingController(launcher=launcher)
    controller.start("session")
    with pytest.raises(RuntimeError) as caught:
        controller.close()
    assert caught.value is error
    assert controller._launch.cleanup_failed
    assert "supervision failed" in caplog.text
    controller._close_at_exit()
    module.atexit.unregister(controller._close_at_exit)


def test_startup_timeout_stops_eventual_spawn():
    """Timeout still joins the owner after a delayed spawn."""
    exited = threading.Event()

    @contextmanager
    def launcher(path, args):
        """Delay publication beyond the configured startup budget."""
        threading.Event().wait(0.03)
        try:
            yield Child()
        finally:
            exited.set()

    controller = HostingController(launcher=launcher, startup_timeout=0.001)
    with pytest.raises(TimeoutError):
        controller.start("session")
    assert exited.is_set()
    controller.close()


def test_hook_registration_and_output_once(monkeypatch, tmp_path, capsys, launched):
    """Register exactly one top-level command and print its returned status once."""
    from topsailai.workspace import hook_instruction as hooks
    controller, child, calls, exited = launched
    monkeypatch.setattr(hooks, "FILE_INPUT_COMPLETIONS", str(tmp_path / "completions.json"))
    monkeypatch.setattr(hooks, "INSTRUCTIONS", {})
    monkeypatch.setattr(module, "HostingController", lambda: controller)
    hook = hooks.HookInstruction(session_getter=lambda: "runtime-session")
    assert len(hook.hook_map["/hosting"]) == 1
    assert "/hosting.hosting" not in hook.hook_map
    hook.call_hook("/hosting")
    assert capsys.readouterr().out.count("Hosting process started") == 1
    assert calls[0][1] == ["--session", "runtime-session"]
    assert not hasattr(hook, "close")


def test_runtime_empty_does_not_fallback(monkeypatch, tmp_path, capsys):
    """An empty authoritative runtime ID must not use a stale environment ID."""
    from topsailai.workspace import hook_instruction as hooks
    monkeypatch.setattr(hooks, "FILE_INPUT_COMPLETIONS", str(tmp_path / "completions.json"))
    monkeypatch.setattr(hooks, "INSTRUCTIONS", {})
    monkeypatch.setattr(hooks.env_tool, "get_session_id", lambda: "stale")
    controller = HostingController(launcher=Mock())
    monkeypatch.setattr(module, "HostingController", lambda: controller)
    hook = hooks.HookInstruction(session_getter=lambda: "")
    hook.call_hook("/hosting")
    assert "session_id is required" in capsys.readouterr().out
    assert controller._launch is None
    controller._launcher.assert_not_called()
    assert not hasattr(hook, "close")


def test_standalone_session_boundary(monkeypatch, tmp_path, launched):
    """Standalone instruction uses the entry-point environment accessor."""
    from topsailai.workspace import hook_instruction as hooks
    controller, child, calls, exited = launched
    monkeypatch.setattr(hooks, "FILE_INPUT_COMPLETIONS", str(tmp_path / "completions.json"))
    monkeypatch.setattr(hooks, "INSTRUCTIONS", {})
    monkeypatch.setattr(module, "HostingController", lambda: controller)
    monkeypatch.setattr(hooks.env_tool, "get_session_id", lambda: "standalone")
    hook = hooks.HookInstruction()
    hook.call_instruction("/hosting")
    assert calls[0][1] == ["--session", "standalone"]
    assert not hasattr(hook, "close")


@pytest.mark.parametrize("interruption", [KeyboardInterrupt, SystemExit])
def test_start_wait_interruption(launched, monkeypatch, interruption):
    """Caller cancellation stops and joins the published worker."""
    controller, child, calls, exited = launched
    original = module.threading.Event.wait

    def wait(event, timeout=None):
        """Interrupt only the caller's startup publication wait once."""
        if threading.current_thread() is threading.main_thread() and timeout == 10.0:
            raise interruption("cancel")
        return original(event, timeout)

    monkeypatch.setattr(module.threading.Event, "wait", wait)
    with pytest.raises(interruption):
        controller.start("session")
    assert exited.is_set()
    assert not controller._launch.thread.is_alive()


def test_concurrent_starts_single_child(launched):
    """Concurrent commands share the exact starting slot."""
    controller, child, calls, exited = launched
    results = []
    threads = [threading.Thread(target=lambda: results.append(controller.start("session")))
               for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(calls) == 1
    assert len(results) == 4


def test_join_interruption_is_deferred(launched, monkeypatch):
    """Preserve host interruption after completing independent child cleanup."""
    controller, child, calls, exited = launched
    controller.start("session")
    original = controller._launch.thread.join
    raised = False

    def join(timeout=None):
        """Inject a one-shot join interruption before allowing recovery."""
        nonlocal raised
        if not raised:
            raised = True
            raise KeyboardInterrupt("join")
        return original(timeout)

    monkeypatch.setattr(controller._launch.thread, "join", join)
    with pytest.raises(KeyboardInterrupt, match="join"):
        controller.close()
    assert exited.is_set()
    assert not controller._launch.thread.is_alive()


@pytest.mark.parametrize("business", [None, ValueError("business"), KeyboardInterrupt("business")])
def test_session_exit_does_not_close_instruction(monkeypatch, business):
    """Session exit preserves original cleanup without instruction lifecycle calls."""
    from topsailai.workspace.agent import agent_shell_base as shell
    close = Mock()
    chat = SimpleNamespace(
        ctx_runtime_data=SimpleNamespace(session_id="session"),
        hook_instruction=SimpleNamespace(close=close),
        ai_agent=SimpleNamespace(close=Mock()),
        _stop_control_server=Mock(),
        _run=Mock(side_effect=business, return_value="answer"))
    monkeypatch.setattr(shell, "update_session_meta_status", Mock())
    from topsailai.workspace import print_tool
    monkeypatch.setattr(print_tool, "EnvReaderInstance", SimpleNamespace(check_bool=lambda *args: False))
    run = shell.AgentChat.run
    expected = business
    if expected is None:
        assert run(chat) == "answer"
    else:
        with pytest.raises(type(expected)) as caught:
            run(chat)
        assert caught.value is expected
    close.assert_not_called()
    chat._stop_control_server.assert_called_once()
    chat.ai_agent.close.assert_called_once()


def test_factory_failure_does_not_close_instruction(monkeypatch):
    """Factory failures propagate without calling instruction cleanup."""
    from topsailai.workspace import agent_shell as shell
    data = SimpleNamespace(session_id="runtime", messages=[])
    data.init = Mock()
    hook = SimpleNamespace(close=Mock())
    constructor = Mock(return_value=hook)
    primary = RuntimeError("factory")
    monkeypatch.setattr(shell, "ContextRuntimeData", Mock(return_value=data))
    monkeypatch.setattr(shell, "ContextRuntimeAIAgent", Mock())
    monkeypatch.setattr(shell, "ContextRuntimeInstructions", Mock())
    monkeypatch.setattr(shell, "HookInstruction", constructor)
    monkeypatch.setattr(shell, "get_ai_agent", Mock(side_effect=primary))
    monkeypatch.setattr(shell.ctx_manager, "exists_session", lambda session: True)
    monkeypatch.setattr(shell.env_tool, "is_interactive_mode", lambda: True)
    with pytest.raises(RuntimeError) as caught:
        shell._get_agent_chat_impl(message="task", session_id="runtime", need_print_session=False)
    assert caught.value is primary
    assert constructor.call_args.kwargs["session_getter"]() == "runtime"
    hook.close.assert_not_called()


def test_thread_start_post_handoff_interruption(launched, monkeypatch):
    """A thread-start interruption after spawn must retain and settle ownership."""
    controller, child, calls, exited = launched
    original = module.threading.Thread.start

    def start(thread):
        """Start normally then interrupt the caller at the handoff boundary."""
        original(thread)
        raise KeyboardInterrupt("handoff")

    monkeypatch.setattr(module.threading.Thread, "start", start)
    with pytest.raises(KeyboardInterrupt, match="handoff"):
        controller.start("session")
    assert exited.is_set()
    assert not controller._launch.thread.is_alive()


def test_unresolved_cleanup_blocks_restart():
    """A settled worker with cleanup debt must never authorize a new child."""
    error = RuntimeError("cleanup debt")

    @contextmanager
    def launcher(path, args):
        """Fail after a naturally completed child."""
        child = Child()
        child.returncode = 0
        yield child
        raise error

    controller = HostingController(launcher=launcher)
    try:
        try:
            controller.start("session")
        except RuntimeError:
            pass
        assert controller._launch.done.wait(2)
        with pytest.raises(RuntimeError, match="unresolved"):
            controller.start("session")
    finally:
        with pytest.raises(RuntimeError):
            controller.close()
        module.atexit.unregister(controller._close_at_exit)


def test_thread_construction_failure_is_settled(monkeypatch):
    """A constructor failure proves start was never invoked and close can settle."""
    launcher = Mock()
    controller = HostingController(launcher=launcher)
    monkeypatch.setattr(module.threading, "Thread", Mock(side_effect=RuntimeError("construct")))
    with pytest.raises(RuntimeError, match="construct"):
        controller.start("session")
    assert controller._launch.thread is None
    assert controller._launch.done.is_set()
    controller.close()
    assert not controller._exit_registered
    launcher.assert_not_called()
