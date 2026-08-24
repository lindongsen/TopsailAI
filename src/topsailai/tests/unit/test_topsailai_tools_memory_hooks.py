"""Unit tests for story memory create and update hooks."""

from unittest import mock

import pytest

from topsailai.tools import story_memory_tool
from topsailai.tools.memory_tool_utils import memory_hooks


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch):
    """Give every test an empty registry and disable real external scripts."""
    registry = memory_hooks.MemoryHookRegistry()
    monkeypatch.setattr(memory_hooks, "REGISTRY", registry)
    external = mock.Mock(return_value={})
    monkeypatch.setattr(memory_hooks.hook_tool, "call_hook_scripts", external)
    return registry


def _write(operation_exists=False, content="content"):
    story_id = "20260824040604.memory.md"
    memory_file = "/memory/story/2026-08-24/" + story_id
    with mock.patch.object(story_memory_tool, "build_story_id", return_value=story_id), \
         mock.patch.object(
             story_memory_tool.StoryFileInstance,
             "get_story_file",
             return_value=memory_file if operation_exists else None,
         ), \
         mock.patch.object(
             story_memory_tool.StoryFileInstance, "write_story", return_value=memory_file
         ), \
         mock.patch.object(
             story_memory_tool.time_tool,
             "get_current_local_datetime_with_offset",
             return_value="2026-08-24 04:06:04 +08:00",
         ):
        result = story_memory_tool.write_memory("memory", content)
    return result, memory_file


def test_no_hooks_registered_is_noop():
    result, memory_file = _write()
    assert memory_file in result


def test_create_hook_receives_complete_event():
    events = []
    memory_hooks.register_create_hook(events.append)

    _, memory_file = _write()

    assert events == [{
        "op": "create",
        "memory_id": "20260824040604.memory.md",
        "title": "memory",
        "content": "content",
        "memory_file": memory_file,
        "workspace": story_memory_tool.WORKSPACE,
        "timestamp": "2026-08-24 04:06:04 +08:00",
    }]


def test_create_and_update_are_distinct():
    operations = []
    memory_hooks.register_create_hook(lambda event: operations.append(event["op"]))
    memory_hooks.register_update_hook(lambda event: operations.append(event["op"]))

    _write(operation_exists=False)
    _write(operation_exists=True)

    assert operations == ["create", "update"]


def test_multiple_hooks_keep_order_and_continue_after_exception():
    calls = []

    def failing(_event):
        calls.append("first")
        raise RuntimeError("hook failed")

    memory_hooks.register_create_hook(failing)
    memory_hooks.register_create_hook(lambda _event: calls.append("second"))

    result, memory_file = _write()

    assert memory_file in result
    assert calls == ["first", "second"]


def test_register_unregister_and_validation(isolated_registry):
    hook = mock.Mock()
    memory_hooks.register_update_hook(hook)
    assert memory_hooks.unregister_update_hook(hook) is True
    assert memory_hooks.unregister_update_hook(hook) is False
    assert isolated_registry.call("update", {}) == []
    assert isolated_registry.call("unknown", {}) == []
    with pytest.raises(ValueError, match="unsupported"):
        isolated_registry.register("unknown", hook)
    with pytest.raises(ValueError, match="callable"):
        isolated_registry.register("create", None)


def test_external_scripts_run_after_in_process(monkeypatch):
    order = []
    memory_hooks.register_create_hook(lambda _event: order.append("in-process"))

    def external(key, event):
        order.append("external")
        assert key == "TOPSAILAI_HOOK_SCRIPTS_MEMORY_WRITE"
        assert event["op"] == "create"
        return {"script": "ok"}

    monkeypatch.setattr(memory_hooks.hook_tool, "call_hook_scripts", external)

    result = memory_hooks.fire_memory_hooks("create", {"op": "create"})

    assert order == ["in-process", "external"]
    assert result["external"] == {"script": "ok"}


def test_external_script_bridge_is_fail_open(monkeypatch):
    monkeypatch.setattr(
        memory_hooks.hook_tool,
        "call_hook_scripts",
        mock.Mock(side_effect=RuntimeError("bridge failed")),
    )
    assert memory_hooks.fire_memory_hooks("create", {})["external"] == {}


def test_write_hook_does_not_record_or_mutate_stats():
    stat = {"read_count": 4, "last_read_at": None}
    with mock.patch.object(story_memory_tool.memory_stat, "record_memory_event") as record, \
         mock.patch.object(story_memory_tool.memory_stat, "ensure_memory_stat", return_value=stat):
        _write()

    record.assert_not_called()
    assert stat == {"read_count": 4, "last_read_at": None}


def test_lru_loader_does_not_fire_hooks(monkeypatch):
    fire = mock.Mock()
    monkeypatch.setattr(story_memory_tool.memory_hooks, "fire_memory_hooks", fire)
    with mock.patch.object(story_memory_tool, "list_memories", return_value=[]):
        assert story_memory_tool._load_memories_lru(10) == {}
    fire.assert_not_called()


def test_write_dispatch_failure_is_fail_open(monkeypatch):
    monkeypatch.setattr(
        story_memory_tool.memory_hooks,
        "fire_memory_hooks",
        mock.Mock(side_effect=RuntimeError("dispatch failed")),
    )
    result, memory_file = _write(content="")
    assert memory_file in result


def test_hooks_run_only_after_stat_ensure(monkeypatch):
    order = []
    story_id = "20260824040604.memory.md"
    memory_file = "/memory/story/2026-08-24/" + story_id

    def write_story(**kwargs):
        kwargs["after_write"](memory_file)
        return memory_file

    monkeypatch.setattr(
        story_memory_tool.memory_stat,
        "ensure_memory_stat",
        lambda *_args: order.append("stat"),
    )
    memory_hooks.register_create_hook(lambda _event: order.append("hook"))
    with mock.patch.object(story_memory_tool, "build_story_id", return_value=story_id), \
         mock.patch.object(story_memory_tool.StoryFileInstance, "get_story_file", return_value=None), \
         mock.patch.object(story_memory_tool.StoryFileInstance, "write_story", side_effect=write_story):
        story_memory_tool.write_memory("memory", "content")

    assert order == ["stat", "hook"]


def test_failed_write_does_not_fire_hooks(monkeypatch):
    fire = mock.Mock()
    monkeypatch.setattr(story_memory_tool.memory_hooks, "fire_memory_hooks", fire)
    with mock.patch.object(story_memory_tool, "build_story_id", return_value="memory.md"), \
         mock.patch.object(story_memory_tool.StoryFileInstance, "get_story_file", return_value=None), \
         mock.patch.object(
             story_memory_tool.StoryFileInstance,
             "write_story",
             side_effect=OSError("write failed"),
         ), pytest.raises(OSError, match="write failed"):
        story_memory_tool.write_memory("memory", "content")

    fire.assert_not_called()


def test_unregister_create_hook_reports_presence_and_removes_hook():
    """A registered create hook is removed once and absent thereafter."""
    hook = mock.Mock()
    memory_hooks.register_create_hook(hook)

    assert memory_hooks.unregister_create_hook(hook) is True
    assert memory_hooks.unregister_create_hook(hook) is False
    memory_hooks.fire_memory_hooks(memory_hooks.CREATE, {"operation": "create"})
    hook.assert_not_called()
