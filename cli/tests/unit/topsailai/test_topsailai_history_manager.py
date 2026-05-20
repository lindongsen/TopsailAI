"""Unit tests for HistoryManager and load_readline_history in topsailai.py."""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

import topsailai


class TestHistoryManager:
    """Tests for HistoryManager class."""

    def test_load_all_empty_file(self):
        """Loading from a non-existent file should result in empty entries."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name
        os.remove(path)
        manager = topsailai.HistoryManager(path)
        manager.load_all()
        assert manager.entries == []

    def test_load_all_valid_entries(self):
        """Loading should parse valid JSON lines and skip invalid ones."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, encoding="utf-8") as f:
            f.write(json.dumps({"scope": "workspace", "session_id": "", "ts": 1, "text": "hello"}) + "\n")
            f.write("not a json line\n")
            f.write(json.dumps({"scope": "session", "session_id": "s1", "ts": 2, "text": "world"}) + "\n")
            path = f.name

        manager = topsailai.HistoryManager(path)
        manager.load_all()
        assert len(manager.entries) == 2
        assert manager.entries[0]["text"] == "hello"
        assert manager.entries[1]["text"] == "world"
        os.remove(path)

    def test_append_persists_to_file(self):
        """Append should write a JSON line to the file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, encoding="utf-8") as f:
            path = f.name

        manager = topsailai.HistoryManager(path)
        manager.append("workspace", "", "/refresh")

        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["scope"] == "workspace"
        assert entry["session_id"] == ""
        assert entry["text"] == "/refresh"
        assert isinstance(entry["ts"], int)
        os.remove(path)

    def test_filter_entries_by_scope(self):
        """filter_entries should return only matching scope commands."""
        manager = topsailai.HistoryManager("")
        manager.entries = [
            {"scope": "workspace", "session_id": "", "ts": 1, "text": "w1"},
            {"scope": "session", "session_id": "s1", "ts": 2, "text": "s1"},
            {"scope": "workspace", "session_id": "", "ts": 3, "text": "w2"},
        ]
        result = manager.filter_entries("workspace")
        assert result == ["w1", "w2"]

    def test_filter_entries_by_session(self):
        """filter_entries for session scope should also match session_id."""
        manager = topsailai.HistoryManager("")
        manager.entries = [
            {"scope": "session", "session_id": "s1", "ts": 1, "text": "a"},
            {"scope": "session", "session_id": "s2", "ts": 2, "text": "b"},
            {"scope": "session", "session_id": "s1", "ts": 3, "text": "c"},
        ]
        result = manager.filter_entries("session", "s1")
        assert result == ["a", "c"]

    def test_filter_entries_skips_empty_text(self):
        """Entries with empty text should be excluded from results."""
        manager = topsailai.HistoryManager("")
        manager.entries = [
            {"scope": "workspace", "session_id": "", "ts": 1, "text": ""},
            {"scope": "workspace", "session_id": "", "ts": 2, "text": "valid"},
        ]
        result = manager.filter_entries("workspace")
        assert result == ["valid"]


class TestLoadReadlineHistory:
    """Tests for load_readline_history function."""

    def test_load_readline_history_adds_entries(self):
        """Filtered entries should be added to readline history."""
        manager = topsailai.HistoryManager("")
        manager.entries = [
            {"scope": "workspace", "session_id": "", "ts": 1, "text": "cmd1"},
            {"scope": "workspace", "session_id": "", "ts": 2, "text": "cmd2"},
        ]
        topsailai.load_readline_history(manager, "workspace", None)
        assert topsailai.readline.get_history_item(1) == "cmd1"
        assert topsailai.readline.get_history_item(2) == "cmd2"

    def test_load_readline_history_clears_previous(self):
        """Previous readline history should be cleared before loading."""
        try:
            topsailai.readline.add_history("old_cmd")
        except Exception:
            pass
        manager = topsailai.HistoryManager("")
        manager.entries = [
            {"scope": "session", "session_id": "s1", "ts": 1, "text": "new_cmd"},
        ]
        topsailai.load_readline_history(manager, "session", "s1")
        assert topsailai.readline.get_history_item(1) == "new_cmd"
        assert topsailai.readline.get_history_item(2) is None
