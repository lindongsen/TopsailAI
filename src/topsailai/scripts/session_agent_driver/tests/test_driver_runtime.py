"""Lifecycle and log retention tests for driver runtime records.

Author: DawsonLin
"""
import json
import logging
import os
import signal
from unittest import mock

import pytest

import session_agent_driver as sad
from driver_runtime import DriverRuntime


def _read(directory):
    """Read a published target record."""
    return json.loads((directory / "target.meta").read_text())


def test_runtime_lifecycle_and_restart(tmp_path):
    """Publish running state, terminal state and a fresh restart identity."""
    logger = logging.getLogger("driver-runtime-test")
    level = logger.level
    handlers = list(logger.handlers)
    with DriverRuntime(tmp_path, "target", 5, logger) as runtime:
        first = _read(tmp_path)
        assert first["status"] == "running"
        assert first["pid"] == os.getpid()
        assert first["end_time"] is None
        runtime.update_target("input")
        logger.info("first run")
        runtime.set_stop_reason("exit_requested")
    last = _read(tmp_path)
    assert last["status"] == "stopped"
    assert last["target_status"] == "input"
    assert last["stop_reason"] == "exit_requested"
    assert last["exit_code"] == 0
    assert last["end_time"] >= last["start_time"]
    assert logger.handlers == handlers
    assert logger.level == level
    with DriverRuntime(tmp_path, "target", 5, logger):
        assert _read(tmp_path)["run_id"] != first["run_id"]
        logger.info("second run")
    text = (tmp_path / "target.log").read_text()
    assert "first run" in text and "second run" in text
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("error,code", [(RuntimeError("broken"), 1),
                                         (SystemExit(0), 0), (SystemExit(2), 2),
                                         (SystemExit("bad"), 1), (KeyboardInterrupt(), 130)])
def test_runtime_exception_records(tmp_path, error, code):
    """Finalize records and propagate the original termination object."""
    with pytest.raises(type(error)) as caught:
        with DriverRuntime(tmp_path, "target", 5, logging.getLogger("runtime-error")):
            raise error
    assert caught.value is error
    data = _read(tmp_path)
    assert data["exit_code"] == code
    assert data["status"] == ("stopped" if code == 0 else "failed")


@pytest.mark.parametrize("name", ["../escape", "/absolute", "", ".", "a/b", "a" * 201])
def test_invalid_session_filename(tmp_path, name):
    """Reject traversal and unsupported filenames before writing."""
    with pytest.raises(ValueError):
        DriverRuntime(tmp_path, name, 5, logging.getLogger("runtime-invalid"))
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("size,backups", [(0, 5), (10, 0)])
def test_invalid_rotation(tmp_path, size, backups):
    """Reject settings that would disable bounded log retention."""
    with pytest.raises(ValueError):
        DriverRuntime(tmp_path, "target", 5, logging.getLogger("runtime-invalid"), size, backups)


def test_rotation_is_bounded(tmp_path):
    """Rotate logs and leave unrelated files unchanged."""
    other = tmp_path / "other.log"
    other.write_text("keep")
    logger = logging.getLogger("runtime-rotation")
    with DriverRuntime(tmp_path, "target", 5, logger, 200, 2):
        for index in range(30):
            logger.info("entry %s %s", index, "x" * 70)
    assert len(list(tmp_path.glob("target.log*"))) == 3
    assert other.read_text() == "keep"


@pytest.mark.parametrize("mode,reason", [("idle", "target_exited"),
                                         ("request", "exit_requested"),
                                         ("signal", "signal:15")])
def test_main_records_stop_paths(tmp_path, mode, reason):
    """Exercise main's real lifecycle integration without model or target I/O."""
    def status(session_id):
        """Observe running metadata and trigger a controlled stop."""
        assert _read(tmp_path)["status"] == "running"
        if mode == "signal":
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        if mode == "request":
            sad.exit_process.exit_process()
            return "running"
        return "idle"

    old_int, old_term = signal.getsignal(signal.SIGINT), signal.getsignal(signal.SIGTERM)
    try:
        with mock.patch.object(sad, "check_session_status", side_effect=status), \
                mock.patch.object(sad.time, "sleep"):
            if mode == "signal":
                with pytest.raises(SystemExit):
                    sad.main(["-s", "target"], record_directory=tmp_path)
            else:
                assert sad.main(["-s", "target"], record_directory=tmp_path) == 0
    finally:
        signal.signal(signal.SIGINT, old_int)
        signal.signal(signal.SIGTERM, old_term)
    assert _read(tmp_path)["stop_reason"] == reason
    assert "driver stopped" in (tmp_path / "target.log").read_text()


def test_publish_failure_closes_handler(tmp_path):
    """Release the log handler even when initial metadata publication fails."""
    logger = logging.getLogger("runtime-publish-error")
    before = list(logger.handlers)
    runtime = DriverRuntime(tmp_path, "target", 5, logger)
    with mock.patch.object(runtime, "_publish", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            with runtime:
                pass
    assert logger.handlers == before
    assert runtime.handler is None


def test_atomic_publication_failure_removes_temporary(tmp_path):
    """Retain the previous snapshot and remove failed publication debris."""
    logger = logging.getLogger("runtime-atomic")
    with DriverRuntime(tmp_path, "target", 5, logger) as runtime:
        before = _read(tmp_path)
        with mock.patch("driver_runtime.os.replace", side_effect=OSError("replace failed")):
            with pytest.raises(OSError):
                runtime.update_target("input")
        assert _read(tmp_path) == before
        assert not list(tmp_path.glob("*.tmp"))


def test_system_exit_without_code(tmp_path):
    """Treat an implicit SystemExit as a successful stop."""
    with pytest.raises(SystemExit):
        with DriverRuntime(tmp_path, "target", 5, logging.getLogger("runtime-exit")):
            raise SystemExit()
    assert _read(tmp_path)["exit_code"] == 0
