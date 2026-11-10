"""Tests for the driver exit reaper.

Author: DawsonLin
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import driver_reaper as reaper  # noqa: E402


@pytest.fixture(autouse=True)
def clean_tracking(monkeypatch):
    """Reset module tracking so tests cannot leak state into each other."""
    monkeypatch.setattr(reaper, "_TRACKED", set())
    monkeypatch.setattr(reaper, "_REGISTERED", False)
    monkeypatch.setenv(reaper.REAPER_ENABLED_ENV, "1")


class TestTracking:
    def test_tracks_valid_session(self):
        reaper.track_session("sad-abc123")
        assert reaper.tracked_sessions() == ("sad-abc123",)

    def test_ignores_empty_and_non_string(self):
        reaper.track_session("")
        reaper.track_session(None)
        reaper.track_session(123)
        assert reaper.tracked_sessions() == ()

    def test_deduplicates(self):
        reaper.track_session("sad-abc123")
        reaper.track_session("sad-abc123")
        assert reaper.tracked_sessions() == ("sad-abc123",)

    def test_returns_sorted_tuple(self):
        reaper.track_session("sad-bbb")
        reaper.track_session("sad-aaa")
        assert reaper.tracked_sessions() == ("sad-aaa", "sad-bbb")

    def test_disabled_reaper_tracks_nothing(self, monkeypatch):
        monkeypatch.setenv(reaper.REAPER_ENABLED_ENV, "0")
        reaper.track_session("sad-abc123")
        assert reaper.tracked_sessions() == ()


class TestEnabledFlag:
    @pytest.mark.parametrize("value", ["0", "false", "no", "off", "FALSE", " Off "])
    def test_disabled_values(self, monkeypatch, value):
        monkeypatch.setenv(reaper.REAPER_ENABLED_ENV, value)
        assert reaper._is_enabled() is False

    @pytest.mark.parametrize("value", ["1", "true", "yes", "on", ""])
    def test_enabled_values(self, monkeypatch, value):
        monkeypatch.setenv(reaper.REAPER_ENABLED_ENV, value)
        assert reaper._is_enabled() is True

    def test_defaults_to_enabled(self, monkeypatch):
        monkeypatch.delenv(reaper.REAPER_ENABLED_ENV, raising=False)
        assert reaper._is_enabled() is True


class TestRegistration:
    def test_registers_once(self):
        with mock.patch.object(reaper.atexit, "register") as register:
            reaper.register_exit_reaper()
            reaper.register_exit_reaper()
        assert register.call_count == 1
        assert register.call_args[0][0] is reaper._spawn_reaper


class TestBuildCommand:
    def test_contains_parent_pid_home_and_sessions(self, tmp_path):
        command = reaper.build_reaper_command(4242, tmp_path, ["sad-a", "sad-b"])
        assert command[0] == sys.executable
        assert command[1] == str(Path(reaper.__file__).resolve())
        assert command[command.index("--parent-pid") + 1] == "4242"
        assert command[command.index("--home") + 1] == str(tmp_path)
        assert json.loads(command[command.index("--sessions") + 1]) == ["sad-a", "sad-b"]

    def test_child_environment_disables_nested_reaper(self, tmp_path):
        environment = reaper._child_environment(tmp_path)
        assert environment["TOPSAILAI_HOME"] == str(tmp_path)
        assert environment[reaper.REAPER_ENABLED_ENV] == "0"


class TestSpawn:
    def test_spawns_detached_child(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_HOME", str(tmp_path))
        reaper.track_session("sad-abc123")
        with mock.patch.object(reaper.subprocess, "Popen") as popen:
            popen.return_value = mock.Mock(pid=999)
            reaper._spawn_reaper()
        assert popen.call_count == 1
        kwargs = popen.call_args.kwargs
        assert kwargs["start_new_session"] is True
        assert kwargs["close_fds"] is True
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["stdout"] == subprocess.DEVNULL
        assert kwargs["stderr"] == subprocess.DEVNULL

    def test_skips_when_disabled(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_HOME", str(tmp_path))
        monkeypatch.setenv(reaper.REAPER_ENABLED_ENV, "0")
        reaper.track_session("sad-abc123")
        with mock.patch.object(reaper.subprocess, "Popen") as popen:
            reaper._spawn_reaper()
        assert popen.call_count == 0

    def test_skips_when_nothing_tracked(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_HOME", str(tmp_path))
        with mock.patch.object(reaper.subprocess, "Popen") as popen:
            reaper._spawn_reaper()
        assert popen.call_count == 0

    def test_skips_when_home_unset(self, monkeypatch):
        monkeypatch.delenv("TOPSAILAI_HOME", raising=False)
        reaper.track_session("sad-abc123")
        with mock.patch.object(reaper.subprocess, "Popen") as popen:
            reaper._spawn_reaper()
        assert popen.call_count == 0

    def test_spawn_failure_is_logged_not_raised(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TOPSAILAI_HOME", str(tmp_path))
        reaper.track_session("sad-abc123")
        with mock.patch.object(reaper.subprocess, "Popen",
                               side_effect=OSError("boom")):
            reaper._spawn_reaper()


class TestWaitForParentExit:
    def test_returns_true_when_parent_already_gone(self):
        assert reaper.wait_for_parent_exit(1, 1, 0.01, observer=lambda _: False)

    def test_returns_false_when_parent_stays_alive(self):
        assert reaper.wait_for_parent_exit(1, 0.05, 0.01, observer=lambda _: True) is False

    def test_returns_true_when_parent_disappears_during_wait(self):
        calls = []

        def observer(_):
            """Report alive for the first two probes, then gone."""
            calls.append(1)
            return len(calls) < 3

        assert reaper.wait_for_parent_exit(1, 5, 0.01, observer=observer) is True

    def test_pid_alive_returns_false_for_invalid_pid(self):
        assert reaper._pid_alive(0) is False
        assert reaper._pid_alive(-1) is False
        assert reaper._pid_alive(None) is False

    def test_pid_alive_returns_true_for_own_process(self):
        assert reaper._pid_alive(os.getpid()) is True


class TestFindOwnerRecords:
    def _write(self, directory, name):
        """Create one empty owner record file."""
        path = directory / name
        path.write_text("{}", encoding="utf-8")
        return path

    def test_finds_every_owner_suffix(self, tmp_path):
        names = [
            "sad-abc.123.session.meta",
            "sad-abc.123.session.stats.jsonl",
            "sad-abc.123.session.events",
            "sad-abc.123.session.stdout",
        ]
        for name in names:
            self._write(tmp_path, name)
        found = {path.name for path in reaper.find_owner_records(tmp_path, "sad-abc")}
        assert found == set(names)

    def test_ignores_other_sessions(self, tmp_path):
        self._write(tmp_path, "sad-abc.123.session.meta")
        self._write(tmp_path, "sad-xyz.123.session.meta")
        found = [path.name for path in reaper.find_owner_records(tmp_path, "sad-abc")]
        assert found == ["sad-abc.123.session.meta"]

    def test_ignores_non_owner_files(self, tmp_path):
        self._write(tmp_path, "sad-abc.123.session.unknown")
        self._write(tmp_path, "sad-abc.meta")
        assert reaper.find_owner_records(tmp_path, "sad-abc") == []

    def test_ignores_prefix_collision(self, tmp_path):
        self._write(tmp_path, "sad-abc-extra.123.session.meta")
        assert reaper.find_owner_records(tmp_path, "sad-abc") == []

    def test_missing_directory_returns_empty(self, tmp_path):
        assert reaper.find_owner_records(tmp_path / "absent", "sad-abc") == []


class TestReapSessions:
    def test_deletes_row_and_files_after_parent_exit(self, tmp_path):
        task_dir = tmp_path / "workspace" / "task"
        task_dir.mkdir(parents=True)
        record = task_dir / "sad-abc.123.session.meta"
        record.write_text("{}", encoding="utf-8")
        manager = mock.Mock()
        manager.exists_session.return_value = True
        manager.delete_session.return_value = True
        with mock.patch("topsailai.context.ctx_manager.get_session_manager",
                        return_value=manager), \
                mock.patch("topsailai.context.session_activity.SessionActivityProbe.can_clean",
                           return_value=True):
            reaped = reaper.reap_sessions(1, ["sad-abc"], tmp_path, 1, 0.01,
                                          observer=lambda _: False)
        assert reaped == ["sad-abc"]
        manager.delete_session.assert_called_once_with("sad-abc")
        assert not record.exists()

    def test_preserves_everything_when_parent_stays_alive(self, tmp_path):
        task_dir = tmp_path / "workspace" / "task"
        task_dir.mkdir(parents=True)
        record = task_dir / "sad-abc.123.session.meta"
        record.write_text("{}", encoding="utf-8")
        manager = mock.Mock()
        with mock.patch("topsailai.context.ctx_manager.get_session_manager",
                        return_value=manager):
            reaped = reaper.reap_sessions(1, ["sad-abc"], tmp_path, 0.05, 0.01,
                                          observer=lambda _: True)
        assert reaped == []
        manager.delete_session.assert_not_called()
        assert record.exists()

    def test_preserves_session_when_cleanup_not_authorized(self, tmp_path):
        task_dir = tmp_path / "workspace" / "task"
        task_dir.mkdir(parents=True)
        record = task_dir / "sad-abc.123.session.meta"
        record.write_text("{}", encoding="utf-8")
        manager = mock.Mock()
        with mock.patch("topsailai.context.ctx_manager.get_session_manager",
                        return_value=manager), \
                mock.patch("topsailai.context.session_activity.SessionActivityProbe.can_clean",
                           return_value=False):
            reaped = reaper.reap_sessions(1, ["sad-abc"], tmp_path, 1, 0.01,
                                          observer=lambda _: False)
        assert reaped == []
        manager.delete_session.assert_not_called()
        assert record.exists()

    def test_preserves_files_when_row_deletion_refused(self, tmp_path):
        task_dir = tmp_path / "workspace" / "task"
        task_dir.mkdir(parents=True)
        record = task_dir / "sad-abc.123.session.meta"
        record.write_text("{}", encoding="utf-8")
        manager = mock.Mock()
        manager.exists_session.return_value = True
        manager.delete_session.return_value = False
        with mock.patch("topsailai.context.ctx_manager.get_session_manager",
                        return_value=manager), \
                mock.patch("topsailai.context.session_activity.SessionActivityProbe.can_clean",
                           return_value=True):
            reaped = reaper.reap_sessions(1, ["sad-abc"], tmp_path, 1, 0.01,
                                          observer=lambda _: False)
        assert reaped == []
        assert record.exists()

    def test_deletes_files_when_row_already_absent(self, tmp_path):
        task_dir = tmp_path / "workspace" / "task"
        task_dir.mkdir(parents=True)
        record = task_dir / "sad-abc.123.session.meta"
        record.write_text("{}", encoding="utf-8")
        manager = mock.Mock()
        manager.exists_session.return_value = False
        with mock.patch("topsailai.context.ctx_manager.get_session_manager",
                        return_value=manager), \
                mock.patch("topsailai.context.session_activity.SessionActivityProbe.can_clean",
                           return_value=True):
            reaped = reaper.reap_sessions(1, ["sad-abc"], tmp_path, 1, 0.01,
                                          observer=lambda _: False)
        assert reaped == ["sad-abc"]
        manager.delete_session.assert_not_called()
        assert not record.exists()

    def test_preserves_files_when_manager_unavailable(self, tmp_path):
        task_dir = tmp_path / "workspace" / "task"
        task_dir.mkdir(parents=True)
        record = task_dir / "sad-abc.123.session.meta"
        record.write_text("{}", encoding="utf-8")
        with mock.patch("topsailai.context.ctx_manager.get_session_manager",
                        return_value=None), \
                mock.patch("topsailai.context.session_activity.SessionActivityProbe.can_clean",
                           return_value=True):
            reaped = reaper.reap_sessions(1, ["sad-abc"], tmp_path, 1, 0.01,
                                          observer=lambda _: False)
        assert reaped == []
        assert record.exists()


class TestRelativeHomeResolution:
    """A relative TOPSAILAI_HOME must be resolved once, before the child runs.

    Importing the framework re-reads TOPSAILAI_HOME, so a relative value would
    be resolved a second time against the child working directory and the
    reaper would look for the owner records in the wrong place.
    """

    def test_spawn_passes_absolute_home(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("TOPSAILAI_HOME", "relhome")
        reaper.track_session("sad-abc123")
        with mock.patch.object(reaper.subprocess, "Popen") as popen:
            popen.return_value = mock.Mock(pid=999)
            reaper._spawn_reaper()
        command = popen.call_args.args[0]
        passed_home = command[command.index("--home") + 1]
        assert Path(passed_home).is_absolute()
        assert Path(passed_home) == (tmp_path / "relhome").resolve()
        environment = popen.call_args.kwargs["env"]
        assert Path(environment["TOPSAILAI_HOME"]).is_absolute()

    def test_reap_resolves_relative_home_before_deleting(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        task_dir = tmp_path / "relhome" / "workspace" / "task"
        task_dir.mkdir(parents=True)
        record = task_dir / "sad-abc.123.session.meta"
        record.write_text("{}", encoding="utf-8")
        manager = mock.Mock()
        manager.exists_session.return_value = True
        manager.delete_session.return_value = True
        with mock.patch("topsailai.context.ctx_manager.get_session_manager",
                        return_value=manager), \
                mock.patch("topsailai.context.session_activity.SessionActivityProbe") as probe:
            probe.return_value.can_clean.return_value = True
            reaped = reaper.reap_sessions(1, ["sad-abc"], "relhome", 1, 0.01,
                                          observer=lambda _: False)
        assert reaped == ["sad-abc"]
        assert not record.exists()
        # The probe must receive an absolute directory, never the raw relative
        # value, otherwise a second resolution would point at the wrong tree.
        probed_dir = probe.call_args.args[0][0]
        assert Path(probed_dir).is_absolute()
        assert Path(probed_dir) == task_dir.resolve()


class TestParseSessionIds:
    def test_accepts_valid_array(self):
        assert reaper._parse_session_ids('["sad-a", "sad-b"]') == ["sad-a", "sad-b"]

    def test_rejects_malformed_json(self):
        assert reaper._parse_session_ids("not json") is None

    def test_rejects_non_array(self):
        assert reaper._parse_session_ids('{"a": 1}') is None

    def test_rejects_non_string_items(self):
        assert reaper._parse_session_ids('["sad-a", 5]') is None

    def test_rejects_empty_items(self):
        assert reaper._parse_session_ids('["sad-a", ""]') is None


class TestMain:
    def test_rejects_malformed_sessions(self, tmp_path):
        code = reaper.main(["--parent-pid", "1", "--home", str(tmp_path),
                            "--sessions", "bad"])
        assert code == 2

    def test_reaps_after_parent_exit(self, tmp_path):
        task_dir = tmp_path / "workspace" / "task"
        task_dir.mkdir(parents=True)
        record = task_dir / "sad-abc.123.session.meta"
        record.write_text("{}", encoding="utf-8")
        manager = mock.Mock()
        manager.exists_session.return_value = True
        manager.delete_session.return_value = True
        # Use a PID that has genuinely exited; PID 1 is alive and would make
        # the reaper wait for its full timeout.
        parent = subprocess.Popen([sys.executable, "-c", "pass"])
        parent.wait()
        with mock.patch("topsailai.context.ctx_manager.get_session_manager",
                        return_value=manager), \
                mock.patch("topsailai.context.session_activity.SessionActivityProbe.can_clean",
                           return_value=True):
            code = reaper.main(["--parent-pid", str(parent.pid),
                                "--home", str(tmp_path),
                                "--sessions", '["sad-abc"]'])
        assert code == 0
        assert not record.exists()


class TestEndToEnd:
    def test_reaper_deletes_record_after_real_parent_exit(self, tmp_path):
        """A real detached reaper must delete the record once the parent is gone."""
        task_dir = tmp_path / "workspace" / "task"
        task_dir.mkdir(parents=True)
        record = task_dir / "sad-e2e.999999.session.meta"
        record.write_text(json.dumps({"session_id": "sad-e2e", "pid": 999999}),
                          encoding="utf-8")
        environment = dict(os.environ)
        environment["TOPSAILAI_HOME"] = str(tmp_path)
        environment["TOPSAILAI_SESSION_DRIVER_REAPER_ENABLED"] = "0"
        environment["TOPSAILAI_SESSION_DRIVER_REAPER_TIMEOUT"] = "20"
        environment["TOPSAILAI_SESSION_DRIVER_REAPER_POLL_INTERVAL"] = "0.1"
        # The parent is a short-lived process that exits immediately, so the
        # reaper observes a genuinely stopped owner.
        parent = subprocess.Popen([sys.executable, "-c", "pass"], env=environment)
        parent.wait()
        command = reaper.build_reaper_command(parent.pid, tmp_path, ["sad-e2e"])
        reaper_process = subprocess.Popen(command, env=environment,
                                          stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline and record.exists():
                time.sleep(0.1)
        finally:
            if reaper_process.poll() is None:
                reaper_process.kill()
            reaper_process.wait()
        assert not record.exists()
