"""Gherkin bindings and harness-cleanup regressions for Unified Hooks lifecycle."""

import threading

import pytest
from pytest_bdd import scenarios

from tests.bdd.steps.unified_hooks_lifecycle_steps import *  # noqa: F403
from tests.bdd.unified_hooks_lifecycle_harness import UnifiedHooksLifecycleScenario


scenarios("features/unified_hooks_lifecycle.feature")


def test_cleanup_steps_attempt_every_ordinary_failure() -> None:
    """Retain every ordinary failure while attempting every cleanup step."""
    calls: list[str] = []

    def fail(name: str) -> None:
        calls.append(name)
        raise RuntimeError(name)

    with pytest.raises(ExceptionGroup) as captured:
        UnifiedHooksLifecycleScenario._run_cleanup_steps(
            lambda: fail("join"),
            lambda: fail("runtime-close"),
            lambda: calls.append("worker-settlement"),
        )

    assert calls == ["join", "runtime-close", "worker-settlement"]
    assert tuple(str(error) for error in captured.value.exceptions) == (
        "join",
        "runtime-close",
    )


def test_cleanup_steps_preserve_host_interrupt() -> None:
    """Propagate host interruption instead of aggregating it as cleanup failure."""
    with pytest.raises(KeyboardInterrupt):
        UnifiedHooksLifecycleScenario._run_cleanup_steps(
            lambda: (_ for _ in ()).throw(KeyboardInterrupt())
        )


def test_close_attempts_local_cleanup_after_settlement_failure() -> None:
    """Do not let failed execution settlement skip independent local cleanup."""
    scenario = UnifiedHooksLifecycleScenario.__new__(UnifiedHooksLifecycleScenario)
    scenario.closed = False
    calls: list[str] = []

    def fail_settlement() -> None:
        calls.append("settlement")
        raise AssertionError("dispatch thread did not settle")

    scenario._settle_owned_execution = fail_settlement
    scenario._close_local_resources = lambda: calls.append("local-cleanup")

    with pytest.raises(ExceptionGroup) as captured:
        scenario.close()

    assert calls == ["settlement", "local-cleanup"]
    assert str(captured.value.exceptions[0]) == "dispatch thread did not settle"


def test_final_rejoin_precedes_storage_teardown(monkeypatch) -> None:
    """Settle a real controlled thread before storage teardown may proceed."""
    import tests.bdd.unified_hooks_lifecycle_harness as lifecycle_harness

    monkeypatch.setattr(lifecycle_harness, "_SETTLEMENT_LIMIT_SECONDS", 0.05)
    release = threading.Event()
    lifecycle: list[str] = []

    def controlled_dispatch() -> None:
        release.wait()
        lifecycle.append("thread-exited")

    dispatch_thread = threading.Thread(target=controlled_dispatch)
    dispatch_thread.start()
    try:
        scenario = UnifiedHooksLifecycleScenario.__new__(UnifiedHooksLifecycleScenario)
        scenario.closed = False
        scenario._dispatch_thread = dispatch_thread
        scenario.observed_workers = ()
        scenario._close_runtime = lambda: None
        scenario._release_worker = lambda: None
        scenario._capture_workers = lambda: None
        scenario._wait_for_workers_gone = lambda: None
        scenario._terminate_observed_workers = release.set

        with pytest.raises(ExceptionGroup):
            scenario._settle_owned_execution()

        lifecycle.append("storage-teardown")
        assert scenario.closed
        assert not dispatch_thread.is_alive()
        assert lifecycle == ["thread-exited", "storage-teardown"]
    finally:
        release.set()
        dispatch_thread.join(1.0)
        assert not dispatch_thread.is_alive()


def test_local_cleanup_attempts_every_resource() -> None:
    """Attempt both descriptors and the import path after an ordinary close failure."""
    scenario = UnifiedHooksLifecycleScenario.__new__(UnifiedHooksLifecycleScenario)
    calls: list[str] = []

    def close_descriptor(name: str) -> None:
        calls.append(name)
        if name == "_ready_fd":
            raise OSError("ready close")

    scenario._close_descriptor = close_descriptor
    scenario._remove_runtime_path = lambda: calls.append("runtime-path")

    with pytest.raises(ExceptionGroup) as captured:
        scenario._close_local_resources()

    assert calls == ["_ready_fd", "_release_fd", "runtime-path"]
    assert str(captured.value.exceptions[0]) == "ready close"


def test_initialization_retains_original_and_cleanup_failures(monkeypatch, tmp_path) -> None:
    """Report both construction and cleanup failures without losing either cause."""
    monkeypatch.setattr(
        UnifiedHooksLifecycleScenario,
        "_initialize_runtime",
        lambda self: (_ for _ in ()).throw(RuntimeError("initialize")),
    )
    monkeypatch.setattr(
        UnifiedHooksLifecycleScenario,
        "close",
        lambda self: (_ for _ in ()).throw(ValueError("cleanup")),
    )

    with pytest.raises(ExceptionGroup) as captured:
        UnifiedHooksLifecycleScenario(tmp_path, "timeout")

    assert tuple(str(error) for error in captured.value.exceptions) == (
        "initialize",
        "cleanup",
    )


def test_cleanup_preserves_errors_before_host_interrupt() -> None:
    """Keep prior ordinary failures attached to the original host interruption."""
    calls: list[str] = []
    interruption = KeyboardInterrupt("stop")

    def ordinary_failure() -> None:
        calls.append("ordinary")
        raise RuntimeError("ordinary cleanup")

    def interrupt() -> None:
        calls.append("interrupt")
        raise interruption

    with pytest.raises(KeyboardInterrupt) as captured:
        UnifiedHooksLifecycleScenario._run_cleanup_steps(
            ordinary_failure,
            interrupt,
            lambda: calls.append("after"),
        )

    assert captured.value is interruption
    assert calls == ["ordinary", "interrupt", "after"]
    assert any("ordinary cleanup" in note for note in captured.value.__notes__)


def test_settlement_interrupt_still_attempts_local_cleanup() -> None:
    """Propagate settlement interruption only after local cleanup runs."""
    scenario = UnifiedHooksLifecycleScenario.__new__(UnifiedHooksLifecycleScenario)
    scenario.closed = False
    calls: list[str] = []
    interruption = KeyboardInterrupt("settlement")

    def interrupt_settlement() -> None:
        calls.append("settlement")
        raise interruption

    scenario._settle_owned_execution = interrupt_settlement
    scenario._close_local_resources = lambda: calls.append("local-cleanup")

    with pytest.raises(KeyboardInterrupt) as captured:
        scenario.close()

    assert captured.value is interruption
    assert calls == ["settlement", "local-cleanup"]


def test_descriptor_interrupt_still_cleans_remaining_local_resources() -> None:
    """Propagate descriptor interruption after other local cleanup is attempted."""
    scenario = UnifiedHooksLifecycleScenario.__new__(UnifiedHooksLifecycleScenario)
    calls: list[str] = []
    interruption = SystemExit("descriptor")

    def close_descriptor(name: str) -> None:
        calls.append(name)
        if name == "_ready_fd":
            raise interruption

    scenario._close_descriptor = close_descriptor
    scenario._remove_runtime_path = lambda: calls.append("runtime-path")

    with pytest.raises(SystemExit) as captured:
        scenario._close_local_resources()

    assert captured.value is interruption
    assert calls == ["_ready_fd", "_release_fd", "runtime-path"]


def test_pidfd_identity_mismatch_fails_closed(monkeypatch) -> None:
    """Close the stable handle without signaling when worker identity changed."""
    import os
    import tests.bdd.unified_hooks_lifecycle_harness as lifecycle_harness

    read_fd, write_fd = os.pipe()

    class MismatchedStat:
        """Return a valid stat shape for a different process generation."""

        def read_text(self, *, encoding: str) -> str:
            assert encoding == "utf-8"
            return " ".join(["field"] * 21 + ["new-start"])

    monkeypatch.setattr(lifecycle_harness.os, "pidfd_open", lambda pid, flags: read_fd)
    monkeypatch.setattr(lifecycle_harness, "Path", lambda path: MismatchedStat())
    try:
        with pytest.raises(AssertionError, match="identity changed"):
            UnifiedHooksLifecycleScenario._open_verified_worker_pidfd(123, "old-start")
        with pytest.raises(OSError):
            os.fstat(read_fd)
    finally:
        os.close(write_fd)


def test_pidfd_signal_tolerates_exit_after_verification(monkeypatch) -> None:
    """Treat process exit after identity verification as a safe signaling race."""
    import os
    import signal
    import tests.bdd.unified_hooks_lifecycle_harness as lifecycle_harness

    read_fd, write_fd = os.pipe()
    scenario = UnifiedHooksLifecycleScenario.__new__(UnifiedHooksLifecycleScenario)
    scenario.observed_workers = ((123, "start"),)
    monkeypatch.setattr(scenario, "_open_verified_worker_pidfd", lambda pid, start: read_fd)
    monkeypatch.setattr(
        lifecycle_harness.signal,
        "pidfd_send_signal",
        lambda descriptor, number, siginfo, flags: (_ for _ in ()).throw(
            ProcessLookupError()
        ),
    )
    try:
        scenario._signal_observed_workers(signal.SIGTERM)
        with pytest.raises(OSError):
            os.fstat(read_fd)
    finally:
        os.close(write_fd)


def test_worker_termination_escalates_from_term_to_kill(monkeypatch) -> None:
    """Bound settlement before escalating one verified worker to SIGKILL."""
    import signal

    scenario = UnifiedHooksLifecycleScenario.__new__(UnifiedHooksLifecycleScenario)
    scenario.observed_workers = ((123, "start"),)
    signals: list[int] = []
    waits = 0

    monkeypatch.setattr(scenario, "_identity_is_gone", lambda pid, start: False)
    monkeypatch.setattr(
        scenario,
        "_signal_observed_workers",
        lambda signal_number: signals.append(signal_number),
    )

    def wait_for_exit() -> None:
        nonlocal waits
        waits += 1
        if waits == 1:
            raise AssertionError("still alive")

    monkeypatch.setattr(scenario, "_wait_for_workers_gone", wait_for_exit)

    scenario._terminate_observed_workers()

    assert signals == [signal.SIGTERM, signal.SIGKILL]
    assert waits == 2


def test_initialization_interrupt_survives_cleanup_interrupt(monkeypatch, tmp_path) -> None:
    """Keep the original initialization interruption as the propagated object."""
    initialization_error = KeyboardInterrupt("initialize")
    cleanup_error = SystemExit("cleanup")
    monkeypatch.setattr(
        UnifiedHooksLifecycleScenario,
        "_initialize_runtime",
        lambda self: (_ for _ in ()).throw(initialization_error),
    )
    monkeypatch.setattr(
        UnifiedHooksLifecycleScenario,
        "close",
        lambda self: (_ for _ in ()).throw(cleanup_error),
    )

    with pytest.raises(KeyboardInterrupt) as captured:
        UnifiedHooksLifecycleScenario(tmp_path, "timeout")

    assert captured.value is initialization_error
    assert any("SystemExit('cleanup')" in note for note in captured.value.__notes__)


def test_cleanup_interrupt_survives_ordinary_initialization_error(
    monkeypatch, tmp_path
) -> None:
    """Propagate cleanup interruption while retaining ordinary initialization failure."""
    initialization_error = RuntimeError("initialize")
    cleanup_error = SystemExit("cleanup")
    monkeypatch.setattr(
        UnifiedHooksLifecycleScenario,
        "_initialize_runtime",
        lambda self: (_ for _ in ()).throw(initialization_error),
    )
    monkeypatch.setattr(
        UnifiedHooksLifecycleScenario,
        "close",
        lambda self: (_ for _ in ()).throw(cleanup_error),
    )

    with pytest.raises(SystemExit) as captured:
        UnifiedHooksLifecycleScenario(tmp_path, "timeout")

    assert captured.value is cleanup_error
    assert any("RuntimeError('initialize')" in note for note in captured.value.__notes__)
