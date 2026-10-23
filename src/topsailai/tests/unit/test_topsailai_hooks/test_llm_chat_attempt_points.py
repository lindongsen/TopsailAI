"""Standalone LLM attempt Hook contracts. Author: DawsonLin."""

import asyncio
from dataclasses import replace
from importlib import import_module
import re
from types import SimpleNamespace

import pytest

import topsailai.hooks as hooks

PHASES = ("before", "after", "error")


def point(phase):
    """Import a real point package through its discoverable namespace."""
    return import_module(f"topsailai.hooks.points.aibase.{phase}_llm_chat_attempt")


def payload(phase):
    """Create the exact approved scalar field set for one checkpoint."""
    module = point(phase)
    value = dict(schema_version=1, operation_id="a" * 32, attempt_number=1,
                 point_name=module.NAME, outcome=module.POINT.phase,
                 stream=True, return_mode="parsed")
    if phase != "before":
        value["duration_sec"] = 0.25
    if phase == "error":
        value["error_category"] = "RuntimeError"
    return value


@pytest.mark.parametrize("phase", PHASES)
def test_declaration(phase):
    """Names, supported schemas and phase mappings import and validate cleanly."""
    module = point(phase)
    assert re.fullmatch(r"hook__aibase__(before|after|error)__llm_chat_attempt", module.NAME)
    assert module.NAME == module.POINT.definition.name == module.POINT.name
    assert module.POINT.phase == {"before": "before", "after": "success", "error": "error"}[phase]
    assert module.POINT.failure_policy == "report"
    assert module.POINT.definition.major_version == 1
    assert module.POINT.definition.payload_limit_bytes == 8192
    with pytest.raises(ValueError):
        replace(module.POINT, phase="error" if phase != "error" else "before")
    with pytest.raises(ValueError):
        replace(module.POINT, definition=replace(module.POINT.definition, name="other"))


@pytest.mark.parametrize("phase", PHASES)
@pytest.mark.parametrize("mode", ["raw", "parsed", "response_and_parsed"])
def test_valid_detached_payload(phase, mode):
    """All return modes and endpoint values yield detached scalar dictionaries."""
    module = point(phase)
    value = payload(phase)
    value.update(return_mode=mode, attempt_number=18, stream=False, operation_id="0123456789abcdef" * 2)
    if phase != "before":
        value["duration_sec"] = 0
    if phase == "error":
        value["error_category"] = "界" * 128
    result = module.build_payload(value, loop_attempts=18)
    assert result == value and result is not value
    value["operation_id"] = "b" * 32
    assert result["operation_id"] != value["operation_id"]


@pytest.mark.parametrize("phase", PHASES)
def test_missing_unknown_and_wrong_stage(phase):
    """Every required field and exact per-point allowlist is enforced."""
    module = point(phase)
    value = payload(phase)
    for key in value:
        candidate = dict(value)
        del candidate[key]
        with pytest.raises(ValueError):
            module.build_payload(candidate, loop_attempts=18)
    for key in ("messages", "credentials", "response", "exception", "loop_attempts"):
        with pytest.raises(ValueError):
            module.build_payload(dict(value, **{key: None}), loop_attempts=18)
    with pytest.raises(ValueError):
        module.build_payload([], loop_attempts=18)
    if phase == "before":
        with pytest.raises(ValueError):
            module.build_payload(dict(value, duration_sec=0), loop_attempts=18)
    if phase == "after":
        with pytest.raises(ValueError):
            module.build_payload(dict(value, error_category="Error"), loop_attempts=18)


INVALID = [
    ("schema_version", True), ("schema_version", 2), ("schema_version", "1"),
    ("operation_id", "a" * 31), ("operation_id", "a" * 33),
    ("operation_id", "A" * 32), ("operation_id", "g" * 32), ("operation_id", None),
    ("attempt_number", True), ("attempt_number", 0), ("attempt_number", 19),
    ("attempt_number", 1.0), ("point_name", "x" * 129), ("point_name", None),
    ("outcome", "after"), ("outcome", None), ("stream", 1),
    ("return_mode", "other"), ("return_mode", []),
]


@pytest.mark.parametrize("phase", PHASES)
@pytest.mark.parametrize("key,value", INVALID)
def test_invalid_common(phase, key, value):
    """Malformed types, enum values and length boundaries reject without coercion."""
    with pytest.raises(ValueError):
        point(phase).build_payload(dict(payload(phase), **{key: value}), loop_attempts=18)


@pytest.mark.parametrize("phase", PHASES)
@pytest.mark.parametrize("limit", [None, True, 0, -1, 18.0])
def test_invalid_context_bound(phase, limit):
    """The actual caller-supplied attempt limit is a positive exact integer."""
    with pytest.raises(ValueError):
        point(phase).build_payload(payload(phase), loop_attempts=limit)


@pytest.mark.parametrize("phase", ["after", "error"])
@pytest.mark.parametrize("duration", [-1, True, None, "0", float("nan"), float("inf"), -float("inf")])
def test_invalid_duration(phase, duration):
    """Terminal observations reject invalid and non-finite durations."""
    with pytest.raises(ValueError):
        point(phase).build_payload(dict(payload(phase), duration_sec=duration), loop_attempts=18)


@pytest.mark.parametrize("category", ["", "a" * 129, None, ValueError("private")])
def test_invalid_category(category):
    """Only bounded category strings, never exception instances, are accepted."""
    with pytest.raises(ValueError):
        point("error").build_payload(dict(payload("error"), error_category=category), loop_attempts=18)


def test_payload_byte_cap():
    """Even exact integers cannot exceed the aggregate serialized byte budget."""
    huge = 10 ** 4100
    value = dict(payload("after"), attempt_number=huge, duration_sec=huge)
    with pytest.raises(ValueError, match="attempt_payload_too_large"):
        point("after").build_payload(value, loop_attempts=huge)


@pytest.mark.parametrize("phase", PHASES)
def test_entry_preparation_and_dispatch_isolation(phase, monkeypatch):
    """Bad metadata never dispatches and ordinary execution failures stay isolated."""
    module = point(phase)
    entry = getattr(module, module.NAME)
    calls = []
    def dispatch(name, **metadata):
        """Record exact detached plugin metadata."""
        calls.append((name, metadata))
        return sentinel
    sentinel = object()
    monkeypatch.setattr(hooks, "invoke_hook_point", dispatch)
    assert entry(loop_attempts=18, **payload(phase)) is sentinel
    assert calls == [(module.NAME, payload(phase))]
    assert entry(loop_attempts=18, **dict(payload(phase), secret="DO_NOT_LOG")) is None
    assert entry(**payload(phase)) is None
    assert len(calls) == 1
    def fail(*args, **kwargs):
        """Simulate an ordinary dispatcher or diagnostic sink failure."""
        raise RuntimeError("failure")
    monkeypatch.setattr(hooks, "invoke_hook_point", fail)
    assert entry(loop_attempts=18, **payload(phase)) is None
    monkeypatch.setattr(module.logger, "error", fail)
    assert entry(loop_attempts=18, **payload(phase)) is None


@pytest.mark.parametrize("phase", PHASES)
@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit, asyncio.CancelledError])
def test_host_control_identity(phase, kind, monkeypatch):
    """Genuine host controls propagate as their original instances."""
    error = kind()
    def fail(*args, **kwargs):
        """Raise one exact host-control object."""
        raise error
    monkeypatch.setattr(hooks, "invoke_hook_point", fail)
    module = point(phase)
    with pytest.raises(kind) as caught:
        getattr(module, module.NAME)(loop_attempts=18, **payload(phase))
    assert caught.value is error


@pytest.mark.parametrize("phase", PHASES)
def test_real_discovery_and_plugin_failure(phase, tmp_path, monkeypatch):
    """Configured resources resolve the conventional point name without a catalog."""
    module = point(phase)
    plugin = tmp_path / "observer.py"
    plugin.write_text("def main(**payload):\n    return payload\n")
    monkeypatch.setattr(hooks, "_point_configuration", ())
    hooks.initialize_hook_points({module.NAME: {"modules": str(plugin)}})
    result = getattr(module, module.NAME)(loop_attempts=18, **payload(phase))
    assert result.status == "success"
    assert result.handlers[0].returned.value == payload(phase)
    assert result.handlers[-1].handler.name == "hook_script"
    assert result.handlers[-1].children == ()
    plugin.write_text("def main(**payload):\n    raise RuntimeError('observer failed')\n")
    result = getattr(module, module.NAME)(loop_attempts=18, **payload(phase))
    assert result.status == "completed_with_errors"
    assert result.handlers[0].error.category == "error"
    assert type(result.handlers[0].error.exception) is RuntimeError


@pytest.mark.parametrize("phase", PHASES)
@pytest.mark.parametrize("error_name", ["KeyboardInterrupt", "SystemExit", "CancelledError"])
def test_real_plugin_host_control(phase, error_name, tmp_path, monkeypatch):
    """Real Module execution preserves host-control exceptions through named entries."""
    module = point(phase)
    plugin = tmp_path / "host.py"
    prefix = "from asyncio import CancelledError\n" if error_name == "CancelledError" else ""
    plugin.write_text(prefix + f"def main(**payload):\n    raise {error_name}()\n")
    monkeypatch.setattr(hooks, "_point_configuration", ())
    hooks.initialize_hook_points({module.NAME: {"modules": str(plugin)}})
    kind = {"KeyboardInterrupt": KeyboardInterrupt, "SystemExit": SystemExit,
            "CancelledError": asyncio.CancelledError}[error_name]
    with pytest.raises(kind):
        getattr(module, module.NAME)(loop_attempts=18, **payload(phase))


def test_scalar_subclasses_and_nulls():
    """Exact built-ins and non-null fields disallow custom object behavior."""
    class Text(str):
        """Represent an unapproved custom scalar type."""
    for phase in PHASES:
        module = point(phase)
        for key in payload(phase):
            with pytest.raises(ValueError):
                module.build_payload(dict(payload(phase), **{key: None}), loop_attempts=18)
        with pytest.raises(ValueError):
            module.build_payload(dict(payload(phase), operation_id=Text("a" * 32)), loop_attempts=18)


@pytest.mark.parametrize("phase", PHASES)
@pytest.mark.parametrize("sink_broken", [False, True])
def test_diagnostic_fallback(phase, sink_broken, monkeypatch, capsys):
    """A failed logger has sanitized fallback output or an observable loss marker."""
    module = point(phase)
    writes = []
    def fail(*args, **kwargs):
        """Simulate a broken sink without leaking its error text."""
        raise RuntimeError("PRIVATE_SENTINEL")
    def write(message):
        """Capture a single fixed fallback diagnostic."""
        writes.append(message)
    monkeypatch.setattr(hooks, "invoke_hook_point", fail)
    monkeypatch.setattr(module.logger, "error", fail)
    monkeypatch.setattr(module.sys, "__stderr__", SimpleNamespace(write=fail if sink_broken else write))
    result = getattr(module, module.NAME)(loop_attempts=18, **payload(phase))
    assert result == ("diagnostic_unavailable" if sink_broken else None)
    assert writes == ([] if sink_broken else ["LLM attempt Hook diagnostic sink failed\n"])
    captured = capsys.readouterr()
    assert "PRIVATE_SENTINEL" not in captured.out + captured.err


@pytest.mark.parametrize("phase", PHASES)
@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit, asyncio.CancelledError])
@pytest.mark.parametrize("stage", ["logger", "fallback"])
def test_diagnostic_host_control_identity(phase, kind, stage, monkeypatch):
    """Both diagnostic stages preserve genuine host-control object identity."""
    module = point(phase)
    error = kind()
    def fail(*args, **kwargs):
        """Raise an ordinary observation or logger failure."""
        raise RuntimeError("unavailable")
    def interrupt(*args, **kwargs):
        """Raise the original host-control instance."""
        raise error
    monkeypatch.setattr(hooks, "invoke_hook_point", fail)
    monkeypatch.setattr(module.logger, "error", interrupt if stage == "logger" else fail)
    monkeypatch.setattr(module.sys, "__stderr__", SimpleNamespace(write=interrupt))
    with pytest.raises(kind) as caught:
        getattr(module, module.NAME)(loop_attempts=18, **payload(phase))
    assert caught.value is error
