"""Unit tests for bounded LRU startup memory loading."""

import os
from unittest import mock

from topsailai.tools import story_memory_tool


def _stat(memory_id, activity="2026-08-24 01:00:00 +08:00", created=None):
    return {
        "memory_id": memory_id,
        "last_activity_at": activity,
        "created_at": created or activity,
    }


def test_parse_max_tokens():
    assert story_memory_tool._parse_max_tokens(None) == 0
    assert story_memory_tool._parse_max_tokens("") == 0
    assert story_memory_tool._parse_max_tokens("invalid") == 0
    assert story_memory_tool._parse_max_tokens("-7") == 0
    assert story_memory_tool._parse_max_tokens("12") == 12


@mock.patch.object(story_memory_tool, "list_memories", return_value=None)
def test_empty_memory_directory(mock_list):
    assert story_memory_tool._load_memories_lru(10) == {}
    mock_list.assert_called_once_with()


@mock.patch.object(story_memory_tool, "count_tokens", side_effect=lambda text: len(text))
@mock.patch.object(story_memory_tool, "read_memory_without_count")
@mock.patch.object(story_memory_tool.memory_stat, "read_memory_stat")
@mock.patch.object(story_memory_tool, "list_memories")
def test_unlimited_loads_all_in_mru_order(mock_list, mock_stat, mock_read, _mock_tokens):
    mock_list.return_value = ["old.md", "new.md"]
    stats = {
        "old.md": _stat("old.md", "2026-08-23 01:00:00 +08:00"),
        "new.md": _stat("new.md", "2026-08-24 01:00:00 +08:00"),
    }
    mock_stat.side_effect = lambda _workspace, title: stats[title]
    mock_read.side_effect = lambda title: title

    result = story_memory_tool._load_memories_lru(0)

    assert list(result) == ["new.md", "old.md"]


@mock.patch.object(story_memory_tool, "count_tokens", side_effect=lambda text: len(text))
@mock.patch.object(story_memory_tool, "read_memory_without_count")
@mock.patch.object(story_memory_tool.memory_stat, "read_memory_stat")
@mock.patch.object(story_memory_tool, "list_memories")
def test_positive_limit_stops_before_exceed(mock_list, mock_stat, mock_read, _mock_tokens):
    mock_list.return_value = ["new.md", "old.md", "tail.md"]
    mock_stat.side_effect = lambda _workspace, title: {
        "new.md": _stat("new.md", "2026-08-24 03:00:00 +08:00"),
        "old.md": _stat("old.md", "2026-08-24 02:00:00 +08:00"),
        "tail.md": _stat("tail.md", "2026-08-24 01:00:00 +08:00"),
    }[title]
    mock_read.side_effect = {"new.md": "123", "old.md": "456", "tail.md": "7"}.get

    result = story_memory_tool._load_memories_lru(5)

    assert list(result) == ["new.md"]
    mock_read.assert_has_calls([mock.call("new.md"), mock.call("old.md")])
    assert mock.call("tail.md") not in mock_read.call_args_list


@mock.patch.object(story_memory_tool, "count_tokens", return_value=1)
@mock.patch.object(story_memory_tool, "read_memory_without_count", return_value="content")
@mock.patch.object(story_memory_tool.memory_stat, "read_memory_stat")
@mock.patch.object(story_memory_tool, "list_memories")
def test_ties_use_created_desc_then_memory_id_asc(
    mock_list, mock_stat, _mock_read, _mock_tokens
):
    mock_list.return_value = ["b.md", "old-created.md", "a.md"]
    common_activity = "2026-08-24 03:00:00 +08:00"
    stats = {
        "a.md": _stat("z-memory", common_activity, "2026-08-24 02:00:00 +08:00"),
        "b.md": _stat("a-memory", common_activity, "2026-08-24 02:00:00 +08:00"),
        "old-created.md": _stat(
            "old-created.md", common_activity, "2026-08-24 01:00:00 +08:00"
        ),
    }
    mock_stat.side_effect = lambda _workspace, title: stats[title]

    result = story_memory_tool._load_memories_lru(10)

    assert list(result) == ["b.md", "a.md", "old-created.md"]


@mock.patch.object(story_memory_tool, "count_tokens", return_value=1)
@mock.patch.object(story_memory_tool, "read_memory_without_count", return_value="content")
@mock.patch.object(story_memory_tool.memory_stat, "read_memory_stat")
@mock.patch.object(story_memory_tool, "list_memories")
def test_missing_stat_sorts_last(mock_list, mock_stat, _mock_read, _mock_tokens):
    mock_list.return_value = ["missing.md", "tracked.md"]
    mock_stat.side_effect = lambda _workspace, title: (
        None if title == "missing.md" else _stat("tracked.md")
    )

    result = story_memory_tool._load_memories_lru(10)

    assert list(result) == ["tracked.md", "missing.md"]


@mock.patch.object(story_memory_tool, "count_tokens", return_value=1)
@mock.patch.object(story_memory_tool, "read_memory_without_count", return_value="content")
@mock.patch.object(story_memory_tool.memory_stat, "record_memory_event")
@mock.patch.object(story_memory_tool.memory_stat, "read_memory_stat")
@mock.patch.object(story_memory_tool, "list_memories", return_value=["memory.md"])
def test_loader_is_non_counting(
    _mock_list, mock_stat, mock_record, mock_read, _mock_tokens
):
    persisted = _stat("memory.md") | {"read_count": 4, "last_read_at": None}
    mock_stat.return_value = persisted.copy()

    story_memory_tool._load_memories_lru(10)

    mock_read.assert_called_once_with("memory.md")
    mock_record.assert_not_called()
    assert persisted["read_count"] == 4
    assert persisted["last_read_at"] is None


@mock.patch.object(story_memory_tool, "get_all_memories")
@mock.patch.object(story_memory_tool, "_load_memories_lru")
def test_prompt_uses_env_budget(mock_load, mock_all):
    mock_load.return_value = {"memory.md": "content"}
    with mock.patch.dict(os.environ, {"TOPSAILAI_CONTEXT_MEMORY_LOAD_MAX_TOKENS": "9"}):
        prompt = story_memory_tool.get_prompt_memory()

    assert "content" in prompt
    mock_load.assert_called_once_with(9)
    mock_all.assert_not_called()


def test_stats_directory_is_not_a_candidate():
    with mock.patch.object(
        story_memory_tool, "list_memories", return_value=["memory.md"]
    ), mock.patch.object(
        story_memory_tool.memory_stat, "read_memory_stat", return_value=_stat("memory.md")
    ), mock.patch.object(
        story_memory_tool, "read_memory_without_count", return_value="content"
    ), mock.patch.object(story_memory_tool, "count_tokens", return_value=1):
        result = story_memory_tool._load_memories_lru(10)

    assert list(result) == ["memory.md"]
    assert ".stats" not in result
