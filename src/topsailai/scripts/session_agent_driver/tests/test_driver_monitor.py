"""Regression tests for single-flight analysis cancellation.

Author: DawsonLin
"""

import threading
from unittest.mock import Mock

import pytest

import session_agent_driver as sad
from driver_monitor import InputMonitor


def test_changed_child_interrupts_once_with_sibling_still_input():
    """Session aggregate input must not keep an obsolete child analysis alive."""
    interrupt = threading.Event()
    send = Mock(side_effect=interrupt.set)
    monitor = InputMonitor(
        lambda: ([{"pid": 1, "ctime": 10, "status": "running"},
                  {"pid": 2, "ctime": 20, "status": "input"}], "input"),
        {"pid": 1, "created_at": 10}, send, interval=0.001,
    )
    monitor.start()
    try:
        assert interrupt.wait(2)
    finally:
        monitor.close()
    send.assert_called_once_with()
    assert not monitor.thread.is_alive()


@pytest.mark.parametrize("rows", [[], [{"pid": 1, "ctime": 11, "status": "input"}]])
def test_missing_or_replaced_owner_cancels(rows):
    """A vanished process or replaced record invalidates the original owner."""
    interrupted = threading.Event()
    monitor = InputMonitor(lambda: (rows, "input"),
                           {"pid": 1, "created_at": 10}, interrupted.set, interval=0.001)
    monitor.start()
    try:
        assert interrupted.wait(2)
    finally:
        monitor.close()


def test_unknown_observation_retries_without_false_interrupt(caplog):
    """A query exception is not interpreted as confirmed target exit."""
    observed = threading.Event()

    def snapshot():
        """Fail once and then report the original input owner."""
        if not observed.is_set():
            observed.set()
            raise OSError("query unavailable")
        return ([{"pid": 1, "ctime": 10, "status": "input"}], "input")

    send = Mock()
    monitor = InputMonitor(snapshot, {"pid": 1, "created_at": 10}, send, interval=0.001)
    monitor.start()
    try:
        assert observed.wait(2)
    finally:
        monitor.close()
    send.assert_not_called()
    assert "query unavailable" in caplog.text


def test_interrupt_failure_retries_then_stops(caplog):
    """Only a successful interrupt ends the watcher; transport failure retries."""
    sent = threading.Event()
    send = Mock(side_effect=[OSError("write failed"), None])

    def interrupt():
        """Signal only after the framework request succeeds."""
        send()
        sent.set()

    monitor = InputMonitor(lambda: ([], "idle"), {"pid": 1, "created_at": 10},
                           interrupt, interval=0.001)
    monitor.start()
    try:
        assert sent.wait(2)
    finally:
        monitor.close()
    assert send.call_count == 2
    assert "write failed" in caplog.text


def test_hard_interrupt_marker_is_exact_and_cleaned(tmp_path, monkeypatch):
    """Use the real framework handler, never a process signal or target flag."""
    from topsailai.workspace.folder_utils import get_interrupt_flag_path
    from pathlib import Path

    monkeypatch.setattr(sad, "_task_dir", lambda: tmp_path)
    sad._request_analysis_interrupt("unique_analysis")
    path = Path(get_interrupt_flag_path(str(tmp_path), "unique_analysis", sad.os.getpid()))
    assert path.read_text() == "1"
    assert list(tmp_path.iterdir()) == [path]
    sad._clear_analysis_interrupt("unique_analysis")
    assert not path.exists()
    sad._clear_analysis_interrupt("unique_analysis")


def test_no_second_factory_until_interrupted_run_and_cleanup_finish(monkeypatch):
    """Cancellation is not termination: retain admission until actual return."""
    interrupted = threading.Event()
    contender_done = threading.Event()
    contender = None
    constructions = []
    calls = []
    original_argv = sad.sys.argv

    monkeypatch.setattr(sad, "check_session_status", lambda _: "input")
    monkeypatch.setattr(sad, "get_session_info", lambda _: {
        "status": "input", "pid": 1, "created_at": 10})
    monkeypatch.setattr(sad, "render_analysis_prompt", lambda _: "prompt")
    monkeypatch.setattr(sad, "_session_snapshot", lambda _: ([], "idle"))
    monkeypatch.setattr(sad, "_request_analysis_interrupt", lambda _: interrupted.set())
    monkeypatch.setattr(sad, "_clear_analysis_interrupt", lambda _: None)
    monkeypatch.setattr(sad.signal, "signal", Mock())
    monkeypatch.setattr(sad.signal, "alarm", Mock())

    def run(**kwargs):
        """Attempt a second launch while the first run remains on its stack."""
        nonlocal contender
        calls.append("run")
        assert interrupted.wait(2)

        def compete():
            """Try starting a concurrent analysis during cooperative cancellation."""
            sad.run_analysis_agent("same_target")
            contender_done.set()

        contender = threading.Thread(target=compete)
        contender.start()
        assert contender_done.wait(2)
        assert len(constructions) == 1

    def factory(**kwargs):
        """Try a reentrant launch even while factory construction is active."""
        constructions.append(kwargs["session_id"])
        sad.run_analysis_agent("recursive")
        return Mock(run=run)

    def cleanup(_):
        """Admission stays held until cleanup has completed too."""
        sad.run_analysis_agent("during_cleanup")
        calls.append("cleanup")

    monkeypatch.setattr(sad, "get_agent_chat", factory)
    monkeypatch.setattr(sad, "cleanup_analysis_session", cleanup)
    try:
        sad.run_analysis_agent("target")
    finally:
        if contender is not None:
            contender.join(2)
    assert len(constructions) == 1
    assert calls == ["run", "cleanup"]
    assert sad.sys.argv is original_argv
    assert not sad._ANALYSIS_LOCK.locked()
    assert not any(t.name == "analysis-input-monitor" for t in threading.enumerate())


def test_admission_released_after_base_exception(monkeypatch):
    """Host interruption cannot leave single-flight admission permanently held."""
    def fail(_):
        """Simulate host cancellation before analysis setup completes."""
        raise KeyboardInterrupt()

    monkeypatch.setattr(sad, "_run_analysis_agent", fail)
    with pytest.raises(KeyboardInterrupt):
        sad.run_analysis_agent("target")
    assert not sad._ANALYSIS_LOCK.locked()


def test_invalidated_analysis_never_regains_input_authority():
    """An observed running-to-input cycle must not revive an old decision."""
    row = {"pid": 1, "ctime": 10, "status": "input"}
    monitor = InputMonitor(lambda: ([row], "input"),
                           {"pid": 1, "created_at": 10}, Mock())
    assert monitor.allows_send(1)
    assert not monitor.allows_send(2)
    row["status"] = "running"
    assert not monitor.allows_send(1)
    row["status"] = "input"
    assert not monitor.allows_send(1)


def test_input_guard_rejects_stale_send_before_transport(monkeypatch):
    """The plugin checks the analysis lease before either transport route."""
    from plugins.tools import inject_input
    send = Mock()
    monkeypatch.setattr(inject_input, "execute_runtime_request", send)
    inject_input.set_input_guard(lambda session, pid: False)
    try:
        with pytest.raises(sad.AgentEndProcess, match="input owner changed"):
            inject_input.inject_input("target", "answer", 1)
    finally:
        inject_input.set_input_guard(None)
    send.assert_not_called()


def test_successful_injection_revokes_authority_before_pipe_changes(monkeypatch):
    """A successful reply ends analysis even if the original pipe still looks open."""
    from plugins.tools import inject_input
    monitor = InputMonitor(lambda: ([{"pid": 1, "ctime": 10, "status": "input"}], "input"),
                           {"pid": 1, "created_at": 10}, Mock())
    transport = Mock(return_value=Mock(ok=True))
    monkeypatch.setattr(inject_input, "execute_runtime_request", transport)
    inject_input.set_input_guard(lambda session, pid: monitor.allows_send(pid),
                                 monitor.mark_delivered)
    try:
        assert "input injected" in inject_input.inject_input("target", "reply")
        with pytest.raises(sad.AgentEndProcess, match="input owner changed"):
            inject_input.inject_input("target", "duplicate")
    finally:
        inject_input.set_input_guard(None)
    transport.assert_called_once()


def test_framework_checkpoint_consumes_exact_analysis_interrupt(tmp_path, monkeypatch):
    """A real agent checkpoint observes the monitor's framework marker."""
    from topsailai.ai_base.agent_base import AgentRun
    from topsailai.ai_base.exception import HardInterruptError
    from topsailai.workspace.folder_utils import get_interrupt_flag_path
    from pathlib import Path

    monkeypatch.setattr(sad, "_task_dir", lambda: tmp_path)
    sad._request_analysis_interrupt("checkpoint_analysis")
    flag = Path(get_interrupt_flag_path(str(tmp_path), "checkpoint_analysis", sad.os.getpid()))
    agent = AgentRun.__new__(AgentRun)
    agent._get_interrupt_flag_path = lambda: str(flag)
    with pytest.raises(HardInterruptError):
        agent._check_hard_interrupt()
    assert not flag.exists()
