#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for topsailai_session_status.py."""

import contextlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

CLI_DIR = Path(__file__).resolve().parents[3]
SRC_DIR = CLI_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))
sys.path.insert(0, str(CLI_DIR))

import topsailai_session_status


def _lock_ctx(acquired):
    """Build a lock context manager that reports the given acquisition result."""

    @contextlib.contextmanager
    def _ctx(session_id=None, timeout=None, to_delete_lock_file=None):
        yield {"fp": object() if acquired else None}

    return _ctx


class TestSessionStatusPlainOutput:
    """Tests for the default human-readable output."""

    def test_idle_prints_bare_word(self, capsys):
        """An acquired lock prints ``idle`` and exits zero."""
        with patch.object(
            topsailai_session_status, "ctxm_try_session_lock", _lock_ctx(True)
        ):
            with patch.object(
                sys, "argv", ["topsailai_session_status", "-s", "sess-1"]
            ):
                topsailai_session_status.main()

        captured = capsys.readouterr()
        assert captured.out.strip() == "idle"
        assert captured.err == ""

    def test_processing_prints_bare_word(self, capsys):
        """A lock that cannot be acquired prints ``processing`` and exits zero."""
        with patch.object(
            topsailai_session_status, "ctxm_try_session_lock", _lock_ctx(False)
        ):
            with patch.object(
                sys, "argv", ["topsailai_session_status", "-s", "sess-1"]
            ):
                topsailai_session_status.main()

        captured = capsys.readouterr()
        assert captured.out.strip() == "processing"
        assert captured.err == ""

    def test_missing_session_reports_error(self, capsys, monkeypatch):
        """No session ID reports on stderr and exits one."""
        monkeypatch.delenv("TOPSAILAI_SESSION_ID", raising=False)
        with patch.object(sys, "argv", ["topsailai_session_status"]):
            with pytest.raises(SystemExit) as excinfo:
                topsailai_session_status.main()

        captured = capsys.readouterr()
        assert excinfo.value.code == 1
        assert captured.out == ""
        assert "TOPSAILAI_SESSION_ID not set" in captured.err


class TestSessionStatusJSONOutput:
    """Tests for the structured ``--json`` output mode."""

    def test_json_idle(self, capsys):
        """``--json`` emits one object with a null error code when idle."""
        with patch.object(
            topsailai_session_status, "ctxm_try_session_lock", _lock_ctx(True)
        ):
            with patch.object(
                sys, "argv", ["topsailai_session_status", "-s", "sess-1", "--json"]
            ):
                with pytest.raises(SystemExit) as excinfo:
                    topsailai_session_status.main()

        captured = capsys.readouterr()
        assert excinfo.value.code == 0
        assert json.loads(captured.out) == {
            "session_id": "sess-1",
            "status": "idle",
            "error_code": None,
            "message": None,
        }
        assert captured.err == ""

    def test_json_processing(self, capsys):
        """``--json`` reports the processing status."""
        with patch.object(
            topsailai_session_status, "ctxm_try_session_lock", _lock_ctx(False)
        ):
            with patch.object(
                sys, "argv", ["topsailai_session_status", "-s", "sess-1", "--json"]
            ):
                with pytest.raises(SystemExit) as excinfo:
                    topsailai_session_status.main()

        captured = capsys.readouterr()
        assert excinfo.value.code == 0
        payload = json.loads(captured.out)
        assert payload["status"] == "processing"
        assert payload["error_code"] is None

    def test_json_missing_session(self, capsys, monkeypatch):
        """A missing session ID still emits one parseable object and exits one."""
        monkeypatch.delenv("TOPSAILAI_SESSION_ID", raising=False)
        with patch.object(sys, "argv", ["topsailai_session_status", "--json"]):
            with pytest.raises(SystemExit) as excinfo:
                topsailai_session_status.main()

        captured = capsys.readouterr()
        assert excinfo.value.code == 1
        payload = json.loads(captured.out)
        assert payload["session_id"] is None
        assert payload["status"] is None
        assert payload["error_code"] == "missing_session_id"
        assert "TOPSAILAI_SESSION_ID not set" in payload["message"]
        assert captured.err == ""

    def test_json_lock_failure(self, capsys):
        """A lock exception becomes a structured error instead of a bare message."""

        def _boom(session_id=None, timeout=None, to_delete_lock_file=None):
            raise RuntimeError("lock backend unavailable")

        with patch.object(topsailai_session_status, "ctxm_try_session_lock", _boom):
            with patch.object(
                sys, "argv", ["topsailai_session_status", "-s", "sess-1", "--json"]
            ):
                with pytest.raises(SystemExit) as excinfo:
                    topsailai_session_status.main()

        captured = capsys.readouterr()
        assert excinfo.value.code == 1
        payload = json.loads(captured.out)
        assert payload["session_id"] == "sess-1"
        assert payload["status"] is None
        assert payload["error_code"] == "status_unavailable"
        assert "lock backend unavailable" in payload["message"]
        assert captured.err == ""

    def test_json_uses_environment_session_id(self, capsys, monkeypatch):
        """The environment session ID is echoed in the JSON payload."""
        monkeypatch.setenv("TOPSAILAI_SESSION_ID", "env-sess")
        with patch.object(
            topsailai_session_status, "ctxm_try_session_lock", _lock_ctx(True)
        ):
            with patch.object(
                sys, "argv", ["topsailai_session_status", "--json"]
            ):
                with pytest.raises(SystemExit) as excinfo:
                    topsailai_session_status.main()

        captured = capsys.readouterr()
        assert excinfo.value.code == 0
        assert json.loads(captured.out)["session_id"] == "env-sess"
