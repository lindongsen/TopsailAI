"""Tests for the non-interactive ``workspace clean`` command.

Author: DawsonLin
"""

import json
import os
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from cli_topsailai.cleaning import EXPIRED_AGE_SECONDS, delete_collected_files
from cli_topsailai.process_liveness import ProcessState
from cli_topsailai.workspace_clean_cli import run_workspace_clean_cli

#: Age used by every fixture so a file is unambiguously expired.
_OLD_AGE = EXPIRED_AGE_SECONDS + 3600


def _make_task_dir(tmp_path: Path) -> Path:
    """Create the ``{home}/workspace/task`` layout the command expects."""
    task_dir = tmp_path / "workspace" / "task"
    task_dir.mkdir(parents=True)
    return task_dir


def _make_file(task_dir: Path, name: str, *, age: float = _OLD_AGE) -> Path:
    """Create one file with an explicit modification age in seconds."""
    path = task_dir / name
    path.write_text("log")
    mtime = time.time() - age
    os.utime(path, (mtime, mtime))
    return path


def _record(path: Path, session_id=None, pid=None, session_pid=None) -> dict:
    """Build a log-file record matching ``discover_log_files`` output.

    ``discover_log_files`` reports a task file's own child PID in ``pid`` and
    the owning session's PID in ``session_pid``, while a session log file
    carries the same value in both fields. The default mirrors that, so a test
    only passes ``session_pid`` when it needs the two to differ.
    """
    stat_info = os.stat(path)
    return {
        "filename": path.name,
        "path": str(path),
        "session_id": session_id,
        "pid": pid,
        "session_pid": pid if session_pid is None else session_pid,
        "size": stat_info.st_size,
        "mtime": stat_info.st_mtime,
        "ctime": stat_info.st_ctime,
    }


def _invoke(tmp_path, records, argv, *, discover=None):
    """Run the command with isolated discovery and a dead-owner liveness seam."""
    discover_mock = Mock(return_value=records) if discover is None else discover
    with patch(
        "cli_topsailai.cleaning.socket_heartbeat_alive", return_value=False
    ), patch(
        "cli_topsailai.cleaning.pid_state", return_value=ProcessState.DEAD
    ), patch(
        "cli_topsailai.cleaning.is_file_in_use", return_value=False
    ):
        code = run_workspace_clean_cli(
            argv,
            home_resolver=lambda: str(tmp_path),
            discover=discover_mock,
        )
    return code, discover_mock


def test_preview_lists_candidates_without_deleting(tmp_path, capsys):
    """The default mode reports candidates and leaves every file in place."""
    task_dir = _make_task_dir(tmp_path)
    old = _make_file(task_dir, "sessA.111.session.stdout")
    records = [_record(old, "sessA", 111)]

    code, _ = _invoke(tmp_path, records, [])

    assert code == 0
    assert old.exists()
    out = capsys.readouterr().out
    assert "sessA.111.session.stdout" in out
    assert "nothing was deleted" in out


def test_yes_deletes_candidates(tmp_path):
    """``--yes`` removes exactly the listed files."""
    task_dir = _make_task_dir(tmp_path)
    old = _make_file(task_dir, "sessA.111.session.stdout")
    records = [_record(old, "sessA", 111)]

    code, _ = _invoke(tmp_path, records, ["--yes"])

    assert code == 0
    assert not old.exists()


def test_json_preview_emits_one_parseable_document(tmp_path, capsys):
    """JSON mode keeps stdout to a single receipt and moves text to stderr."""
    task_dir = _make_task_dir(tmp_path)
    old = _make_file(task_dir, "sessA.111.session.stdout")
    records = [_record(old, "sessA", 111)]

    code, _ = _invoke(tmp_path, records, ["--json"])

    captured = capsys.readouterr()
    assert code == 0
    lines = [line for line in captured.out.splitlines() if line.strip()]
    assert len(lines) == 1
    receipt = json.loads(lines[0])
    assert receipt["action"] == "clean"
    assert receipt["delivery_state"] == "preview"
    assert receipt["response"]["candidate_count"] == 1
    assert receipt["response"]["deleted_count"] == 0
    assert receipt["response"]["candidates"][0]["filename"] == old.name
    assert receipt["response"]["candidates"][0]["age_hours"] > 0
    # Human diagnostics must not pollute the machine-readable channel.
    assert "Clean Expired Log Files" in captured.err


def test_session_selector_restricts_candidates(tmp_path, capsys):
    """``-s`` limits the inventory to the named sessions only."""
    task_dir = _make_task_dir(tmp_path)
    keep = _make_file(task_dir, "sessA.111.session.stdout")
    other = _make_file(task_dir, "sessB.222.session.stdout")
    records = [_record(keep, "sessA", 111), _record(other, "sessB", 222)]

    code, _ = _invoke(tmp_path, records, ["-s", "sessB", "--json"])

    receipt = json.loads(capsys.readouterr().out.strip())
    assert code == 0
    assert receipt["response"]["candidate_count"] == 1
    assert receipt["response"]["candidates"][0]["filename"] == other.name


def test_empty_session_selector_is_a_usage_error(tmp_path, capsys):
    """An empty selector must not silently mean "every session"."""
    task_dir = _make_task_dir(tmp_path)
    old = _make_file(task_dir, "sessA.111.session.stdout")
    records = [_record(old, "sessA", 111)]

    code, _ = _invoke(tmp_path, records, ["-s", "", "--json"])

    receipt = json.loads(capsys.readouterr().out.strip())
    assert code == 2
    assert receipt["error_code"] == "usage_error"
    assert old.exists()


def test_conflicting_repeated_selector_is_rejected(tmp_path, capsys):
    """Two different ``-s`` values are ambiguous, so the command refuses."""
    task_dir = _make_task_dir(tmp_path)
    old = _make_file(task_dir, "sessA.111.session.stdout")
    records = [_record(old, "sessA", 111)]

    code, _ = _invoke(tmp_path, records, ["-s", "sessA", "-s", "sessB"])

    assert code == 2
    assert old.exists()


def test_inspection_failure_returns_one(tmp_path, capsys):
    """An unreadable task directory is reported as an inspection failure."""
    _make_task_dir(tmp_path)
    discover = Mock(side_effect=OSError("permission denied"))

    code, _ = _invoke(tmp_path, [], ["--json"], discover=discover)

    receipt = json.loads(capsys.readouterr().out.strip())
    assert code == 1
    assert receipt["error_code"] == "inspection_failed"
    assert "permission denied" in receipt["message"]


def test_delete_failure_returns_one(tmp_path, capsys):
    """A failed removal is reported per file and changes the exit code."""
    task_dir = _make_task_dir(tmp_path)
    old = _make_file(task_dir, "sessA.111.session.stdout")
    records = [_record(old, "sessA", 111)]

    with patch(
        "cli_topsailai.cleaning.os.remove", side_effect=OSError("busy")
    ):
        code, _ = _invoke(tmp_path, records, ["--yes", "--json"])

    receipt = json.loads(capsys.readouterr().out.strip())
    assert code == 1
    assert receipt["delivery_state"] == "partial"
    assert receipt["error_code"] == "delete_failed"
    assert receipt["response"]["deleted_count"] == 0
    assert receipt["response"]["failed_count"] == 1
    assert receipt["response"]["failed"][0]["filename"] == old.name
    assert old.exists()


def test_live_session_is_protected(tmp_path, capsys):
    """A file whose owner answers the control channel is never a candidate."""
    task_dir = _make_task_dir(tmp_path)
    old = _make_file(task_dir, "sessA.111.session.stdout")
    records = [_record(old, "sessA", 111)]

    with patch(
        "cli_topsailai.cleaning.socket_heartbeat_alive", return_value=True
    ), patch(
        "cli_topsailai.cleaning.is_file_in_use", return_value=False
    ):
        code = run_workspace_clean_cli(
            ["--yes", "--json"],
            home_resolver=lambda: str(tmp_path),
            discover=Mock(return_value=records),
        )

    receipt = json.loads(capsys.readouterr().out.strip())
    assert code == 0
    assert receipt["delivery_state"] == "nothing_to_delete"
    assert old.exists()


def test_unverifiable_liveness_blocks_deletion(tmp_path, capsys):
    """An unanswerable liveness probe must fail closed, not authorize removal."""
    task_dir = _make_task_dir(tmp_path)
    old = _make_file(task_dir, "sessA.111.session.stdout")
    records = [_record(old, "sessA", 111)]

    with patch(
        "cli_topsailai.cleaning.socket_heartbeat_alive", return_value=None
    ), patch(
        "cli_topsailai.cleaning.pid_state", return_value=ProcessState.UNKNOWN
    ), patch(
        "cli_topsailai.cleaning.is_file_in_use", return_value=False
    ):
        code = run_workspace_clean_cli(
            ["--yes", "--json"],
            home_resolver=lambda: str(tmp_path),
            discover=Mock(return_value=records),
        )

    receipt = json.loads(capsys.readouterr().out.strip())
    assert code == 0
    assert receipt["delivery_state"] == "nothing_to_delete"
    assert old.exists()


def test_active_launch_log_is_protected(tmp_path, capsys):
    """A launch log still holding a lease is excluded from the inventory.

    Launch logs are discovered by the inventory itself, not by the session
    log-file scan, so the discovery seam returns nothing and the protection
    under test is the lease check inside ``collect_expired_files``.
    """
    task_dir = _make_task_dir(tmp_path)
    launch_log = _make_file(task_dir, "sessA.111.agent-launch.log")

    with patch(
        "cli_topsailai.cleaning._is_active_launch_log", return_value=True
    ), patch(
        "cli_topsailai.cleaning.socket_heartbeat_alive", return_value=False
    ), patch(
        "cli_topsailai.cleaning.pid_state", return_value=ProcessState.DEAD
    ), patch(
        "cli_topsailai.cleaning.is_file_in_use", return_value=False
    ):
        code = run_workspace_clean_cli(
            ["--yes", "--json"],
            home_resolver=lambda: str(tmp_path),
            discover=Mock(return_value=[]),
        )

    receipt = json.loads(capsys.readouterr().out.strip())
    assert code == 0
    assert receipt["delivery_state"] == "nothing_to_delete"
    assert receipt["response"]["candidate_count"] == 0
    assert launch_log.exists()


def test_expired_launch_log_is_a_candidate(tmp_path, capsys):
    """An expired launch log without a lease is listed like any other file."""
    task_dir = _make_task_dir(tmp_path)
    launch_log = _make_file(task_dir, "sessA.111.agent-launch.log")

    with patch(
        "cli_topsailai.cleaning._is_active_launch_log", return_value=False
    ), patch(
        "cli_topsailai.cleaning.socket_heartbeat_alive", return_value=False
    ), patch(
        "cli_topsailai.cleaning.pid_state", return_value=ProcessState.DEAD
    ), patch(
        "cli_topsailai.cleaning.is_file_in_use", return_value=False
    ):
        code = run_workspace_clean_cli(
            ["--json"],
            home_resolver=lambda: str(tmp_path),
            discover=Mock(return_value=[]),
        )

    receipt = json.loads(capsys.readouterr().out.strip())
    assert code == 0
    assert receipt["delivery_state"] == "preview"
    assert receipt["response"]["candidate_count"] == 1
    assert receipt["response"]["candidates"][0]["filename"] == launch_log.name
    assert launch_log.exists()


def test_changed_file_is_skipped_at_deletion_time(tmp_path):
    """A file modified after the inventory pass is not deleted."""
    task_dir = _make_task_dir(tmp_path)
    old = _make_file(task_dir, "sessA.111.session.stdout")
    stale_entry = {
        "filename": old.name,
        "path": str(old),
        "size": old.stat().st_size,
        "mtime": old.stat().st_mtime - 60,
    }

    with patch(
        "cli_topsailai.cleaning.socket_heartbeat_alive", return_value=False
    ), patch(
        "cli_topsailai.cleaning.pid_state", return_value=ProcessState.DEAD
    ), patch(
        "cli_topsailai.cleaning.is_file_in_use", return_value=False
    ), patch(
        "cli_topsailai.cleaning._is_active_launch_log", return_value=False
    ):
        deleted, failures = delete_collected_files(str(task_dir), [stale_entry])

    assert deleted == []
    assert failures == []
    assert old.exists()


def test_nothing_to_delete_reports_clean_state(tmp_path, capsys):
    """A fresh file is not expired, so the command reports nothing to do."""
    task_dir = _make_task_dir(tmp_path)
    fresh = _make_file(task_dir, "sessA.111.session.stdout", age=60)
    records = [_record(fresh, "sessA", 111)]

    code, _ = _invoke(tmp_path, records, ["--json"])

    receipt = json.loads(capsys.readouterr().out.strip())
    assert code == 0
    assert receipt["delivery_state"] == "nothing_to_delete"
    assert receipt["response"]["candidate_count"] == 0
    assert fresh.exists()


def test_help_exits_zero(tmp_path):
    """``--help`` documents the command without touching any file."""
    _make_task_dir(tmp_path)

    code, discover = _invoke(tmp_path, [], ["--help"])

    assert code == 0
    discover.assert_not_called()


def test_pid_selector_restricts_candidates(tmp_path, capsys):
    """``-p`` narrows the inventory to one session instance.

    Both files belong to the same session, so only the PID can tell them
    apart; the other instance must survive the deletion.
    """
    task_dir = _make_task_dir(tmp_path)
    keep = _make_file(task_dir, "sessA.111.session.stdout")
    other = _make_file(task_dir, "sessA.222.session.stdout")
    records = [_record(keep, "sessA", 111), _record(other, "sessA", 222)]

    code, _ = _invoke(tmp_path, records, ["-p", "222", "--yes", "--json"])

    receipt = json.loads(capsys.readouterr().out.strip())
    assert code == 0
    assert receipt["delivery_state"] == "deleted"
    assert receipt["response"]["deleted_count"] == 1
    assert not other.exists()
    assert keep.exists()


def test_pid_selector_matches_owner_pid_not_child_pid(tmp_path, capsys):
    """A task file is selected by its owning session PID, not its child PID.

    ``discover_log_files`` reports the task's own child PID in ``pid`` and the
    owning session's PID in ``session_pid``. Deletion groups files by the
    ``{session_id}.{pid}`` owner prefix, so the selector must follow the owner.
    """
    task_dir = _make_task_dir(tmp_path)
    task_file = _make_file(task_dir, "sessA.111.task.stdout")
    records = [_record(task_file, "sessA", 999, session_pid=111)]

    code, _ = _invoke(tmp_path, records, ["-p", "111", "--json"])

    receipt = json.loads(capsys.readouterr().out.strip())
    assert code == 0
    assert receipt["response"]["candidate_count"] == 1
    assert receipt["response"]["candidates"][0]["filename"] == task_file.name


def test_pid_selector_ignores_child_pid_value(tmp_path, capsys):
    """Selecting the child PID must not select the task file it produced."""
    task_dir = _make_task_dir(tmp_path)
    task_file = _make_file(task_dir, "sessA.111.task.stdout")
    records = [_record(task_file, "sessA", 999, session_pid=111)]

    code, _ = _invoke(tmp_path, records, ["-p", "999", "--json"])

    receipt = json.loads(capsys.readouterr().out.strip())
    assert code == 0
    assert receipt["response"]["candidate_count"] == 0
    assert task_file.exists()


def test_session_and_pid_selectors_intersect(tmp_path, capsys):
    """``-s`` and ``-p`` together keep only rows matching both filters."""
    task_dir = _make_task_dir(tmp_path)
    wanted = _make_file(task_dir, "sessA.111.session.stdout")
    wrong_session = _make_file(task_dir, "sessB.111.session.stdout")
    wrong_pid = _make_file(task_dir, "sessA.222.session.stdout")
    records = [
        _record(wanted, "sessA", 111),
        _record(wrong_session, "sessB", 111),
        _record(wrong_pid, "sessA", 222),
    ]

    code, _ = _invoke(
        tmp_path, records, ["-s", "sessA", "-p", "111", "--json"]
    )

    receipt = json.loads(capsys.readouterr().out.strip())
    assert code == 0
    assert receipt["response"]["candidate_count"] == 1
    assert receipt["response"]["candidates"][0]["filename"] == wanted.name
    assert receipt["response"]["selectors"] == {
        "session_ids": ["sessA"], "pids": [111],
    }


def test_pid_selector_accepts_a_list(tmp_path, capsys):
    """A comma-separated PID list selects every named instance."""
    task_dir = _make_task_dir(tmp_path)
    first = _make_file(task_dir, "sessA.111.session.stdout")
    second = _make_file(task_dir, "sessB.222.session.stdout")
    third = _make_file(task_dir, "sessC.333.session.stdout")
    records = [
        _record(first, "sessA", 111),
        _record(second, "sessB", 222),
        _record(third, "sessC", 333),
    ]

    code, _ = _invoke(tmp_path, records, ["-p", "111,222", "--json"])

    receipt = json.loads(capsys.readouterr().out.strip())
    assert code == 0
    assert receipt["response"]["candidate_count"] == 2
    assert receipt["response"]["selectors"]["pids"] == [111, 222]


def test_pid_selector_excludes_launch_logs(tmp_path, capsys):
    """An active PID filter must not fall back to unowned launch logs.

    Launch logs carry no owner PID, so including them would widen the
    inventory beyond the instance the operator named.
    """
    task_dir = _make_task_dir(tmp_path)
    launch_log = _make_file(task_dir, "sessA.111.agent-launch.log")
    session_log = _make_file(task_dir, "sessA.111.session.stdout")
    records = [_record(session_log, "sessA", 111)]

    with patch(
        "cli_topsailai.cleaning._is_active_launch_log", return_value=False
    ):
        code, _ = _invoke(tmp_path, records, ["-p", "111", "--json"])

    receipt = json.loads(capsys.readouterr().out.strip())
    assert code == 0
    assert receipt["response"]["candidate_count"] == 1
    assert receipt["response"]["candidates"][0]["filename"] == session_log.name
    assert launch_log.exists()


@pytest.mark.parametrize(
    "value",
    ["", "   ", "abc", "0", "-1", "111,abc", "111,0"],
)
def test_invalid_pid_selector_is_a_usage_error(tmp_path, capsys, value):
    """A PID selector that names no usable PID must never widen the inventory."""
    task_dir = _make_task_dir(tmp_path)
    old = _make_file(task_dir, "sessA.111.session.stdout")
    records = [_record(old, "sessA", 111)]

    code, _ = _invoke(tmp_path, records, ["-p", value, "--yes", "--json"])

    receipt = json.loads(capsys.readouterr().out.strip())
    assert code == 2
    assert receipt["error_code"] == "usage_error"
    assert old.exists()


def test_conflicting_repeated_pid_selector_is_rejected(tmp_path, capsys):
    """Two different ``-p`` values are ambiguous, so the command refuses."""
    task_dir = _make_task_dir(tmp_path)
    old = _make_file(task_dir, "sessA.111.session.stdout")
    records = [_record(old, "sessA", 111)]

    code, _ = _invoke(tmp_path, records, ["-p", "111", "-p", "222", "--yes"])

    assert code == 2
    assert old.exists()


def test_repeated_identical_pid_selector_is_accepted(tmp_path, capsys):
    """Repeating the same ``-p`` value is not a conflict."""
    task_dir = _make_task_dir(tmp_path)
    old = _make_file(task_dir, "sessA.111.session.stdout")
    records = [_record(old, "sessA", 111)]

    code, _ = _invoke(tmp_path, records, ["-p", "111", "-p", "111", "--json"])

    receipt = json.loads(capsys.readouterr().out.strip())
    assert code == 0
    assert receipt["response"]["candidate_count"] == 1
    assert receipt["response"]["selectors"]["pids"] == [111]


def test_pid_selector_reports_no_match(tmp_path, capsys):
    """A PID with no expired file reports an empty inventory, not a failure."""
    task_dir = _make_task_dir(tmp_path)
    old = _make_file(task_dir, "sessA.111.session.stdout")
    records = [_record(old, "sessA", 111)]

    code, _ = _invoke(tmp_path, records, ["-p", "222", "--json"])

    receipt = json.loads(capsys.readouterr().out.strip())
    assert code == 0
    assert receipt["delivery_state"] == "nothing_to_delete"
    assert receipt["response"]["candidate_count"] == 0
    assert receipt["response"]["selectors"]["pids"] == [222]
    assert old.exists()


def test_pid_selector_keeps_related_files_of_the_same_instance(tmp_path):
    """Deleting one file of an instance removes its related files only."""
    task_dir = _make_task_dir(tmp_path)
    stdout = _make_file(task_dir, "sessA.111.session.stdout")
    stderr = _make_file(task_dir, "sessA.111.session.stderr")
    other = _make_file(task_dir, "sessA.222.session.stdout")
    records = [
        _record(stdout, "sessA", 111),
        _record(stderr, "sessA", 111),
        _record(other, "sessA", 222),
    ]

    code, _ = _invoke(tmp_path, records, ["-p", "111", "--yes"])

    assert code == 0
    assert not stdout.exists()
    assert not stderr.exists()
    assert other.exists()
