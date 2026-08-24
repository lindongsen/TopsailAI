"""Unit tests for story memory create and update hooks."""

import json
from unittest import mock

import pytest

from topsailai.tools import story_memory_tool
from topsailai.tools.memory_tool_utils import memory_hooks


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch):
    """Give every test an empty registry and disable real external scripts."""
    registry = memory_hooks.MemoryHookRegistry()
    monkeypatch.setattr(memory_hooks, "REGISTRY", registry)
    monkeypatch.delenv(memory_hooks.MEMORY_SYNC_HOOKS_ENV_KEY, raising=False)
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
        "version": 1,
    }]


def test_create_and_update_versions_are_monotonic(monkeypatch, tmp_path):
    story_id = "20260824040604.memory.md"
    memory_file = str(tmp_path / "story" / story_id)
    events = []
    existing = [None, memory_file]

    def write_story(**kwargs):
        kwargs["after_write"](memory_file)
        return memory_file

    monkeypatch.setattr(story_memory_tool, "WORKSPACE", str(tmp_path))
    memory_hooks.register_create_hook(events.append)
    memory_hooks.register_update_hook(events.append)
    with mock.patch.object(story_memory_tool, "build_story_id", return_value=story_id), \
         mock.patch.object(
             story_memory_tool.StoryFileInstance,
             "get_story_file",
             side_effect=existing,
         ), \
         mock.patch.object(
             story_memory_tool.StoryFileInstance,
             "write_story",
             side_effect=write_story,
         ):
        story_memory_tool.write_memory("memory", "first")
        story_memory_tool.write_memory("memory", "second")

    assert [event["op"] for event in events] == ["create", "update"]
    assert [event["version"] for event in events] == [1, 2]


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


def _sync_event():
    """Return a complete internal event for sync-dispatch tests."""
    return {
        "op": "create",
        "memory_id": "20260824040604.memory.md",
        "title": "memory",
        "content": "內容",
        "memory_file": "/memory/story/2026-08-24/20260824040604.memory.md",
        "workspace": "/memory",
        "timestamp": "2026-08-24 04:06:04 +08:00",
        "version": 2,
    }


def test_sync_dispatch_passes_stable_json_to_selected_binding(monkeypatch):
    """A matching binding receives the complete stable event through stdin."""
    config = {
        "create": [{
            "script": "/hooks/sync",
            "timeout": 17,
            "enabled": True,
            "env_keys": ["MEM_GRAPH_URL"],
        }],
        "update": [{"script": "/hooks/update-only"}],
    }
    monkeypatch.setenv(memory_hooks.MEMORY_SYNC_HOOKS_ENV_KEY, json.dumps(config))
    execute = mock.Mock(return_value=(0, "ok", ""))
    monkeypatch.setattr(memory_hooks.cmd_tool, "exec_cmd", execute)

    result = memory_hooks.fire_memory_hooks("create", _sync_event())

    execute.assert_called_once()
    assert execute.call_args.args == (["/hooks/sync"],)
    assert execute.call_args.kwargs["timeout"] == 17
    assert execute.call_args.kwargs["env_keys"] == ["MEM_GRAPH_URL"]
    assert json.loads(execute.call_args.kwargs["stdin_text"]) == {
        "schema_version": 1,
        "event": "create",
        "memory_id": "20260824040604.memory.md",
        "title": "memory",
        "content": "內容",
        "memory_file": "/memory/story/2026-08-24/20260824040604.memory.md",
        "workspace": "/memory",
        "timestamp": "2026-08-24 04:06:04 +08:00",
        "version": 2,
    }
    assert result["sync"] == [(0, "ok", "")]


def test_sync_dispatch_invalid_json_and_disabled_binding_are_noops(monkeypatch):
    """Invalid configuration and explicitly disabled bindings execute nothing."""
    execute = mock.Mock()
    monkeypatch.setattr(memory_hooks.cmd_tool, "exec_cmd", execute)
    monkeypatch.setenv(memory_hooks.MEMORY_SYNC_HOOKS_ENV_KEY, "not-json")
    assert memory_hooks.dispatch_memory_sync_hooks("create", _sync_event()) == []

    config = {"create": [{"script": "/hooks/sync", "enabled": False}]}
    monkeypatch.setenv(memory_hooks.MEMORY_SYNC_HOOKS_ENV_KEY, json.dumps(config))
    assert memory_hooks.dispatch_memory_sync_hooks("create", _sync_event()) == [None]
    execute.assert_not_called()


def test_sync_dispatch_ignores_unknown_delete_event_with_warning(monkeypatch, caplog):
    """Delete configuration is warned about and never dispatched."""
    config = {"delete": [{"script": "/hooks/delete"}]}
    monkeypatch.setenv(memory_hooks.MEMORY_SYNC_HOOKS_ENV_KEY, json.dumps(config))
    execute = mock.Mock()
    monkeypatch.setattr(memory_hooks.cmd_tool, "exec_cmd", execute)

    with caplog.at_level("WARNING"):
        result = memory_hooks.dispatch_memory_sync_hooks("create", _sync_event())

    assert result == []
    assert "unsupported memory sync event: delete" in caplog.text
    execute.assert_not_called()


def test_sync_dispatch_is_fail_open_per_binding(monkeypatch):
    """One failing binding does not prevent later bindings from running."""
    config = {"create": [
        {"script": "/hooks/fail"},
        {"script": "/hooks/pass", "timeout": 9},
    ]}
    monkeypatch.setenv(memory_hooks.MEMORY_SYNC_HOOKS_ENV_KEY, json.dumps(config))
    execute = mock.Mock(side_effect=[RuntimeError("failed"), (0, "ok", "")])
    monkeypatch.setattr(memory_hooks.cmd_tool, "exec_cmd", execute)

    result = memory_hooks.dispatch_memory_sync_hooks("create", _sync_event())

    assert result == [None, (0, "ok", "")]
    assert [call.args[0] for call in execute.call_args_list] == [
        ["/hooks/fail"],
        ["/hooks/pass"],
    ]


def test_sync_dispatch_coexists_with_legacy_external_hook(monkeypatch):
    """The new dispatcher runs in addition to the unchanged legacy bridge."""
    config = {"create": [{"script": "/hooks/sync"}]}
    monkeypatch.setenv(memory_hooks.MEMORY_SYNC_HOOKS_ENV_KEY, json.dumps(config))
    legacy = mock.Mock(return_value={"legacy": "ok"})
    execute = mock.Mock(return_value=(0, "sync", ""))
    monkeypatch.setattr(memory_hooks.hook_tool, "call_hook_scripts", legacy)
    monkeypatch.setattr(memory_hooks.cmd_tool, "exec_cmd", execute)

    result = memory_hooks.fire_memory_hooks("create", _sync_event())

    legacy.assert_called_once_with(memory_hooks.EXTERNAL_HOOK_ENV_KEY, _sync_event())
    execute.assert_called_once()
    assert result["external"] == {"legacy": "ok"}
    assert result["sync"] == [(0, "sync", "")]


def test_sync_dispatch_rejects_non_object_config_and_unknown_operation(monkeypatch, caplog):
    """Non-object configuration and unsupported runtime operations are no-ops."""
    monkeypatch.setenv(memory_hooks.MEMORY_SYNC_HOOKS_ENV_KEY, "[]")
    with caplog.at_level("WARNING"):
        assert memory_hooks.dispatch_memory_sync_hooks("create", _sync_event()) == []
    assert "must contain a JSON object" in caplog.text
    assert memory_hooks.dispatch_memory_sync_hooks("delete", _sync_event()) == []


@pytest.mark.parametrize(
    "binding",
    [
        "invalid",
        {},
        {"script": "/hooks/sync", "timeout": 0},
        {"script": "/hooks/sync", "timeout": True},
        {"script": "/hooks/sync", "env_keys": "MEM_GRAPH_URL"},
        {"script": "/hooks/sync", "env_keys": ["OK", 1]},
    ],
)
def test_sync_dispatch_rejects_invalid_bindings(monkeypatch, binding):
    """Malformed bindings are skipped without invoking a subprocess."""
    monkeypatch.setenv(
        memory_hooks.MEMORY_SYNC_HOOKS_ENV_KEY,
        json.dumps({"create": [binding]}),
    )
    execute = mock.Mock()
    monkeypatch.setattr(memory_hooks.cmd_tool, "exec_cmd", execute)

    assert memory_hooks.dispatch_memory_sync_hooks("create", _sync_event()) == [None]
    execute.assert_not_called()


def test_sync_dispatch_rejects_non_list_bindings_and_incomplete_event(monkeypatch):
    """Invalid event binding containers and incomplete payloads fail open."""
    monkeypatch.setenv(
        memory_hooks.MEMORY_SYNC_HOOKS_ENV_KEY,
        json.dumps({"create": {"script": "/hooks/sync"}}),
    )
    assert memory_hooks.dispatch_memory_sync_hooks("create", _sync_event()) == []

    monkeypatch.setenv(
        memory_hooks.MEMORY_SYNC_HOOKS_ENV_KEY,
        json.dumps({"create": [{"script": "/hooks/sync"}]}),
    )
    event = _sync_event()
    event.pop("version")
    assert memory_hooks.dispatch_memory_sync_hooks("create", event) == []


def test_sync_dispatch_reports_nonzero_exit(monkeypatch, caplog):
    """A nonzero consumer status is returned and logged without raising."""
    monkeypatch.setenv(
        memory_hooks.MEMORY_SYNC_HOOKS_ENV_KEY,
        json.dumps({"create": [{"script": "/hooks/sync"}]}),
    )
    monkeypatch.setattr(
        memory_hooks.cmd_tool, "exec_cmd", mock.Mock(return_value=(1, "", "failed"))
    )

    with caplog.at_level("WARNING"):
        result = memory_hooks.dispatch_memory_sync_hooks("create", _sync_event())

    assert result == [(1, "", "failed")]
    assert "exited non-zero" in caplog.text


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ({"sync": [(0, "ok", "")]}, True),
        ({"sync": [None]}, False),
        ({"sync": [(1, "", "failed")]}, False),
        ({"sync": []}, False),
        ({}, False),
        (None, False),
    ],
)
def test_sync_dispatch_succeeded_requires_zero_exit(result, expected):
    """Only an actually executed zero-exit consumer is a successful dispatch."""
    assert memory_hooks.sync_dispatch_succeeded(result) is expected
