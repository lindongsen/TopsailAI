"""
Unit tests for workspace/project_history/history.py.

Author: AI
Created: 2026-07-03
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from topsailai.workspace.project_history import history


class TestRecordProjectHistory:
    """Test basic record creation and JSONL format."""

    def test_record_creates_jsonl_line(self, temp_history_path):
        with patch.dict(
            os.environ,
            {
                "TOPSAILAI_PROJECT_WORKSPACE": "/workspace/my-project",
                "TOPSAILAI_PWD": "/workspace/my-project",
            },
            clear=True,
        ):
            assert history.record_project_history("session-001") is True

        lines = Path(temp_history_path).read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1

        entry = json.loads(lines[0])
        assert entry["session_id"] == "session-001"
        assert entry["project_workspace"] == "/workspace/my-project"
        assert entry["pwd"] == "/workspace/my-project"
        assert "pid" in entry
        assert entry["pid"] == os.getpid()
        assert "ts" in entry
        assert entry["ts"]  # ISO-8601 local timestamp should be non-empty

    def test_record_uses_current_session_id_from_env(self, temp_history_path):
        with patch.dict(
            os.environ,
            {
                "TOPSAILAI_PROJECT_WORKSPACE": "/workspace/env-project",
                "TOPSAILAI_PWD": "/workspace/env-project",
                "SESSION_ID": "env-session",
            },
            clear=True,
        ):
            assert history.record_project_history() is True

        entry = json.loads(Path(temp_history_path).read_text(encoding="utf-8").strip())
        assert entry["session_id"] == "env-session"
        assert entry["pid"] == os.getpid()

    def test_record_appends_multiple_lines(self, temp_history_path):
        with patch.dict(
            os.environ,
            {
                "TOPSAILAI_PROJECT_WORKSPACE": "/workspace/project",
                "TOPSAILAI_PWD": "/workspace/project",
            },
            clear=True,
        ):
            history.record_project_history("session-1")
            history.record_project_history("session-2")

        lines = Path(temp_history_path).read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["session_id"] == "session-1"
        assert json.loads(lines[0])["pid"] == os.getpid()
        assert json.loads(lines[1])["session_id"] == "session-2"
        assert json.loads(lines[1])["pid"] == os.getpid()


class TestProjectWorkspaceFallback:
    """Test fallback from TOPSAILAI_PROJECT_WORKSPACE to TOPSAILAI_PWD."""

    def test_uses_project_workspace_when_set(self, temp_history_path):
        with patch.dict(
            os.environ,
            {
                "TOPSAILAI_PROJECT_WORKSPACE": "/explicit/workspace",
                "TOPSAILAI_PWD": "/startup/dir",
            },
            clear=True,
        ):
            history.record_project_history("s1")

        entry = json.loads(Path(temp_history_path).read_text(encoding="utf-8").strip())
        assert entry["project_workspace"] == "/explicit/workspace"
        assert entry["pwd"] == "/startup/dir"
        assert entry["pid"] == os.getpid()

    def test_falls_back_to_pwd_when_project_workspace_missing(self, temp_history_path):
        with patch.dict(
            os.environ,
            {"TOPSAILAI_PWD": "/fallback/dir"},
            clear=True,
        ):
            history.record_project_history("s2")

        entry = json.loads(Path(temp_history_path).read_text(encoding="utf-8").strip())
        assert entry["project_workspace"] == "/fallback/dir"
        assert entry["pwd"] == "/fallback/dir"
        assert entry["pid"] == os.getpid()

    def test_falls_back_to_pwd_when_project_workspace_empty(self, temp_history_path):
        with patch.dict(
            os.environ,
            {
                "TOPSAILAI_PROJECT_WORKSPACE": "",
                "TOPSAILAI_PWD": "/fallback/dir",
            },
            clear=True,
        ):
            history.record_project_history("s3")

        entry = json.loads(Path(temp_history_path).read_text(encoding="utf-8").strip())
        assert entry["project_workspace"] == "/fallback/dir"
        assert entry["pid"] == os.getpid()

    def test_empty_strings_when_both_missing(self, temp_history_path):
        with patch.dict(os.environ, {}, clear=True):
            history.record_project_history("s4")

        entry = json.loads(Path(temp_history_path).read_text(encoding="utf-8").strip())
        assert entry["project_workspace"] == ""
        assert entry["pwd"] == ""
        assert entry["pid"] == os.getpid()


class TestRotation:
    """Test size-based rotation and backup count enforcement."""

    def test_rotation_happens_when_size_exceeded(self, temp_history_path):
        with patch.dict(
            os.environ,
            {
                "TOPSAILAI_PROJECT_WORKSPACE": "/workspace/project",
                "TOPSAILAI_PWD": "/workspace/project",
                "TOPSAILAI_PROJECT_HISTORY_MAX_SIZE": "100",
                "TOPSAILAI_PROJECT_HISTORY_MAX_BACKUP": "2",
            },
            clear=True,
        ):
            # First record fits under 100 bytes.
            history.record_project_history("first")
            # Second record pushes the file over 100 bytes, triggering rotation.
            history.record_project_history("second")

        history_path = Path(temp_history_path)
        assert history_path.exists()
        # The current file should contain only the latest record.
        current_lines = history_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(current_lines) == 1
        assert json.loads(current_lines[0])["session_id"] == "second"
        assert json.loads(current_lines[0])["pid"] == os.getpid()

        # The previous content should have been rotated to .1
        backup_1 = Path(str(temp_history_path) + ".1")
        assert backup_1.exists()
        backup_lines = backup_1.read_text(encoding="utf-8").strip().splitlines()
        assert len(backup_lines) == 1
        assert json.loads(backup_lines[0])["session_id"] == "first"
        assert json.loads(backup_lines[0])["pid"] == os.getpid()

    def test_backup_count_is_enforced(self, temp_history_path):
        with patch.dict(
            os.environ,
            {
                "TOPSAILAI_PROJECT_WORKSPACE": "/workspace/project",
                "TOPSAILAI_PWD": "/workspace/project",
                "TOPSAILAI_PROJECT_HISTORY_MAX_SIZE": "1",
                "TOPSAILAI_PROJECT_HISTORY_MAX_BACKUP": "1",
            },
            clear=True,
        ):
            history.record_project_history("record-1")
            history.record_project_history("record-2")
            history.record_project_history("record-3")

        history_path = Path(temp_history_path)
        backup_1 = Path(str(temp_history_path) + ".1")
        backup_2 = Path(str(temp_history_path) + ".2")

        current = json.loads(history_path.read_text(encoding="utf-8").strip())
        assert current["session_id"] == "record-3"
        assert current["pid"] == os.getpid()

        assert backup_1.exists()
        rotated = json.loads(backup_1.read_text(encoding="utf-8").strip())
        assert rotated["session_id"] == "record-2"
        assert rotated["pid"] == os.getpid()

        # With max_backup=1, the oldest backup (.2) must not exist.
        assert not backup_2.exists()

    def test_zero_backups_truncates_current_file(self, temp_history_path):
        with patch.dict(
            os.environ,
            {
                "TOPSAILAI_PROJECT_WORKSPACE": "/workspace/project",
                "TOPSAILAI_PWD": "/workspace/project",
                "TOPSAILAI_PROJECT_HISTORY_MAX_SIZE": "1",
                "TOPSAILAI_PROJECT_HISTORY_MAX_BACKUP": "0",
            },
            clear=True,
        ):
            history.record_project_history("record-1")
            history.record_project_history("record-2")

        history_path = Path(temp_history_path)
        backup_1 = Path(str(temp_history_path) + ".1")

        current = json.loads(history_path.read_text(encoding="utf-8").strip())
        assert current["session_id"] == "record-2"
        assert current["pid"] == os.getpid()
        assert not backup_1.exists()

    def test_invalid_env_vars_use_defaults(self, temp_history_path):
        with patch.dict(
            os.environ,
            {
                "TOPSAILAI_PROJECT_WORKSPACE": "/workspace/project",
                "TOPSAILAI_PWD": "/workspace/project",
                "TOPSAILAI_PROJECT_HISTORY_MAX_SIZE": "not-a-number",
                "TOPSAILAI_PROJECT_HISTORY_MAX_BACKUP": "also-not-a-number",
            },
            clear=True,
        ):
            # A single small record should not rotate with defaults (1 MiB).
            history.record_project_history("default-size")

        history_path = Path(temp_history_path)
        backup_1 = Path(str(temp_history_path) + ".1")
        assert backup_1.exists() is False
        entry = json.loads(history_path.read_text(encoding="utf-8").strip())
        assert entry["session_id"] == "default-size"
        assert entry["pid"] == os.getpid()

    def test_zero_max_size_disables_rotation(self, temp_history_path):
        with patch.dict(
            os.environ,
            {
                "TOPSAILAI_PROJECT_WORKSPACE": "/workspace/project",
                "TOPSAILAI_PWD": "/workspace/project",
                "TOPSAILAI_PROJECT_HISTORY_MAX_SIZE": "0",
                "TOPSAILAI_PROJECT_HISTORY_MAX_BACKUP": "1",
            },
            clear=True,
        ):
            history.record_project_history("record-1")
            history.record_project_history("record-2")

        history_path = Path(temp_history_path)
        backup_1 = Path(str(temp_history_path) + ".1")
        assert not backup_1.exists()
        lines = history_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["session_id"] == "record-1"
        assert json.loads(lines[0])["pid"] == os.getpid()
        assert json.loads(lines[1])["session_id"] == "record-2"
        assert json.loads(lines[1])["pid"] == os.getpid()


class TestLoadProjectHistory:
    """Test loading project history with the most-recent-N limit."""

    def test_load_returns_most_recent_100_by_default(self, temp_history_path):
        total = 150
        with temp_history_path.open("w", encoding="utf-8") as f:
            for i in range(total):
                f.write(json.dumps({"session_id": f"session-{i:03d}"}) + "\n")

        records = history.load_project_history()
        assert len(records) == 100
        assert records[0]["session_id"] == "session-050"
        assert records[-1]["session_id"] == "session-149"

    def test_load_returns_all_records_when_below_limit(self, temp_history_path):
        total = 10
        with temp_history_path.open("w", encoding="utf-8") as f:
            for i in range(total):
                f.write(json.dumps({"session_id": f"session-{i:03d}"}) + "\n")

        records = history.load_project_history()
        assert len(records) == total
        assert records[0]["session_id"] == "session-000"
        assert records[-1]["session_id"] == "session-009"

    def test_load_returns_empty_list_when_file_missing(self, temp_history_path):
        # Ensure the file does not exist.
        if temp_history_path.exists():
            temp_history_path.unlink()

        records = history.load_project_history()
        assert records == []

    def test_load_respects_custom_max_entries(self, temp_history_path):
        total = 50
        with temp_history_path.open("w", encoding="utf-8") as f:
            for i in range(total):
                f.write(json.dumps({"session_id": f"session-{i:03d}"}) + "\n")

        records = history.load_project_history(max_entries=20)
        assert len(records) == 20
        assert records[0]["session_id"] == "session-030"
        assert records[-1]["session_id"] == "session-049"

    def test_load_skips_malformed_lines(self, temp_history_path):
        with temp_history_path.open("w", encoding="utf-8") as f:
            for i in range(105):
                f.write(json.dumps({"session_id": f"session-{i:03d}"}) + "\n")
            f.write("this is not json\n")

        records = history.load_project_history()
        assert len(records) == 100
        assert records[-1]["session_id"] == "session-104"

    def test_load_keeps_pid_field_when_present(self, temp_history_path):
        with temp_history_path.open("w", encoding="utf-8") as f:
            f.write(json.dumps({"session_id": "with-pid", "pid": 12345}) + "\n")
            f.write(json.dumps({"session_id": "without-pid"}) + "\n")

        records = history.load_project_history()
        assert len(records) == 2
        assert records[0]["session_id"] == "with-pid"
        assert records[0]["pid"] == 12345
        assert records[1]["session_id"] == "without-pid"
        assert "pid" not in records[1]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
