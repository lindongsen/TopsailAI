"""Launch-boundary tests for the framework-owned script result descriptor."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

from topsailai.hooks.process_backend import IsolatedProcessBackend
from topsailai.hooks.process_launch import (
    argument_environment_within_limit,
    build_script_environment,
)
from topsailai.hooks.process_state import LaunchRecord, WorkerResult
from topsailai.hooks.process_termination import terminate_unpublished_process
from topsailai.hooks.process_termination import terminate_record


def _launch_size(argv: tuple[str, ...], environment: dict[str, str]) -> int:
    """Return the frozen argv/environment accounting size."""
    return sum(len(item.encode("utf-8")) + 1 for item in argv) + sum(
        len(f"{name}={value}".encode("utf-8")) + 1
        for name, value in environment.items()
    )


def test_final_environment_budget_includes_real_result_descriptor() -> None:
    """The inserted descriptor participates in inclusive cap and cap-plus-one checks."""
    argv = ("/trusted/script", "literal;argument")
    base = {"LANG": "C"}
    expected = {**base, "TOPSAILAI_HOOK_RESULT_FD": "37"}
    exact = _launch_size(argv, expected)

    assert build_script_environment(argv, base, 37, exact) == expected
    assert build_script_environment(argv, base, 37, exact - 1) is None
    assert base == {"LANG": "C"}
    assert argument_environment_within_limit(argv, expected, exact)
    assert not argument_environment_within_limit(argv, expected, exact - 1)


def test_launch_is_shell_free_and_passes_only_owned_result_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Popen receives literal argv, close_fds, and one framework-owned descriptor."""
    backend = IsolatedProcessBackend(temp_root=str(tmp_path))
    record = LaunchRecord("launch-capture", cleanup_deadline=time.monotonic() + 1)
    captured: dict[str, object] = {}

    def reject_launch(argv, **kwargs):
        captured["argv"] = argv
        captured.update(kwargs)
        raise OSError("fixture launch rejection")

    monkeypatch.setattr("topsailai.hooks.process_backend.subprocess.Popen", reject_launch)
    result = backend.launch_script(
        argv=("/trusted/script", "$(literal)", "semi;colon"),
        cwd=str(tmp_path),
        environment={"LANG": "C"},
        argument_environment_limit_bytes=4096,
        deadline=time.monotonic() + 1,
        record=record,
    )

    assert isinstance(result, WorkerResult)
    assert (result.status, result.error_category) == ("worker_lost", "startup_failure")
    assert captured["argv"] == ("/trusted/script", "$(literal)", "semi;colon")
    assert "shell" not in captured
    assert captured["close_fds"] is True
    assert captured["start_new_session"] is True
    assert len(captured["pass_fds"]) == 1
    result_fd = captured["pass_fds"][0]
    assert captured["env"]["TOPSAILAI_HOOK_RESULT_FD"] == str(result_fd)
    assert result.cleanup_confirmed
    assert backend.cleanup_debts() == ()


def test_launch_limit_rejection_closes_both_pipe_ends_before_process_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A final-environment overflow creates no process and leaks no pipe descriptor."""
    backend = IsolatedProcessBackend(temp_root=str(tmp_path))
    record = LaunchRecord("launch-limit", cleanup_deadline=time.monotonic() + 1)
    descriptors: list[int] = []
    real_pipe = os.pipe

    def tracked_pipe() -> tuple[int, int]:
        pair = real_pipe()
        descriptors.extend(pair)
        return pair

    def forbidden_popen(*args, **kwargs):
        raise AssertionError("process creation must not be attempted")

    monkeypatch.setattr("topsailai.hooks.process_backend.os.pipe", tracked_pipe)
    monkeypatch.setattr("topsailai.hooks.process_backend.subprocess.Popen", forbidden_popen)
    result = backend.launch_script(
        argv=("/trusted/script",),
        cwd=str(tmp_path),
        environment={"LANG": "C"},
        argument_environment_limit_bytes=1,
        deadline=time.monotonic() + 1,
        record=record,
    )

    assert isinstance(result, WorkerResult)
    assert result.cleanup_confirmed and result.cleanup_debt is None
    assert len(descriptors) == 2
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)


class _LiveProcess:
    """Provide a live process identity for stale-group authorization tests."""

    pid = 424242

    def poll(self) -> None:
        """Report that the recorded leader appears live."""
        return None



class _ExitedProcess:
    """Provide one already reaped leader without termination side effects."""

    pid = 424242

    def poll(self) -> int:
        """Report that the exact leader has exited."""
        return 0

class _GroupBackend(IsolatedProcessBackend):
    """Control process-group existence without touching host processes."""

    def _group_exists(self, pgid: int) -> bool:
        """Keep the historical process group uncertain."""
        return True


def test_stale_process_group_is_never_signaled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A live PID whose current group differs from the recorded PGID fails closed."""
    backend = _GroupBackend(temp_root=str(tmp_path))
    process = _LiveProcess()
    record = LaunchRecord(
        "stale-group",
        process=process,
        cleanup_deadline=time.monotonic() + 1,
        termination_grace=0.01,
        group_authorized=True,
    )
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr("topsailai.hooks.process_termination.os.getpgid", lambda pid: pid + 1)
    monkeypatch.setattr(
        "topsailai.hooks.process_termination.os.killpg",
        lambda pgid, sig: signals.append((pgid, sig)),
    )

    assert not terminate_record(backend, record, process)
    assert signals == []


def test_process_group_authority_failure_terminates_exact_unpublished_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failure to establish a fresh group reaps the exact child before returning."""
    backend = IsolatedProcessBackend(temp_root=str(tmp_path), cleanup_grace_ms=20)
    record = LaunchRecord(
        "group-authority",
        cleanup_deadline=time.monotonic() + 1,
        termination_grace=0.02,
    )
    created: list[subprocess.Popen[bytes]] = []
    real_popen = subprocess.Popen

    def tracked_popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        created.append(process)
        return process

    monkeypatch.setattr("topsailai.hooks.process_backend.subprocess.Popen", tracked_popen)
    monkeypatch.setattr(
        "topsailai.hooks.process_backend.os.getpgid",
        lambda pid: pid + 1,
    )
    result = backend.launch_script(
        argv=("/usr/bin/python3", "-c", "import time; time.sleep(10)"),
        cwd=str(tmp_path),
        environment={"LANG": "C"},
        argument_environment_limit_bytes=4096,
        deadline=time.monotonic() + 1,
        record=record,
    )

    assert isinstance(result, WorkerResult)
    assert (result.status, result.error_category) == ("worker_lost", "startup_failure")
    assert len(created) == 1 and created[0].poll() is not None
    assert result.cleanup_confirmed
    assert backend.cleanup_debts() == ()


def test_unpublished_exited_leader_with_live_group_retains_debt_without_signal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An untrusted surviving group remains debt after its exact leader exits."""
    backend = _GroupBackend(temp_root=str(tmp_path))
    process = _ExitedProcess()
    record = LaunchRecord(
        "unpublished-live-group",
        process=process,
        cleanup_deadline=time.monotonic() + 1,
        termination_grace=0.01,
    )
    for channel in record.cleanup.channels.values():
        channel.state = "closed"
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "topsailai.hooks.process_termination.os.killpg",
        lambda pgid, sig: signals.append((pgid, sig)),
    )

    record.cleanup.termination_started = True
    record.cleanup.termination_confirmed = terminate_unpublished_process(
        backend,
        process,
        record.cleanup_deadline,
        record.termination_grace,
    )
    result = backend._cleanup_launch_record(record, "group_authority_failure")

    assert not result.cleanup_confirmed
    assert result.cleanup_debt == record.debt_id
    assert tuple(debt.debt_id for debt in backend.cleanup_debts()) == (record.debt_id,)
    assert signals == []


def test_parent_result_write_close_failure_retains_retryable_descriptor_debt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed parent write-end close remains owned until exact retry succeeds."""

    class CloseFailureBackend(IsolatedProcessBackend):
        fail_write_close = True

        def _before_channel_close(self, record, name, descriptor):
            if name == "result_write" and self.fail_write_close:
                raise OSError("fixture write close failure")

    backend = CloseFailureBackend(temp_root=str(tmp_path), cleanup_grace_ms=20)
    record = LaunchRecord(
        "write-close-debt",
        cleanup_deadline=time.monotonic() + 1,
        termination_grace=0.02,
    )
    descriptors: list[int] = []
    real_pipe = os.pipe

    def tracked_pipe() -> tuple[int, int]:
        pair = real_pipe()
        descriptors.extend(pair)
        return pair

    monkeypatch.setattr("topsailai.hooks.process_backend.os.pipe", tracked_pipe)
    result = backend.launch_script(
        argv=("/usr/bin/python3", "-c", "import time; time.sleep(10)"),
        cwd=str(tmp_path),
        environment={"LANG": "C"},
        argument_environment_limit_bytes=4096,
        deadline=time.monotonic() + 1,
        record=record,
    )

    assert isinstance(result, WorkerResult)
    assert not result.cleanup_confirmed and result.cleanup_debt == record.debt_id
    assert os.fstat(descriptors[1])
    backend.fail_write_close = False
    assert backend.retry_cleanup(record.debt_id)
    with pytest.raises(OSError):
        os.fstat(descriptors[1])


def test_prelaunch_close_failure_retains_descriptor_only_debt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pipe ends that cannot close before Popen remain queryable without a process."""
    backend = IsolatedProcessBackend(temp_root=str(tmp_path))
    record = LaunchRecord("prelaunch-close-debt", cleanup_deadline=time.monotonic() + 1)
    descriptors: list[int] = []
    real_pipe = os.pipe
    real_close = os.close

    def tracked_pipe() -> tuple[int, int]:
        pair = real_pipe()
        descriptors.extend(pair)
        return pair

    def fail_owned_close(descriptor: int) -> None:
        if descriptor in descriptors:
            raise OSError("fixture prelaunch close failure")
        real_close(descriptor)

    monkeypatch.setattr("topsailai.hooks.process_backend.os.pipe", tracked_pipe)
    monkeypatch.setattr("topsailai.hooks.process_setup.os.close", fail_owned_close)
    result = backend.launch_script(
        argv=("/trusted/script",),
        cwd=str(tmp_path),
        environment={"LANG": "C"},
        argument_environment_limit_bytes=1,
        deadline=time.monotonic() + 1,
        record=record,
    )

    assert isinstance(result, WorkerResult)
    assert not result.cleanup_confirmed and result.cleanup_debt == record.debt_id
    assert backend._debt_processes[record.debt_id].process is None
    for descriptor in descriptors:
        assert os.fstat(descriptor)
    monkeypatch.setattr("topsailai.hooks.process_setup.os.close", real_close)
    assert backend.retry_cleanup(record.debt_id)
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_setup_close_retry_does_not_close_reused_descriptor(tmp_path: Path) -> None:
    """A changed descriptor identity settles stale ownership without closing its reuse."""
    backend = IsolatedProcessBackend(temp_root=str(tmp_path))
    record = LaunchRecord("setup-reuse")
    result_read, result_write = os.pipe()
    replacement_read, replacement_write = os.pipe()
    try:
        backend._adopt_setup_pipe(record, result_read, result_write)
        os.close(result_write)
        os.dup2(replacement_read, result_write)

        backend._close_setup_channel(record, "result_write")

        assert record.cleanup.setup_channels["result_write"].state == "closed"
        assert os.fstat(result_write)
    finally:
        for descriptor in (result_read, result_write, replacement_read, replacement_write):
            try:
                os.close(descriptor)
            except OSError:
                pass


def test_deadline_termination_reaps_sigkill_leader_on_first_cleanup(tmp_path: Path) -> None:
    """A TERM-resistant owned leader is reaped after KILL without false debt."""
    backend = IsolatedProcessBackend(temp_root=str(tmp_path), cleanup_grace_ms=30)
    process = subprocess.Popen(
        (
            "/usr/bin/python3",
            "-c",
            "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "print('ready', flush=True); time.sleep(10)",
        ),
        stdout=subprocess.PIPE,
        start_new_session=True,
    )
    assert process.stdout is not None and process.stdout.readline() == b"ready\n"
    record = LaunchRecord(
        "sigkill-reap",
        process=process,
        cleanup_deadline=time.monotonic() + 1,
        termination_grace=0.03,
        group_authorized=True,
    )
    try:
        assert terminate_record(backend, record, process)
        assert process.poll() is not None
        assert not backend._group_exists(process.pid)
        assert backend.cleanup_debts() == ()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=1)
        process.stdout.close()


@pytest.mark.parametrize("failed_index", (0, 1))
def test_launch_identity_failure_retains_setup_descriptor_until_absence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed_index: int
) -> None:
    """Identity-unknown setup ownership settles only after descriptor absence."""

    class IdentityFailureBackend(IsolatedProcessBackend):
        failed_descriptor: int | None = None

        def _descriptor_identity(self, descriptor):
            if descriptor == self.failed_descriptor:
                return "uncertain", None
            return super()._descriptor_identity(descriptor)

    backend = IdentityFailureBackend(temp_root=str(tmp_path))
    record = LaunchRecord(
        f"identity-failure-{failed_index}",
        cleanup_deadline=time.monotonic() + 1,
    )
    descriptors: list[int] = []
    real_pipe = os.pipe

    def tracked_pipe() -> tuple[int, int]:
        pair = real_pipe()
        descriptors.extend(pair)
        backend.failed_descriptor = pair[failed_index]
        return pair

    def forbidden_popen(*args, **kwargs):
        raise AssertionError("process creation must not be attempted")

    monkeypatch.setattr("topsailai.hooks.process_backend.os.pipe", tracked_pipe)
    monkeypatch.setattr(
        "topsailai.hooks.process_backend.subprocess.Popen", forbidden_popen
    )
    result = backend.launch_script(
        argv=("/trusted/script",),
        cwd=str(tmp_path),
        environment={"LANG": "C"},
        argument_environment_limit_bytes=4096,
        deadline=time.monotonic() + 1,
        record=record,
    )

    assert isinstance(result, WorkerResult)
    assert not result.cleanup_confirmed
    assert result.cleanup_debt == record.debt_id
    failed_channel = tuple(record.cleanup.setup_channels.values())[failed_index]
    assert failed_channel.state == "uncertain"
    assert failed_channel.identity is None and failed_channel.identity_pending
    backend.failed_descriptor = None
    assert not backend.retry_cleanup(record.debt_id)
    assert os.fstat(descriptors[failed_index])

    os.close(descriptors[failed_index])
    assert backend.retry_cleanup(record.debt_id)
    assert backend.cleanup_debts() == ()


@pytest.mark.parametrize("failed_index", (0, 1))
def test_launch_identity_unknown_retry_does_not_close_reused_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed_index: int
) -> None:
    """A later identity cannot authorize closing a reused identity-unknown number."""

    class IdentityFailureBackend(IsolatedProcessBackend):
        failed_descriptor: int | None = None

        def _descriptor_identity(self, descriptor):
            if descriptor == self.failed_descriptor:
                return "uncertain", None
            return super()._descriptor_identity(descriptor)

    backend = IdentityFailureBackend(temp_root=str(tmp_path))
    record = LaunchRecord(
        f"identity-reuse-{failed_index}",
        cleanup_deadline=time.monotonic() + 1,
    )
    descriptors: list[int] = []
    real_pipe = os.pipe

    def tracked_pipe() -> tuple[int, int]:
        pair = real_pipe()
        descriptors.extend(pair)
        backend.failed_descriptor = pair[failed_index]
        return pair

    monkeypatch.setattr("topsailai.hooks.process_backend.os.pipe", tracked_pipe)
    monkeypatch.setattr(
        "topsailai.hooks.process_backend.subprocess.Popen",
        lambda *args, **kwargs: pytest.fail("process creation must not be attempted"),
    )
    result = backend.launch_script(
        argv=("/trusted/script",),
        cwd=str(tmp_path),
        environment={"LANG": "C"},
        argument_environment_limit_bytes=4096,
        deadline=time.monotonic() + 1,
        record=record,
    )
    assert isinstance(result, WorkerResult) and result.cleanup_debt == record.debt_id

    replacement_read, replacement_write = real_pipe()
    failed_descriptor = descriptors[failed_index]
    try:
        os.close(failed_descriptor)
        os.dup2(replacement_read, failed_descriptor)
        backend.failed_descriptor = None

        assert not backend.retry_cleanup(record.debt_id)
        assert os.fstat(failed_descriptor)
        channel = tuple(record.cleanup.setup_channels.values())[failed_index]
        assert channel.state == "uncertain"
        assert channel.identity is None and channel.identity_pending

        os.close(failed_descriptor)
        assert backend.retry_cleanup(record.debt_id)
    finally:
        for descriptor in (failed_descriptor, replacement_read, replacement_write):
            try:
                os.close(descriptor)
            except OSError:
                pass


def test_launch_failure_cleanup_survives_result_read_identity_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A secondary read-identity failure cannot bypass child and descriptor cleanup."""

    class CombinedFailureBackend(IsolatedProcessBackend):
        fail_write_close = True
        fail_read_identity = False
        read_identity_failures = 0
        result_read: int | None = None

        def _before_channel_close(self, record, name, descriptor):
            if name == "result_write" and self.fail_write_close:
                self.fail_read_identity = True
                raise OSError("fixture write close failure")

        def _descriptor_identity(self, descriptor):
            if self.fail_read_identity and descriptor == self.result_read:
                self.read_identity_failures += 1
                return "uncertain", None
            return super()._descriptor_identity(descriptor)

    backend = CombinedFailureBackend(temp_root=str(tmp_path), cleanup_grace_ms=20)
    record = LaunchRecord(
        "combined-setup-failure",
        cleanup_deadline=time.monotonic() + 1,
        termination_grace=0.02,
    )
    descriptors: list[int] = []
    created: list[subprocess.Popen[bytes]] = []
    real_pipe = os.pipe
    real_popen = subprocess.Popen

    def tracked_pipe() -> tuple[int, int]:
        pair = real_pipe()
        if not descriptors:
            descriptors.extend(pair)
            backend.result_read = pair[0]
        return pair

    def tracked_popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        created.append(process)
        return process

    monkeypatch.setattr("topsailai.hooks.process_backend.os.pipe", tracked_pipe)
    monkeypatch.setattr("topsailai.hooks.process_backend.subprocess.Popen", tracked_popen)
    result = backend.launch_script(
        argv=("/usr/bin/python3", "-c", "import time; time.sleep(10)"),
        cwd=str(tmp_path),
        environment={"LANG": "C"},
        argument_environment_limit_bytes=4096,
        deadline=time.monotonic() + 1,
        record=record,
    )

    assert isinstance(result, WorkerResult)
    assert created and created[0].poll() is not None
    assert not result.cleanup_confirmed
    assert result.cleanup_debt == record.debt_id
    assert record.debt_id in {debt.debt_id for debt in backend.cleanup_debts()}
    assert backend.read_identity_failures > 0
    backend.fail_write_close = False
    backend.fail_read_identity = False
    assert backend.retry_cleanup(record.debt_id)
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)
