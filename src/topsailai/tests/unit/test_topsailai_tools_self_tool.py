"""
Unit tests for topsailai.tools.self_tool module.

This module tests the self-awareness tool that reads the session metadata file:
- get_self_info(): returns the agent's own runtime identity and work details
- _resolve_related_files(): resolves stored basenames into absolute paths

Author: DawsonLin
"""

import json
import os

import pytest

from topsailai.tools import self_tool


def _write_meta(folder, session_id, payload):
    """Write a metadata file for the current pid and return its path."""
    path = os.path.join(
        folder, f"{session_id}.{os.getpid()}.session.meta"
    )
    with open(path, "w", encoding="utf-8") as fd:
        if isinstance(payload, str):
            fd.write(payload)
        else:
            json.dump(payload, fd)
    return path


@pytest.fixture
def meta_folder(tmp_path, monkeypatch):
    """Point the metadata folder at an isolated temporary directory."""
    monkeypatch.setattr(self_tool.session_meta, "FOLDER_WORKSPACE_TASK", str(tmp_path))
    monkeypatch.setenv("SESSION_ID", "self-test")
    return tmp_path


class TestToolRegistration:
    """Test cases for tool registration and prompt contract."""

    def test_tool_is_registered(self):
        """Test that get_self_info is exposed through the TOOLS mapping."""
        assert self_tool.TOOLS["get_self_info"] is self_tool.get_self_info

    def test_tool_is_enabled_by_default(self):
        """Test that the tool has no FLAG_TOOL_ENABLED opt-out."""
        assert getattr(self_tool, "FLAG_TOOL_ENABLED", True) is not False

    def test_prompt_documents_the_tool(self):
        """Test that the module prompt names the tool it routes to."""
        assert "self_tool" in self_tool.PROMPT
        assert "get_self_info" in self_tool.PROMPT

    def test_prompt_points_at_history_recoverable_from_files(self):
        """Test that PROMPT tells the agent history is recoverable from files."""
        assert "past messages" in self_tool.PROMPT
        assert "recorded events" in self_tool.PROMPT
        assert "file_tool" in self_tool.PROMPT

    def test_prompt_does_not_restate_the_docstring(self):
        """Test that statuses and field names stay in the docstring only."""
        for status in ("ok", "not_found", "invalid_meta"):
            assert status not in self_tool.PROMPT
        assert "meta_file" not in self_tool.PROMPT
        assert "session metadata file" not in self_tool.PROMPT

    def test_prompt_stays_concise(self):
        """Test that the rejected verbose sections do not come back."""
        assert "Usage Guidelines" not in self_tool.PROMPT
        assert len(self_tool.PROMPT.strip().splitlines()) <= 12

    def test_docstring_is_an_llm_contract(self):
        """Test that the registered docstring documents statuses and fields."""
        doc = self_tool.get_self_info.__doc__
        assert doc
        for token in ("status", "meta_file", "self", "files", "not_found", "invalid_meta"):
            assert token in doc


class TestGetSelfInfoSuccess:
    """Test cases for a successful metadata read."""

    def test_returns_ok_with_stored_fields(self, meta_folder):
        """Test that a valid metadata file is returned under self."""
        payload = {
            "version": 1,
            "session_id": "self-test",
            "session_name": "my run",
            "category": "agent",
            "pid": os.getpid(),
            "status": "running",
            "agent_name": "TopsailAI",
            "model_name": "Kimi-K2.5",
            "files": {"events": "self-test.1.session.events"},
        }
        path = _write_meta(meta_folder, "self-test", payload)

        result = self_tool.get_self_info()

        assert result["status"] == "ok"
        assert result["meta_file"] == path
        assert result["self"]["session_name"] == "my run"
        assert result["self"]["agent_name"] == "TopsailAI"
        assert result["self"]["model_name"] == "Kimi-K2.5"

    def test_related_files_are_absolute(self, meta_folder):
        """Test that stored basenames are resolved to absolute paths."""
        payload = {
            "session_id": "self-test",
            "files": {
                "events": "self-test.1.session.events",
                "stdout": "self-test.1.session.stdout",
            },
        }
        _write_meta(meta_folder, "self-test", payload)

        result = self_tool.get_self_info()

        assert result["files"]["events"] == os.path.join(
            str(meta_folder), "self-test.1.session.events"
        )
        assert result["files"]["stdout"] == os.path.join(
            str(meta_folder), "self-test.1.session.stdout"
        )
        assert all(os.path.isabs(value) for value in result["files"].values())

    def test_absolute_stored_path_is_preserved(self, meta_folder):
        """Test that an already absolute stored path is not re-rooted."""
        absolute = os.path.join(str(meta_folder), "elsewhere", "x.events")
        _write_meta(meta_folder, "self-test", {"files": {"events": absolute}})

        result = self_tool.get_self_info()

        assert result["files"]["events"] == absolute

    def test_missing_files_mapping_yields_empty_dict(self, meta_folder):
        """Test that a metadata record without files still returns ok."""
        _write_meta(meta_folder, "self-test", {"session_id": "self-test"})

        result = self_tool.get_self_info()

        assert result["status"] == "ok"
        assert result["files"] == {}

    def test_non_mapping_files_value_is_ignored(self, meta_folder):
        """Test that a malformed files value degrades to an empty mapping."""
        _write_meta(meta_folder, "self-test", {"files": ["not", "a", "mapping"]})

        result = self_tool.get_self_info()

        assert result["status"] == "ok"
        assert result["files"] == {}

    def test_blank_file_name_is_skipped(self, meta_folder):
        """Test that empty file names are not turned into folder paths."""
        _write_meta(meta_folder, "self-test", {"files": {"events": "", "stdout": "a.stdout"}})

        result = self_tool.get_self_info()

        assert "events" not in result["files"]
        assert "stdout" in result["files"]


class TestGetSelfInfoFailures:
    """Test cases for missing and malformed metadata."""

    def test_missing_file_returns_not_found(self, meta_folder):
        """Test that an absent metadata file reports not_found with its path."""
        result = self_tool.get_self_info()

        assert result["status"] == "not_found"
        assert result["meta_file"].endswith(f"self-test.{os.getpid()}.session.meta")
        assert result["reason"]

    def test_malformed_json_returns_invalid_meta(self, meta_folder):
        """Test that unparsable JSON reports invalid_meta instead of raising."""
        _write_meta(meta_folder, "self-test", "{not valid json")

        result = self_tool.get_self_info()

        assert result["status"] == "invalid_meta"
        assert result["reason"]

    def test_non_object_json_returns_invalid_meta(self, meta_folder):
        """Test that a JSON array is rejected because metadata must be an object."""
        _write_meta(meta_folder, "self-test", "[1, 2, 3]")

        result = self_tool.get_self_info()

        assert result["status"] == "invalid_meta"
        assert result["reason"]

    def test_unreadable_file_returns_invalid_meta(self, meta_folder):
        """Test that an unreadable metadata file reports invalid_meta."""
        path = _write_meta(meta_folder, "self-test", {"session_id": "self-test"})
        os.chmod(path, 0o000)
        try:
            result = self_tool.get_self_info()
        finally:
            os.chmod(path, 0o644)

        if os.geteuid() == 0:
            pytest.skip("root can read a mode 000 file")
        assert result["status"] == "invalid_meta"
        assert result["reason"]


class TestResolveRelatedFiles:
    """Test cases for the related-file path resolver."""

    def test_non_mapping_returns_empty_dict(self):
        """Test that a non-mapping value yields an empty mapping."""
        assert self_tool._resolve_related_files("/task/a.session.meta", None) == {}
        assert self_tool._resolve_related_files("/task/a.session.meta", "x") == {}

    def test_non_string_name_is_skipped(self):
        """Test that a non-string file name is skipped."""
        result = self_tool._resolve_related_files(
            "/task/a.session.meta", {"events": 123, "stdout": "a.stdout"}
        )

        assert result == {"stdout": os.path.join("/task", "a.stdout")}
